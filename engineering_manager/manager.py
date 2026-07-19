"""EngineeringManager: the facade every interface talks to.

One object that owns the store, the provider registry, the event bus,
and the dispatcher, and exposes the operations a human (or a future CLI,
API, or UI) performs: manage projects and tasks, operate the two human
approval gates, manage accounts, and drive dispatch. Every mutation is
persisted, appended to the event log, and emitted on the bus.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path
from uuid import UUID

from engineering_manager.domain.account import ProviderAccount
from engineering_manager.domain.project import Project
from engineering_manager.domain.session import Session
from engineering_manager.domain.states import ProjectStatus, TaskStatus
from engineering_manager.domain.task import Task
from engineering_manager.domain.validation import (
    validate_account,
    validate_project,
    validate_task,
)
from engineering_manager.events import (
    AccountAdded,
    AccountRemoved,
    ProjectAdded,
    ProjectStatusChanged,
    TaskAdded,
    TaskStatusChanged,
)
from engineering_manager.exceptions import DomainValidationError
from engineering_manager.orchestration.dispatcher import SOURCE, Dispatcher
from engineering_manager.orchestration.policy import AssignmentPolicy
from engineering_manager.providers.base import Provider
from engineering_manager.providers.registry import ProviderRegistry
from engineering_manager.store.serialization import EventLogEntry
from engineering_manager.store.store import Store
from shared.events.bus import EventBus
from shared.events.event import Event

DEFAULT_LOGGER_NAME = "zenith.em"


class EngineeringManager:
    """Coordinates projects, tasks, accounts, providers, and sessions.

    The two human approval gates are explicit methods: `approve_task`
    (DRAFT -> READY, "yes, do this") and `accept_task`
    (NEEDS_REVIEW -> DONE, "yes, the work is good"). Everything between
    those gates can be driven without a human.
    """

    def __init__(
        self,
        store: Store,
        *,
        providers: ProviderRegistry | None = None,
        policy: AssignmentPolicy | None = None,
        bus: EventBus | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.store = store
        self.providers = providers or ProviderRegistry()
        self.events = bus or EventBus()
        self._logger = logger or logging.getLogger(DEFAULT_LOGGER_NAME)
        self.dispatcher = Dispatcher(
            store, self.providers, policy=policy, bus=self.events, logger=self._logger
        )

    def close(self) -> None:
        """Close the underlying store."""
        self.store.close()

    # -- providers ---------------------------------------------------------

    def register_provider(self, provider: Provider) -> None:
        """Make `provider` available for dispatch."""
        self.providers.register(provider)

    # -- projects ----------------------------------------------------------

    def add_project(
        self,
        project_id: str,
        name: str,
        root_path: Path,
        description: str | None = None,
    ) -> Project:
        """Place a repository under management.

        Raises:
            DomainValidationError: If the fields are invalid.
            DuplicateEntityError: If `project_id` is already managed.
        """
        project = Project(
            project_id=project_id, name=name, root_path=root_path, description=description
        )
        validate_project(project)
        self.store.add_project(project)
        self._publish(
            ProjectAdded(source=SOURCE, payload={"project_id": project_id, "name": name})
        )
        return project

    def set_project_status(self, project_id: str, status: ProjectStatus) -> Project:
        """Move a project to `status` (pause, reactivate, or archive it).

        Raises:
            ProjectNotFoundError: If `project_id` is not managed.
            DomainValidationError: If the transition is not permitted.
        """
        project = self.store.get_project(project_id)
        previous = project.status
        project.transition_to(status)
        self.store.update_project(project)
        self._publish(
            ProjectStatusChanged(
                source=SOURCE,
                payload={
                    "project_id": project_id,
                    "from": previous.name,
                    "to": status.name,
                },
            )
        )
        return project

    def get_project(self, project_id: str) -> Project:
        """Return the managed project with `project_id`."""
        return self.store.get_project(project_id)

    def list_projects(self, status: ProjectStatus | None = None) -> list[Project]:
        """Return managed projects, optionally filtered by status."""
        return self.store.list_projects(status=status)

    # -- tasks -------------------------------------------------------------

    def add_task(
        self,
        project_id: str,
        title: str,
        *,
        description: str | None = None,
        priority: int = 0,
        depends_on: Iterable[UUID] = (),
    ) -> Task:
        """Create a task in DRAFT.

        Dependencies must already exist and belong to the same project —
        which also makes dependency cycles impossible by construction,
        since a new task cannot yet be anyone's dependency.

        Raises:
            ProjectNotFoundError: If `project_id` is not managed.
            TaskNotFoundError: If a dependency does not exist.
            DomainValidationError: If the fields are invalid or a
                dependency belongs to another project.
        """
        self.store.get_project(project_id)
        dependency_ids = frozenset(depends_on)
        for dependency_id in dependency_ids:
            dependency = self.store.get_task(dependency_id)
            if dependency.project_id != project_id:
                raise DomainValidationError(
                    f"Dependency {dependency_id} belongs to project "
                    f"'{dependency.project_id}', not '{project_id}'."
                )
        task = Task(
            project_id=project_id,
            title=title,
            description=description,
            priority=priority,
            depends_on=dependency_ids,
        )
        validate_task(task)
        self.store.add_task(task)
        self._publish(
            TaskAdded(
                source=SOURCE,
                payload={
                    "task_id": str(task.task_id),
                    "project_id": project_id,
                    "title": title,
                },
            )
        )
        return task

    def approve_task(self, task_id: UUID) -> Task:
        """Human gate one: approve a DRAFT task for execution."""
        return self._transition_task(task_id, TaskStatus.READY)

    def accept_task(self, task_id: UUID) -> Task:
        """Human gate two: accept reviewed work as DONE."""
        return self._transition_task(task_id, TaskStatus.DONE)

    def rework_task(self, task_id: UUID) -> Task:
        """Send reviewed work back to READY for another attempt."""
        return self._transition_task(task_id, TaskStatus.READY)

    def retry_task(self, task_id: UUID) -> Task:
        """Return a FAILED task to READY."""
        return self._transition_task(task_id, TaskStatus.READY)

    def revise_task(self, task_id: UUID) -> Task:
        """Send a READY task back to DRAFT for refinement."""
        return self._transition_task(task_id, TaskStatus.DRAFT)

    def cancel_task(self, task_id: UUID) -> Task:
        """Cancel a task permanently."""
        return self._transition_task(task_id, TaskStatus.CANCELLED)

    def get_task(self, task_id: UUID) -> Task:
        """Return the task with `task_id`."""
        return self.store.get_task(task_id)

    def list_tasks(
        self, project_id: str | None = None, status: TaskStatus | None = None
    ) -> list[Task]:
        """Return tasks, optionally filtered."""
        return self.store.list_tasks(project_id=project_id, status=status)

    # -- accounts ----------------------------------------------------------

    def add_account(
        self, provider_id: str, account_id: str, label: str | None = None
    ) -> ProviderAccount:
        """Register an account as an execution resource.

        Raises:
            DomainValidationError: If the identifiers are invalid.
            DuplicateEntityError: If the pair is already registered.
        """
        account = ProviderAccount(provider_id=provider_id, account_id=account_id, label=label)
        validate_account(account)
        self.store.add_account(account)
        self._publish(
            AccountAdded(
                source=SOURCE,
                payload={"provider_id": provider_id, "account_id": account_id},
            )
        )
        return account

    def remove_account(self, provider_id: str, account_id: str) -> None:
        """Remove an account from the pool.

        Raises:
            AccountNotFoundError: If the pair is not registered.
        """
        self.store.remove_account(provider_id, account_id)
        self._publish(
            AccountRemoved(
                source=SOURCE,
                payload={"provider_id": provider_id, "account_id": account_id},
            )
        )

    def list_accounts(self, provider_id: str | None = None) -> list[ProviderAccount]:
        """Return registered accounts, optionally filtered by provider."""
        return self.store.list_accounts(provider_id=provider_id)

    # -- dispatch and sessions ---------------------------------------------

    def eligible_tasks(self, project_id: str | None = None) -> list[Task]:
        """Return dispatchable tasks, highest priority first."""
        return self.dispatcher.eligible_tasks(project_id=project_id)

    def dispatch(self, task_id: UUID | None = None, **kwargs: object) -> Session | None:
        """Dispatch a task to a provider session. See `Dispatcher.dispatch`."""
        return self.dispatcher.dispatch(task_id, **kwargs)  # type: ignore[arg-type]

    def complete_session(self, session_id: UUID, summary: str | None = None) -> Session:
        """Mark a session finished; its task moves to NEEDS_REVIEW."""
        return self.dispatcher.complete_session(session_id, summary)

    def fail_session(self, session_id: UUID, reason: str | None = None) -> Session:
        """Mark a session failed; its task moves to FAILED."""
        return self.dispatcher.fail_session(session_id, reason)

    def interrupt_session(self, session_id: UUID) -> Session:
        """Record a session interruption; the task stays IN_PROGRESS."""
        return self.dispatcher.interrupt_session(session_id)

    def resume_session(self, session_id: UUID) -> Session:
        """Resume an interrupted session through its provider."""
        return self.dispatcher.resume_session(session_id)

    def abandon_session(self, session_id: UUID, reason: str | None = None) -> Session:
        """Give up on a session; its task returns to READY."""
        return self.dispatcher.abandon_session(session_id, reason)

    def list_sessions(self, task_id: UUID | None = None) -> list[Session]:
        """Return sessions, optionally filtered by task."""
        return self.store.list_sessions(task_id=task_id)

    def list_events(self, limit: int | None = None) -> list[EventLogEntry]:
        """Return the persistent event log, newest first."""
        return self.store.list_events(limit=limit)

    # -- internals ---------------------------------------------------------

    def _transition_task(self, task_id: UUID, new_status: TaskStatus) -> Task:
        """Transition a task, persist it, and publish the change.

        Raises:
            TaskNotFoundError: If `task_id` is not in the store.
            DomainValidationError: If the transition is not permitted.
        """
        task = self.store.get_task(task_id)
        previous = task.status
        task.transition_to(new_status)
        self.store.update_task(task)
        self._publish(
            TaskStatusChanged(
                source=SOURCE,
                payload={
                    "task_id": str(task.task_id),
                    "project_id": task.project_id,
                    "from": previous.name,
                    "to": task.status.name,
                },
            )
        )
        return task

    def _publish(self, event: Event) -> None:
        """Append `event` to the persistent log, then emit it on the bus."""
        self.store.append_event(event)
        self.events.emit(event)

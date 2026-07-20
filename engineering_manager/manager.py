"""EngineeringManager: the facade every interface talks to.

One object that owns the store, the provider registry, the event bus,
the dispatcher, the plan coordinator, and the execution engine, and
exposes the operations a human (or a future CLI, API, or UI) performs:
manage projects, plans, and tasks, operate the human approval gates,
manage accounts, and drive execution. Every mutation is persisted,
appended to the event log, and emitted on the bus. The facade itself
stays thin — lifecycle logic lives in `orchestration/`.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path
from uuid import UUID

from engineering_manager.domain.account import ProviderAccount
from engineering_manager.domain.plan import Plan
from engineering_manager.domain.project import Project
from engineering_manager.domain.session import Session
from engineering_manager.domain.states import (
    TERMINAL_PLAN_STATUSES,
    PlanStatus,
    ProjectStatus,
    TaskStatus,
)
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
    TaskDependencyAdded,
    TaskStatusChanged,
)
from engineering_manager.exceptions import DomainValidationError
from engineering_manager.orchestration.dispatcher import SOURCE, Dispatcher
from engineering_manager.orchestration.engine import ExecutionEngine, TickReport
from engineering_manager.orchestration.graph import Blockage, blockages, would_create_cycle
from engineering_manager.orchestration.plans import PlanCoordinator
from engineering_manager.orchestration.policy import AssignmentPolicy
from engineering_manager.orchestration.retry import RetryPolicy
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
        retry_policy: RetryPolicy | None = None,
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
        self.engine = ExecutionEngine(
            store,
            self.dispatcher,
            self.providers,
            retry_policy=retry_policy,
            bus=self.events,
            logger=self._logger,
        )
        self._plans = PlanCoordinator(store, bus=self.events, logger=self._logger)

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

    # -- plans -------------------------------------------------------------

    def add_plan(self, project_id: str, goal: str, description: str | None = None) -> Plan:
        """Record a high-level goal as a plan in DRAFT."""
        return self._plans.add_plan(project_id, goal, description)

    def approve_plan(self, plan_id: UUID) -> Plan:
        """Human gate one, in bulk: approve a plan and its DRAFT tasks."""
        return self._plans.approve_plan(plan_id)

    def cancel_plan(self, plan_id: UUID) -> Plan:
        """Cancel a plan and every one of its non-terminal tasks."""
        return self._plans.cancel_plan(plan_id)

    def get_plan(self, plan_id: UUID) -> Plan:
        """Return the plan with `plan_id`."""
        return self.store.get_plan(plan_id)

    def list_plans(
        self, project_id: str | None = None, status: PlanStatus | None = None
    ) -> list[Plan]:
        """Return plans, optionally filtered."""
        return self.store.list_plans(project_id=project_id, status=status)

    def plan_tasks(self, plan_id: UUID) -> list[Task]:
        """Return the tasks decomposing the plan with `plan_id`."""
        self.store.get_plan(plan_id)
        return self.store.list_tasks(plan_id=plan_id)

    # -- tasks -------------------------------------------------------------

    def add_task(
        self,
        project_id: str,
        title: str,
        *,
        description: str | None = None,
        priority: int = 0,
        depends_on: Iterable[UUID] = (),
        plan_id: UUID | None = None,
    ) -> Task:
        """Create a task in DRAFT.

        Dependencies must already exist and belong to the same project —
        which also makes dependency cycles impossible at creation, since
        a new task cannot yet be anyone's dependency (cycles are guarded
        again in `add_task_dependency`, where the graph can evolve).
        `plan_id` ties the task to a plan, which must belong to the same
        project and not be terminal — discovered work may join a plan
        that is already IN_PROGRESS.

        Raises:
            ProjectNotFoundError: If `project_id` is not managed.
            TaskNotFoundError: If a dependency does not exist.
            PlanNotFoundError: If `plan_id` is given but not in the store.
            DomainValidationError: If the fields are invalid, a
                dependency belongs to another project, or the plan
                cannot accept tasks.
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
        if plan_id is not None:
            plan = self.store.get_plan(plan_id)
            if plan.project_id != project_id:
                raise DomainValidationError(
                    f"Plan {plan_id} belongs to project '{plan.project_id}', "
                    f"not '{project_id}'."
                )
            if plan.status in TERMINAL_PLAN_STATUSES:
                raise DomainValidationError(
                    f"Plan {plan_id} is {plan.status.name}; tasks can no longer "
                    "be added to it."
                )
        task = Task(
            project_id=project_id,
            title=title,
            description=description,
            priority=priority,
            depends_on=dependency_ids,
            plan_id=plan_id,
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

    def add_task_dependency(self, task_id: UUID, depends_on_id: UUID) -> Task:
        """Make an existing task depend on another — the graph evolving.

        This is how discovered work reshapes execution: create the new
        task, then require it before work that is already planned. The
        dependency must exist, share the task's project, not be
        cancelled, and not create a cycle.

        Raises:
            TaskNotFoundError: If either task is not in the store.
            DomainValidationError: If the tasks are in different
                projects, the dependency is cancelled, the edge would
                create a cycle, or the task can no longer gain
                dependencies.
        """
        task = self.store.get_task(task_id)
        dependency = self.store.get_task(depends_on_id)
        if dependency.project_id != task.project_id:
            raise DomainValidationError(
                f"Dependency {depends_on_id} belongs to project "
                f"'{dependency.project_id}', not '{task.project_id}'."
            )
        if dependency.status is TaskStatus.CANCELLED:
            raise DomainValidationError(
                f"Task {task_id} cannot depend on cancelled task {depends_on_id}."
            )
        tasks_by_id = {
            candidate.task_id: candidate
            for candidate in self.store.list_tasks(project_id=task.project_id)
        }
        if would_create_cycle(tasks_by_id, task_id, depends_on_id):
            raise DomainValidationError(
                f"Making task {task_id} depend on {depends_on_id} would create "
                "a dependency cycle."
            )
        task.add_dependency(depends_on_id)
        self.store.update_task(task)
        self._publish(
            TaskDependencyAdded(
                source=SOURCE,
                payload={
                    "task_id": str(task_id),
                    "depends_on": str(depends_on_id),
                    "project_id": task.project_id,
                },
            )
        )
        return task

    def approve_task(self, task_id: UUID) -> Task:
        """Human gate one: approve a DRAFT task for execution."""
        return self._transition_task(task_id, TaskStatus.READY)

    def accept_task(self, task_id: UUID) -> Task:
        """Human gate two: accept reviewed work as DONE."""
        task = self._transition_task(task_id, TaskStatus.DONE)
        self._plans.note_task_terminal(task)
        return task

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
        task = self._transition_task(task_id, TaskStatus.CANCELLED)
        self._plans.note_task_terminal(task)
        return task

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

    # -- execution ---------------------------------------------------------

    def tick(self) -> TickReport:
        """Advance every session, task, and plan one deterministic step."""
        return self.engine.tick()

    def run(self, **kwargs: object) -> None:
        """Run the execution engine's polling loop. See `ExecutionEngine.run`."""
        self.engine.run(**kwargs)  # type: ignore[arg-type]

    def blocked_tasks(self, project_id: str | None = None) -> list[Blockage]:
        """Report tasks whose dependencies hold them back — or doom them."""
        return blockages(self.store.list_tasks(project_id=project_id))

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

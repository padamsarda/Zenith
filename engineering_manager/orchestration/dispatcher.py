"""Dispatcher: turns eligible tasks into provider sessions and drives
those sessions through their lifecycle.

The dispatcher is the only code that talks to providers. Every state
change it makes is persisted to the `Store` and announced as an event —
both on the in-process `EventBus` (for live subscribers) and in the
store's event log (for audit and history).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from engineering_manager.domain.session import Session
from engineering_manager.domain.states import (
    PlanStatus,
    ProjectStatus,
    SessionStatus,
    TaskStatus,
)
from engineering_manager.domain.task import Task
from engineering_manager.events import SessionStarted, SessionStatusChanged, TaskStatusChanged
from engineering_manager.exceptions import OrchestrationError, ProviderSessionError
from engineering_manager.orchestration.context import ContextAssembler
from engineering_manager.orchestration.policy import AssignmentPolicy, FirstAvailablePolicy
from engineering_manager.orchestration.revisions import NoRevisionProbe, RevisionProbe
from engineering_manager.providers.base import SessionHandle, SessionSpec
from engineering_manager.providers.registry import ProviderRegistry
from engineering_manager.store.store import Store
from shared.events.bus import EventBus
from shared.events.event import Event
from shared.utils.uuid_utils import generate_id

DEFAULT_LOGGER_NAME = "zenith.em"
SOURCE = "engineering_manager"

# Sessions in these statuses occupy their account.
OPEN_SESSION_STATUSES: tuple[SessionStatus, ...] = (
    SessionStatus.ACTIVE,
    SessionStatus.INTERRUPTED,
)


class Dispatcher:
    """Assigns eligible tasks to provider accounts and manages sessions.

    A task is *eligible* when it is `READY`, belongs to an `ACTIVE`
    project, and every task it depends on is `DONE`. `dispatch` pairs
    the highest-priority eligible task with an account chosen by the
    `AssignmentPolicy`, starts a provider session for it, and records
    the resulting `Session`. The session-lifecycle methods
    (`complete_session`, `fail_session`, `interrupt_session`,
    `resume_session`, `abandon_session`) keep the session and its task
    in lockstep from then on.

    The `RevisionProbe` brackets that lifecycle: the project's revision
    is stamped on the session at dispatch and again when the session
    closes, so what the session changed can be measured later instead of
    taken on the provider's word (ADR 0023). It defaults to
    `NoRevisionProbe`, which records nothing.
    """

    def __init__(
        self,
        store: Store,
        providers: ProviderRegistry,
        *,
        policy: AssignmentPolicy | None = None,
        context: ContextAssembler | None = None,
        revision_probe: RevisionProbe | None = None,
        bus: EventBus | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._store = store
        self._providers = providers
        self._policy = policy or FirstAvailablePolicy()
        self._context = context or ContextAssembler(store)
        self._revision_probe = revision_probe or NoRevisionProbe()
        self._bus = bus or EventBus()
        self._logger = logger or logging.getLogger(DEFAULT_LOGGER_NAME)

    def set_revision_probe(self, probe: RevisionProbe) -> None:
        """Replace the probe that stamps revisions around each session.

        Mirrors `ExecutionEngine.set_verification_policy`: a caller (the
        CLI) often only knows which probe it wants once arguments are
        parsed, by which time the dispatcher already exists.
        """
        self._revision_probe = probe

    def eligible_tasks(self, project_id: str | None = None) -> list[Task]:
        """Return dispatchable tasks, highest priority first.

        A task qualifies when it is `READY`, its project is `ACTIVE`,
        its plan (if it belongs to one) is `IN_PROGRESS`, and all of its
        dependencies are `DONE`. Ties in priority break by creation
        time, oldest first.
        """
        active_projects = {
            project.project_id
            for project in self._store.list_projects(status=ProjectStatus.ACTIVE)
        }
        approved_plans = {
            plan.plan_id
            for plan in self._store.list_plans(status=PlanStatus.IN_PROGRESS)
        }
        candidates = [
            task
            for task in self._store.list_tasks(project_id=project_id, status=TaskStatus.READY)
            if task.project_id in active_projects
            and (task.plan_id is None or task.plan_id in approved_plans)
            and self._dependencies_done(task)
        ]
        return sorted(candidates, key=lambda task: (-task.priority, task.created_at))

    def dispatch(
        self,
        task_id: UUID | None = None,
        *,
        model: str | None = None,
        instructions: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Session | None:
        """Start a provider session for a task and record it.

        With `task_id`, dispatches exactly that task and raises if it
        cannot; without, picks the highest-priority eligible task and
        returns None when there is nothing to do or every account is
        occupied — the normal idle states of a polling loop.

        Raises:
            OrchestrationError: If the named task is not eligible, if no
                account with a registered provider exists at all, or if
                the named task cannot get an account.
            ProviderSessionError: If the provider fails to start the
                session. Nothing is persisted in that case; the task
                stays READY.
        """
        task = self._select_task(task_id)
        if task is None:
            return None

        accounts = [
            account
            for account in self._store.list_accounts()
            if self._providers.has(account.provider_id)
        ]
        if not accounts:
            raise OrchestrationError(
                "No accounts with a registered provider are configured; "
                "add an account and register its provider."
            )

        open_sessions = self._store.list_sessions(statuses=OPEN_SESSION_STATUSES)
        account = self._policy.choose_account(task, accounts, open_sessions)
        if account is None:
            if task_id is not None:
                raise OrchestrationError(
                    f"No account is available for task {task_id} right now."
                )
            return None

        project = self._store.get_project(task.project_id)
        provider = self._providers.get(account.provider_id)
        session_id = generate_id()
        spec = SessionSpec(
            session_id=session_id,
            project=project,
            task=task,
            account_id=account.account_id,
            model=model,
            instructions=instructions or self._context.briefing(task, project),
            metadata=metadata or {},
        )
        handle = provider.start_session(spec)

        session = Session(
            session_id=session_id,
            task_id=task.task_id,
            project_id=task.project_id,
            provider_id=account.provider_id,
            account_id=account.account_id,
            model=model,
            external_ref=handle.external_ref,
        )
        # Stamped before the session is stored, so the baseline is part
        # of the row from the moment it exists rather than an update the
        # next crash could lose.
        starting_revision = self._revision_probe.current_revision(project)
        if starting_revision is not None:
            session.stamp_starting_revision(starting_revision)
        self._transition_task(task, TaskStatus.IN_PROGRESS)
        self._store.add_session(session)
        self._logger.info(
            "Dispatched task '%s' (%s) to %s/%s as session %s.",
            task.title,
            task.task_id,
            account.provider_id,
            account.account_id,
            session_id,
        )
        self._publish(
            SessionStarted(
                source=SOURCE,
                payload={
                    "session_id": str(session.session_id),
                    "task_id": str(task.task_id),
                    "project_id": task.project_id,
                    "provider_id": account.provider_id,
                    "account_id": account.account_id,
                },
            )
        )
        return session

    def complete_session(self, session_id: UUID, summary: str | None = None) -> Session:
        """Mark a session's work finished; its task moves to NEEDS_REVIEW.

        Raises:
            SessionNotFoundError: If `session_id` is not in the store.
            DomainValidationError: If the session is not in a status
                that can complete.
        """
        session = self._store.get_session(session_id)
        self._end_session(session, SessionStatus.COMPLETED, summary)
        task = self._store.get_task(session.task_id)
        self._transition_task(task, TaskStatus.NEEDS_REVIEW)
        self._logger.info("Session %s completed; task %s awaits review.", session_id, task.task_id)
        return session

    def fail_session(self, session_id: UUID, reason: str | None = None) -> Session:
        """Mark a session failed; its task moves to FAILED.

        Raises:
            SessionNotFoundError: If `session_id` is not in the store.
            DomainValidationError: If the session is not in a status
                that can fail.
        """
        session = self._store.get_session(session_id)
        self._end_session(session, SessionStatus.FAILED, reason)
        task = self._store.get_task(session.task_id)
        self._transition_task(task, TaskStatus.FAILED)
        self._logger.warning("Session %s failed: %s", session_id, reason or "(no reason)")
        return session

    def interrupt_session(
        self, session_id: UUID, resume_at: datetime | None = None
    ) -> Session:
        """Record that a session was interrupted (e.g. a session limit).

        The task stays IN_PROGRESS — the work is paused, not lost.
        `resume_at` is when the execution engine may resume the session
        automatically; without one, the session waits for a human
        (`resume_session`).

        Raises:
            SessionNotFoundError: If `session_id` is not in the store.
            DomainValidationError: If the session is not ACTIVE.
        """
        session = self._store.get_session(session_id)
        previous = session.status
        session.transition_to(SessionStatus.INTERRUPTED)
        session.set_resume_at(resume_at)
        self._store.update_session(session)
        self._logger.info(
            "Session %s interrupted%s.",
            session_id,
            f"; may auto-resume at {resume_at.isoformat()}" if resume_at else "",
        )
        self._publish_session_change(session, previous)
        return session

    def resume_session(self, session_id: UUID) -> Session:
        """Resume an INTERRUPTED session through its provider.

        Raises:
            SessionNotFoundError: If `session_id` is not in the store.
            DomainValidationError: If the session is not INTERRUPTED.
            OrchestrationError: If the session has no external_ref to
                resume from.
            ProviderNotFoundError: If the session's provider is no
                longer registered.
            ProviderSessionError: If the provider cannot resume it.
        """
        session = self._store.get_session(session_id)
        previous = session.status
        if session.external_ref is None:
            raise OrchestrationError(
                f"Session {session_id} has no external_ref; it cannot be resumed."
            )
        provider = self._providers.get(session.provider_id)
        handle = provider.resume_session(
            SessionHandle(provider_id=session.provider_id, external_ref=session.external_ref)
        )
        session.transition_to(SessionStatus.ACTIVE)
        session.update_external_ref(handle.external_ref)
        session.set_resume_at(None)
        self._store.update_session(session)
        self._logger.info("Session %s resumed as %s.", session_id, handle.external_ref)
        self._publish_session_change(session, previous)
        return session

    def abandon_session(self, session_id: UUID, reason: str | None = None) -> Session:
        """Give up on a session; its task returns to READY for redispatch.

        Asks the provider to stop the session if it can; a provider
        error at that point is logged, not raised — the bookkeeping
        still completes.

        Raises:
            SessionNotFoundError: If `session_id` is not in the store.
            DomainValidationError: If the session is already terminal.
        """
        session = self._store.get_session(session_id)
        self._stop_provider_session(session)
        self._end_session(session, SessionStatus.ABANDONED, reason)
        task = self._store.get_task(session.task_id)
        self._transition_task(task, TaskStatus.READY)
        self._logger.info("Session %s abandoned; task %s back to READY.", session_id, task.task_id)
        return session

    def _select_task(self, task_id: UUID | None) -> Task | None:
        """Resolve which task to dispatch, or None when idle.

        Raises:
            OrchestrationError: If a named task is not eligible.
        """
        if task_id is None:
            eligible = self.eligible_tasks()
            return eligible[0] if eligible else None

        task = self._store.get_task(task_id)
        eligible_ids = {eligible.task_id for eligible in self.eligible_tasks()}
        if task.task_id not in eligible_ids:
            raise OrchestrationError(
                f"Task {task_id} is not eligible for dispatch "
                f"(status {task.status.name}; it must be READY, in an ACTIVE "
                "project, with all dependencies DONE)."
            )
        return task

    def _dependencies_done(self, task: Task) -> bool:
        """Return True if every dependency of `task` is DONE."""
        return all(
            self._store.get_task(dependency_id).status is TaskStatus.DONE
            for dependency_id in task.depends_on
        )

    def _end_session(
        self, session: Session, status: SessionStatus, summary: str | None
    ) -> None:
        """Transition `session` to a terminal `status`, close, persist, publish.

        Every terminal status is stamped, not just `COMPLETED`: what a
        failed or abandoned session left behind is exactly as much a fact
        as what a successful one did, and often a more interesting one.
        """
        # Probed before the transition so that a probe breaking its
        # contract and returning a non-string cannot leave the session
        # transitioned but unclosed.
        ending_revision = self._revision_probe.current_revision(
            self._store.get_project(session.project_id)
        )
        previous = session.status
        session.transition_to(status)
        session.close(summary, ending_revision=ending_revision)
        self._store.update_session(session)
        self._publish_session_change(session, previous)

    def _stop_provider_session(self, session: Session) -> None:
        """Best-effort stop of the provider-side session, if reachable."""
        if session.external_ref is None or not self._providers.has(session.provider_id):
            return
        handle = SessionHandle(
            provider_id=session.provider_id, external_ref=session.external_ref
        )
        try:
            self._providers.get(session.provider_id).stop_session(handle)
        except ProviderSessionError as exc:
            self._logger.warning(
                "Provider could not stop session %s: %s", session.session_id, exc
            )

    def _transition_task(self, task: Task, new_status: TaskStatus) -> None:
        """Transition `task`, persist it, and publish the change."""
        previous = task.status
        task.transition_to(new_status)
        self._store.update_task(task)
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

    def _publish_session_change(self, session: Session, previous: SessionStatus) -> None:
        """Publish a SessionStatusChanged for `session`."""
        self._publish(
            SessionStatusChanged(
                source=SOURCE,
                payload={
                    "session_id": str(session.session_id),
                    "task_id": str(session.task_id),
                    "from": previous.name,
                    "to": session.status.name,
                },
            )
        )

    def _publish(self, event: Event) -> None:
        """Append `event` to the persistent log, then emit it on the bus."""
        self._store.append_event(event)
        self._bus.emit(event)

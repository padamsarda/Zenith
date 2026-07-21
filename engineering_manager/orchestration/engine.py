"""ExecutionEngine: the reconcile-and-advance loop that drives all work.

One `tick()` moves the whole system as far forward as it can go, in a
fixed order: reconcile every ACTIVE session against what its provider
actually reports, resume interrupted sessions whose `resume_at` has
passed, re-queue failed tasks the `RetryPolicy` approves, and dispatch
eligible work until accounts run out. Because every fact the engine
acts on lives in the store, recovery after a crash or restart is not a
special path — the next tick reconciles persisted state against
provider truth exactly the way an ordinary tick does (ADR 0008).
`run()` is nothing but `tick()` on an interval; all decisions live in
the tick so they stay synchronous, deterministic, and testable
(ADR 0007).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from engineering_manager.domain.session import Session
from engineering_manager.domain.states import SessionStatus, TaskStatus
from engineering_manager.domain.task import Task
from engineering_manager.events import AttentionRequired, TaskStatusChanged
from engineering_manager.exceptions import (
    OrchestrationError,
    ProviderNotFoundError,
    ProviderSessionError,
)
from engineering_manager.orchestration.dispatcher import SOURCE, Dispatcher
from engineering_manager.orchestration.retry import LimitedRetryPolicy, RetryPolicy
from engineering_manager.orchestration.verification import (
    NoVerificationPolicy,
    VerificationPolicy,
)
from engineering_manager.providers.base import ProviderSessionState, SessionHandle
from engineering_manager.providers.registry import ProviderRegistry
from engineering_manager.store.store import Store
from shared.events.bus import EventBus
from shared.events.event import Event
from shared.utils.time_utils import utc_now

DEFAULT_LOGGER_NAME = "zenith.em"

# When a provider reports LIMIT_REACHED without saying when the limit
# resets, wait this long before trying to resume.
DEFAULT_LIMIT_BACKOFF = timedelta(minutes=30)

DEFAULT_TICK_INTERVAL_SECONDS = 30.0


@dataclass(frozen=True)
class TickReport:
    """Everything one call to `ExecutionEngine.tick` changed.

    `attention` holds human-readable notices about conditions a human
    must resolve; the run loop logs them, and matching
    `AttentionRequired` events are published once, at the moment the
    condition arises.
    """

    sessions_completed: tuple[UUID, ...] = ()
    sessions_failed: tuple[UUID, ...] = ()
    sessions_interrupted: tuple[UUID, ...] = ()
    sessions_resumed: tuple[UUID, ...] = ()
    tasks_retried: tuple[UUID, ...] = ()
    tasks_exhausted: tuple[UUID, ...] = ()
    sessions_started: tuple[UUID, ...] = ()
    attention: tuple[str, ...] = ()

    @property
    def idle(self) -> bool:
        """True when the tick found nothing to change."""
        return not (
            self.sessions_completed
            or self.sessions_failed
            or self.sessions_interrupted
            or self.sessions_resumed
            or self.tasks_retried
            or self.sessions_started
        )


class ExecutionEngine:
    """Advances every session, task, and plan as far as facts allow."""

    def __init__(
        self,
        store: Store,
        dispatcher: Dispatcher,
        providers: ProviderRegistry,
        *,
        retry_policy: RetryPolicy | None = None,
        verification_policy: VerificationPolicy | None = None,
        bus: EventBus | None = None,
        clock: Callable[[], datetime] = utc_now,
        limit_backoff: timedelta = DEFAULT_LIMIT_BACKOFF,
        logger: logging.Logger | None = None,
    ) -> None:
        self._store = store
        self._dispatcher = dispatcher
        self._providers = providers
        self._retry_policy = retry_policy or LimitedRetryPolicy()
        self._verification_policy = verification_policy or NoVerificationPolicy()
        self._bus = bus or EventBus()
        self._clock = clock
        self._limit_backoff = limit_backoff
        self._logger = logger or logging.getLogger(DEFAULT_LOGGER_NAME)

    def set_verification_policy(self, policy: VerificationPolicy) -> None:
        """Replace the policy that checks a session's claimed completion.

        Mirrors `AssistantEngine.set_permission_policy` in the runtime:
        a policy seam that can be reconfigured after construction, since
        callers (e.g. the CLI) often only know the desired policy once
        arguments are parsed, after the engine already exists.
        """
        self._verification_policy = policy

    def tick(self) -> TickReport:
        """Advance the system one deterministic step and report what moved."""
        now = self._clock()
        completed, failed, interrupted, attention = self._reconcile_active_sessions(now)
        resumed, resume_failures = self._resume_due_sessions(now)
        failed_this_tick = {
            self._store.get_session(session_id).task_id
            for session_id in (*failed, *resume_failures)
        }
        retried, exhausted, retry_attention = self._retry_failed_tasks(failed_this_tick)
        started, dispatch_attention = self._dispatch_until_saturated()
        return TickReport(
            sessions_completed=tuple(completed),
            sessions_failed=tuple((*failed, *resume_failures)),
            sessions_interrupted=tuple(interrupted),
            sessions_resumed=tuple(resumed),
            tasks_retried=tuple(retried),
            tasks_exhausted=tuple(exhausted),
            sessions_started=tuple(started),
            attention=tuple((*attention, *retry_attention, *dispatch_attention)),
        )

    def run(
        self,
        *,
        interval_seconds: float = DEFAULT_TICK_INTERVAL_SECONDS,
        max_ticks: int | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Tick on an interval until `max_ticks` or a KeyboardInterrupt.

        `sleep` is injectable so tests (and callers with their own
        pacing) never wait on a real clock.
        """
        ticks = 0
        try:
            while max_ticks is None or ticks < max_ticks:
                report = self.tick()
                ticks += 1
                if not report.idle:
                    self._logger.info(
                        "Tick %d: %d completed, %d failed, %d interrupted, "
                        "%d resumed, %d retried, %d started.",
                        ticks,
                        len(report.sessions_completed),
                        len(report.sessions_failed),
                        len(report.sessions_interrupted),
                        len(report.sessions_resumed),
                        len(report.tasks_retried),
                        len(report.sessions_started),
                    )
                for notice in report.attention:
                    self._logger.warning("Attention: %s", notice)
                if max_ticks is None or ticks < max_ticks:
                    sleep(interval_seconds)
        except KeyboardInterrupt:
            self._logger.info("Execution engine stopped after %d tick(s).", ticks)

    # -- tick phases -------------------------------------------------------

    def _reconcile_active_sessions(
        self, now: datetime
    ) -> tuple[list[UUID], list[UUID], list[UUID], list[str]]:
        """Align every ACTIVE session with what its provider reports."""
        completed: list[UUID] = []
        failed: list[UUID] = []
        interrupted: list[UUID] = []
        attention: list[str] = []
        for session in self._store.list_sessions(statuses=(SessionStatus.ACTIVE,)):
            if session.external_ref is None or not self._providers.has(session.provider_id):
                self._logger.warning(
                    "Session %s cannot be checked (provider '%s' unavailable).",
                    session.session_id,
                    session.provider_id,
                )
                continue
            handle = SessionHandle(
                provider_id=session.provider_id, external_ref=session.external_ref
            )
            try:
                status = self._providers.get(session.provider_id).check_session(handle)
            except ProviderSessionError as exc:
                # The provider no longer knows the session: the work is
                # lost (crash, eviction). Record the failure; the retry
                # phase decides whether the task runs again.
                self._dispatcher.fail_session(
                    session.session_id, reason=f"Provider lost the session: {exc}"
                )
                failed.append(session.session_id)
                continue
            if status.state is ProviderSessionState.FINISHED:
                if self._verify_completion(session, status.detail):
                    completed.append(session.session_id)
                else:
                    failed.append(session.session_id)
            elif status.state is ProviderSessionState.FAILED:
                self._dispatcher.fail_session(session.session_id, reason=status.detail)
                failed.append(session.session_id)
            elif status.state is ProviderSessionState.LIMIT_REACHED:
                resume_at = status.resume_at or now + self._limit_backoff
                self._dispatcher.interrupt_session(session.session_id, resume_at=resume_at)
                interrupted.append(session.session_id)
            elif status.state is ProviderSessionState.AWAITING_INPUT:
                self._dispatcher.interrupt_session(session.session_id, resume_at=None)
                interrupted.append(session.session_id)
                attention.append(self._report_awaiting_input(session, status.detail))
        return completed, failed, interrupted, attention

    def _resume_due_sessions(self, now: datetime) -> tuple[list[UUID], list[UUID]]:
        """Resume INTERRUPTED sessions whose `resume_at` has passed."""
        resumed: list[UUID] = []
        failures: list[UUID] = []
        for session in self._store.list_sessions(statuses=(SessionStatus.INTERRUPTED,)):
            if session.resume_at is None or session.resume_at > now:
                continue
            if not self._providers.has(session.provider_id):
                self._logger.warning(
                    "Session %s is due to resume but provider '%s' is not registered.",
                    session.session_id,
                    session.provider_id,
                )
                continue
            try:
                self._dispatcher.resume_session(session.session_id)
                resumed.append(session.session_id)
            except (ProviderSessionError, OrchestrationError) as exc:
                self._dispatcher.fail_session(
                    session.session_id, reason=f"Resume failed: {exc}"
                )
                failures.append(session.session_id)
        return resumed, failures

    def _retry_failed_tasks(
        self, failed_this_tick: set[UUID]
    ) -> tuple[list[UUID], list[UUID], list[str]]:
        """Re-queue FAILED tasks the retry policy approves.

        Tasks the policy declines stay FAILED for a human; an
        `AttentionRequired` event fires only for tasks that failed
        during this tick, so standing failures are reported in the
        `TickReport` without re-publishing every interval.
        """
        retried: list[UUID] = []
        exhausted: list[UUID] = []
        attention: list[str] = []
        for task in self._store.list_tasks(status=TaskStatus.FAILED):
            failed_sessions = [
                session
                for session in self._store.list_sessions(task_id=task.task_id)
                if session.status is SessionStatus.FAILED
            ]
            if self._retry_policy.should_retry(task, failed_sessions):
                self._transition_task_to_ready(task)
                retried.append(task.task_id)
            else:
                exhausted.append(task.task_id)
                attention.append(
                    f"Task {task.task_id} ('{task.title}') has exhausted its "
                    f"retries after {len(failed_sessions)} failed attempt(s)."
                )
                if task.task_id in failed_this_tick:
                    self._report_retries_exhausted(task, len(failed_sessions))
        return retried, exhausted, attention

    def _dispatch_until_saturated(self) -> tuple[list[UUID], list[str]]:
        """Dispatch eligible tasks until none remain or accounts run out."""
        started: list[UUID] = []
        attention: list[str] = []
        while True:
            try:
                session = self._dispatcher.dispatch()
            except OrchestrationError as exc:
                # No account has a registered provider — a standing
                # configuration gap, not a per-task failure.
                attention.append(str(exc))
                break
            except (ProviderSessionError, ProviderNotFoundError) as exc:
                # The chosen provider could not start the session; the
                # task stayed READY. Stop for this tick rather than
                # hammering a failing provider.
                self._logger.warning("Dispatch stopped for this tick: %s", exc)
                break
            if session is None:
                break
            started.append(session.session_id)
        return started, attention

    # -- internals ---------------------------------------------------------

    def _verify_completion(self, session: Session, provider_detail: str | None) -> bool:
        """Check a FINISHED session's claim before trusting it; complete or fail it.

        Runs the configured `VerificationPolicy` against the session's
        task and project. A pass completes the session exactly as before
        (`provider_detail` as the summary); a failure fails the session
        instead, with the verification's own detail as the reason — an
        ordinary recoverable failure the retry phase re-evaluates like
        any other, not a new terminal outcome.

        Returns True if the session completed, False if it failed.
        """
        task = self._store.get_task(session.task_id)
        project = self._store.get_project(session.project_id)
        result = self._verification_policy.verify(task, project)
        if result.passed:
            self._dispatcher.complete_session(session.session_id, summary=provider_detail)
            return True
        self._dispatcher.fail_session(
            session.session_id,
            reason=result.detail or "Verification failed with no detail.",
        )
        return False

    def _transition_task_to_ready(self, task: Task) -> None:
        """Return a FAILED task to READY for another attempt."""
        previous = task.status
        task.transition_to(TaskStatus.READY)
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
        self._logger.info("Task %s re-queued for retry.", task.task_id)

    def _report_awaiting_input(self, session: Session, detail: str | None) -> str:
        """Publish AttentionRequired for a session that needs a human."""
        self._publish(
            AttentionRequired(
                source=SOURCE,
                payload={
                    "kind": "session_awaiting_input",
                    "session_id": str(session.session_id),
                    "task_id": str(session.task_id),
                    "detail": detail,
                },
            )
        )
        return (
            f"Session {session.session_id} is awaiting input"
            f"{f': {detail}' if detail else '.'}"
        )

    def _report_retries_exhausted(self, task: Task, attempts: int) -> None:
        """Publish AttentionRequired for a task out of automatic retries."""
        self._publish(
            AttentionRequired(
                source=SOURCE,
                payload={
                    "kind": "task_retries_exhausted",
                    "task_id": str(task.task_id),
                    "detail": f"{attempts} failed attempt(s); retry or cancel manually.",
                },
            )
        )

    def _publish(self, event: Event) -> None:
        """Append `event` to the persistent log, then emit it on the bus."""
        self._store.append_event(event)
        self._bus.emit(event)

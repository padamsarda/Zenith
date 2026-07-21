"""RetryPolicy: the seam for deciding whether failed work runs again.

Mirrors `AssignmentPolicy`: failure recovery is a judgment that will
keep evolving (attempt budgets, backoff, failure-kind awareness), so it
is isolated behind one small abstract class instead of being buried in
the execution engine. The engine supplies the facts — the failed task
and every session that has failed on it — and the policy only decides.
The human override always exists: `retry_task` returns a task to READY
regardless of what the policy would say.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta

from engineering_manager.domain.session import Session
from engineering_manager.domain.task import Task
from engineering_manager.exceptions import OrchestrationError
from shared.utils.time_utils import utc_now

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BASE_DELAY = timedelta(minutes=1)
DEFAULT_BACKOFF_MULTIPLIER = 2.0


class RetryPolicy(ABC):
    """Decides whether a FAILED task should automatically return to READY."""

    @abstractmethod
    def should_retry(self, task: Task, failed_sessions: Sequence[Session]) -> bool:
        """Return True if `task` should be re-queued for another attempt.

        Args:
            task: The task currently in FAILED.
            failed_sessions: Every session on this task that ended
                FAILED, oldest first — the task's failure history, from
                which attempt counts are derived rather than stored.
        """


class LimitedRetryPolicy(RetryPolicy):
    """Retries until a fixed number of attempts have failed.

    Attempt counting is derived from the durable session history, so it
    survives restarts without any extra state. Once `max_attempts`
    sessions have failed, the task stays FAILED and a human decides
    (`retry_task` to override, `cancel_task` to give up).
    """

    def __init__(self, max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> None:
        """Raise OrchestrationError unless `max_attempts` is a positive int."""
        _validate_max_attempts(max_attempts)
        self._max_attempts = max_attempts

    @property
    def max_attempts(self) -> int:
        """The number of failed attempts after which retrying stops."""
        return self._max_attempts

    def should_retry(self, task: Task, failed_sessions: Sequence[Session]) -> bool:
        """Return True while fewer than `max_attempts` sessions have failed."""
        return len(failed_sessions) < self._max_attempts


class ExponentialBackoffRetryPolicy(RetryPolicy):
    """Retries up to `max_attempts`, waiting longer after each failure.

    Combines `LimitedRetryPolicy`'s attempt budget with failure-aware
    backoff: `should_retry` returns False, not just once attempts are
    exhausted, but also while not enough time has passed since the most
    recent failure. That is not "give up" — `ExecutionEngine.tick` polls
    on an interval (ADR 0008), so the next tick asks again, and the
    answer becomes True once `base_delay * multiplier ** (attempt - 1)`
    has elapsed since that failure's `ended_at` (or `started_at`, for a
    session that failed without ever formally closing). No engine change
    is needed for this — the existing tick loop already re-evaluates
    every FAILED task on every tick, which is exactly what backoff needs.

    `clock` is injectable for this policy's own tests, but note what it
    is *not*: `Dispatcher`/`Session.close()` always stamp `ended_at` with
    the real `utc_now()` — `ExecutionEngine`'s own injectable `clock`
    parameter is not threaded down to them. A scripted `clock` here is
    only meaningful alongside `Session` objects whose `started_at`/
    `ended_at` were constructed to match that same scripted timeline
    (as this module's own tests do); against a live `Dispatcher`, leave
    `clock` at its default so it agrees with real session timestamps.
    """

    def __init__(
        self,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        *,
        base_delay: timedelta = DEFAULT_BASE_DELAY,
        multiplier: float = DEFAULT_BACKOFF_MULTIPLIER,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        """Create the policy.

        Args:
            max_attempts: Total failed sessions allowed before retrying
                stops for good.
            base_delay: Minimum wait after the first failure before a
                retry is offered.
            multiplier: How much longer each successive wait is (delay
                after attempt N is `base_delay * multiplier ** (N - 1)`).
            clock: Source of "now"; injectable so tests never wait on a
                real clock, mirroring `ExecutionEngine`'s own `clock`.

        Raises:
            OrchestrationError: If `max_attempts` is not a positive int,
                `base_delay` is negative, or `multiplier` is less than 1.
        """
        _validate_max_attempts(max_attempts)
        if not isinstance(base_delay, timedelta) or base_delay < timedelta(0):
            raise OrchestrationError(
                f"base_delay must be a non-negative timedelta, got {base_delay!r}"
            )
        if (
            not isinstance(multiplier, (int, float))
            or isinstance(multiplier, bool)
            or multiplier < 1
        ):
            raise OrchestrationError(f"multiplier must be a number >= 1, got {multiplier!r}")
        self._max_attempts = max_attempts
        self._base_delay = base_delay
        self._multiplier = multiplier
        self._clock = clock

    @property
    def max_attempts(self) -> int:
        """The number of failed attempts after which retrying stops."""
        return self._max_attempts

    def should_retry(self, task: Task, failed_sessions: Sequence[Session]) -> bool:
        """Return True once the attempt budget and the backoff delay both allow it."""
        if len(failed_sessions) >= self._max_attempts:
            return False
        if not failed_sessions:
            return True
        most_recent = max(
            failed_sessions, key=lambda session: session.ended_at or session.started_at
        )
        reference = most_recent.ended_at or most_recent.started_at
        delay = self._base_delay * (self._multiplier ** (len(failed_sessions) - 1))
        return self._clock() >= reference + delay


def _validate_max_attempts(max_attempts: object) -> None:
    """Raise OrchestrationError unless `max_attempts` is a positive int."""
    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool):
        raise OrchestrationError(f"max_attempts must be an int, got {max_attempts!r}")
    if max_attempts < 1:
        raise OrchestrationError(f"max_attempts must be at least 1, got {max_attempts}")

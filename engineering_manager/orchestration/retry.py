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
from collections.abc import Sequence

from engineering_manager.domain.session import Session
from engineering_manager.domain.task import Task
from engineering_manager.exceptions import OrchestrationError

DEFAULT_MAX_ATTEMPTS = 3


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
        if not isinstance(max_attempts, int) or isinstance(max_attempts, bool):
            raise OrchestrationError(
                f"max_attempts must be an int, got {max_attempts!r}"
            )
        if max_attempts < 1:
            raise OrchestrationError(
                f"max_attempts must be at least 1, got {max_attempts}"
            )
        self._max_attempts = max_attempts

    @property
    def max_attempts(self) -> int:
        """The number of failed attempts after which retrying stops."""
        return self._max_attempts

    def should_retry(self, task: Task, failed_sessions: Sequence[Session]) -> bool:
        """Return True while fewer than `max_attempts` sessions have failed."""
        return len(failed_sessions) < self._max_attempts

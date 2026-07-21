"""VerificationPolicy: the seam for deciding whether finished work actually works.

A provider reporting `FINISHED` only means the provider *believes* it is
done — nothing has actually checked the claim. Left alone, that is the
single biggest reason nobody could trust the engine to run for hours
unattended: broken work would sit in `NEEDS_REVIEW` indistinguishable
from good work until a human happened to look. `VerificationPolicy`
closes that gap the same way every other judgment in this package does
(`AssignmentPolicy`, `RetryPolicy`): the engine supplies the facts — the
task and its project — and the policy decides whether the claimed
completion holds up. A failed verification is reported through the
engine's ordinary `fail_session` path, so it is not a new outcome kind;
it is folded into the retry loop that already exists for any other
failure.

The default, `NoVerificationPolicy`, always passes — behavior is
unchanged for anyone who does not opt in.
"""

from __future__ import annotations

import logging
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass

from engineering_manager.domain.project import Project
from engineering_manager.domain.task import Task
from engineering_manager.exceptions import OrchestrationError

DEFAULT_LOGGER_NAME = "zenith.em"
DEFAULT_COMMAND: tuple[str, ...] = ("python", "-m", "pytest")
DEFAULT_TIMEOUT_SECONDS = 600.0
DEFAULT_DETAIL_TAIL_CHARS = 4000


@dataclass(frozen=True)
class VerificationResult:
    """What a `VerificationPolicy` decided about one finished session.

    `detail` becomes the session's summary when verification passes, or
    the failure reason when it does not — either way, it is what the
    next attempt (and a human reviewing the plan) sees.
    """

    passed: bool
    detail: str | None = None


class VerificationPolicy(ABC):
    """Decides whether a task's claimed completion should be trusted."""

    @abstractmethod
    def verify(self, task: Task, project: Project) -> VerificationResult:
        """Check `task`'s claimed completion in `project`.

        Implementations must be honest about trouble running the check
        itself (a missing interpreter, a timeout): report it as a failed
        `VerificationResult` rather than raising, so one broken check
        becomes an ordinary recoverable task failure instead of stopping
        the tick.
        """


class NoVerificationPolicy(VerificationPolicy):
    """Trusts every provider-reported completion. The default."""

    def verify(self, task: Task, project: Project) -> VerificationResult:
        """Always pass, with nothing to report."""
        return VerificationResult(passed=True)


class CommandVerificationPolicy(VerificationPolicy):
    """Runs a command in the project's root and trusts its exit code.

    The obvious instance is a test suite (`python -m pytest`, the
    default), but any command that exits zero on success works —
    a linter, a build, a focused test subset. The command runs
    synchronously inside the tick with a bounded `timeout_seconds`, so
    pick something fast enough not to stall the engine's other work;
    a slow full suite belongs in the provider's own session instead of
    here.
    """

    def __init__(
        self,
        command: tuple[str, ...] = DEFAULT_COMMAND,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        detail_tail_chars: int = DEFAULT_DETAIL_TAIL_CHARS,
        logger: logging.Logger | None = None,
    ) -> None:
        """Create the policy.

        Raises:
            OrchestrationError: If `command` is empty, `timeout_seconds`
                is not positive, or `detail_tail_chars` is negative.
        """
        if not command:
            raise OrchestrationError("CommandVerificationPolicy requires a non-empty command.")
        if timeout_seconds <= 0:
            raise OrchestrationError(
                f"timeout_seconds must be positive, got {timeout_seconds!r}"
            )
        if detail_tail_chars < 0:
            raise OrchestrationError(
                f"detail_tail_chars must not be negative, got {detail_tail_chars!r}"
            )
        self._command = command
        self._timeout_seconds = timeout_seconds
        self._detail_tail_chars = detail_tail_chars
        self._logger = logger or logging.getLogger(DEFAULT_LOGGER_NAME)

    def verify(self, task: Task, project: Project) -> VerificationResult:
        """Run the configured command in `project.root_path`.

        A missing project directory, an unlaunchable command, or a
        command that exceeds `timeout_seconds` all count as a failed
        verification rather than raising — the retry loop is where that
        belongs, not an engine crash.
        """
        if not project.root_path.is_dir():
            return VerificationResult(
                passed=False,
                detail=f"Verification skipped: {project.root_path} does not exist.",
            )
        try:
            completed = subprocess.run(
                list(self._command),
                cwd=project.root_path,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                encoding="utf-8",
                errors="ignore",
            )
        except subprocess.TimeoutExpired:
            self._logger.warning(
                "Verification for task %s timed out after %ss.", task.task_id, self._timeout_seconds
            )
            return VerificationResult(
                passed=False,
                detail=f"Verification command timed out after {self._timeout_seconds}s.",
            )
        except OSError as exc:
            self._logger.warning("Verification for task %s could not run: %s", task.task_id, exc)
            return VerificationResult(passed=False, detail=f"Verification could not run: {exc}")

        output = self._tail(completed.stdout, completed.stderr)
        if completed.returncode == 0:
            return VerificationResult(passed=True, detail=output or None)
        return VerificationResult(
            passed=False,
            detail=f"Verification failed (exit {completed.returncode}):\n{output}",
        )

    def _tail(self, stdout: str, stderr: str) -> str:
        """Combine and truncate captured output to the last `detail_tail_chars`."""
        combined = "\n".join(part for part in (stdout, stderr) if part)
        if len(combined) <= self._detail_tail_chars:
            return combined
        return combined[-self._detail_tail_chars :]

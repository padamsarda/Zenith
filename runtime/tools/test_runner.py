"""TestRunnerTool: runs the project's test suite and reports the outcome."""

from __future__ import annotations

import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from runtime.capabilities.tool import Tool, ToolParameter
from runtime.tools.arguments import optional_float, optional_sequence_str, optional_str
from runtime.tools.process import run_process
from runtime.tools.sandbox import resolve_within_root

if TYPE_CHECKING:
    from runtime.commands.context import CommandContext

DEFAULT_LOGGER_NAME = "zenith.tools.test_runner"
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_COMMAND: tuple[str, ...] = (sys.executable, "-m", "pytest")

# Pytest's own summary line looks like "===== 2 failed, 3 passed in 0.12s =====";
# this is a best-effort read of it, not a guaranteed contract (ADR 0016) — pytest's
# text output format is not something this tool controls.
SUMMARY_PATTERN = re.compile(r"(\d+)\s+(passed|failed|error|errors|skipped)")
SUMMARY_KEYS = ("passed", "failed", "errors", "skipped")


@dataclass(frozen=True)
class TestRunResult:
    """The structured outcome of one test run.

    `passed`/`failed`/`errors`/`skipped` are best-effort counts parsed
    from the runner's summary line; all four are `None` together when
    the line could not be recognized (e.g. a runner other than pytest,
    or a crash before any summary was printed). `exit_code`/`stdout`/
    `stderr` are always populated and are the authoritative outcome.
    """

    command: tuple[str, ...]
    exit_code: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    passed: int | None = None
    failed: int | None = None
    errors: int | None = None
    skipped: int | None = None
    timed_out: bool = False

    @property
    def success(self) -> bool:
        """Whether the run exited zero without timing out."""
        return self.exit_code == 0 and not self.timed_out

    def __str__(self) -> str:
        header = f"$ {' '.join(self.command)}  (exit={self.exit_code})"
        if self.passed is not None:
            header += (
                f" - passed={self.passed} failed={self.failed} "
                f"errors={self.errors} skipped={self.skipped}"
            )
        lines = [header]
        if self.stdout.strip():
            lines.append(self.stdout.rstrip())
        if self.stderr.strip():
            lines.append("--- stderr ---")
            lines.append(self.stderr.rstrip())
        if self.timed_out:
            lines.append("(timed out and was killed)")
        return "\n".join(lines)


class TestRunnerTool(Tool):
    """Runs the project's test suite within a sandboxed root.

    Defaults to `[sys.executable, "-m", "pytest"]` — this repository's
    own test runner (`docs/conventions.md`) — but the base command is
    configurable at construction for a different runner or interpreter.
    `path` (a test file or node id, e.g. `tests/test_foo.py::test_bar`)
    and `args` (extra runner flags) are appended as their own argv
    entries, never interpolated into a shell string, so there is nothing
    here for `ShellTool`'s "trusted verbatim" caveat to apply to.
    """

    __test__ = False  # Not a pytest test class; only named like one.

    def __init__(
        self,
        root: Path,
        *,
        command: tuple[str, ...] = DEFAULT_COMMAND,
        default_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        logger: logging.Logger | None = None,
    ) -> None:
        """Create a TestRunnerTool sandboxed to `root`.

        Args:
            root: The working directory the test command runs in, and
                the sandbox `path` is resolved against.
            command: The base command, before `path` and `args` are
                appended. Defaults to `python -m pytest`.
            default_timeout_seconds: Timeout used when a call does not
                supply its own `timeout_seconds`.
            logger: Defaults to a module logger.
        """
        self._root = root.resolve()
        self._command = command
        self._default_timeout_seconds = default_timeout_seconds
        self._logger = logger or logging.getLogger(DEFAULT_LOGGER_NAME)

    @property
    def tool_id(self) -> str:
        return "test_runner"

    @property
    def name(self) -> str:
        return "Test Runner"

    @property
    def description(self) -> str:
        return (
            "Runs the project's test suite within the sandboxed project root and "
            "reports the exit code, captured output, and best-effort pass/fail counts."
        )

    @property
    def parameters(self) -> tuple[ToolParameter, ...]:
        return (
            ToolParameter(
                name="path",
                description=(
                    "A specific test path or node id (e.g. 'tests/test_foo.py::test_bar'), "
                    "relative to the root. Omit to run the whole suite."
                ),
                required=False,
            ),
            ToolParameter(
                name="args",
                description="Extra arguments passed through to the test command (e.g. ['-k', 'foo']).",
                required=False,
                type="array",
            ),
            ToolParameter(
                name="timeout_seconds",
                description="Overrides the tool's default timeout.",
                required=False,
                type="number",
            ),
        )

    def invoke(self, context: CommandContext, arguments: dict[str, Any]) -> TestRunResult:
        """Run the test suite (or a subset of it) and return its structured result.

        Raises:
            ToolExecutionError: If `path` escapes the sandbox root or the
                test command could not be started.
            CommandCancelledError: If the command's cancellation token is
                already set.
        """
        path = optional_str(arguments, "path")
        extra_args = optional_sequence_str(arguments, "args")
        timeout_seconds = optional_float(
            arguments, "timeout_seconds", default=self._default_timeout_seconds
        )

        if path is not None:
            resolve_within_root(self._root, path)

        argv = [*self._command, *([path] if path is not None else []), *extra_args]
        self._logger.info("Running tests: %s", " ".join(argv))
        outcome = run_process(
            argv,
            cwd=self._root,
            env=os.environ,
            timeout_seconds=timeout_seconds,
            cancellation_token=context.cancellation_token,
        )
        counts = self._parse_summary(outcome.stdout)
        return TestRunResult(
            command=tuple(argv),
            exit_code=outcome.exit_code,
            stdout=outcome.stdout,
            stderr=outcome.stderr,
            duration_seconds=outcome.duration_seconds,
            timed_out=outcome.timed_out,
            passed=counts["passed"] if counts else None,
            failed=counts["failed"] if counts else None,
            errors=counts["errors"] if counts else None,
            skipped=counts["skipped"] if counts else None,
        )

    def _parse_summary(self, stdout: str) -> dict[str, int] | None:
        """Best-effort parse of pytest's final summary line, or `None`."""
        lines = [line for line in stdout.splitlines() if line.strip()]
        if not lines:
            return None
        matches = SUMMARY_PATTERN.findall(lines[-1])
        if not matches:
            return None
        counts = dict.fromkeys(SUMMARY_KEYS, 0)
        for count, label in matches:
            key = "errors" if label == "error" else label
            counts[key] += int(count)
        return counts

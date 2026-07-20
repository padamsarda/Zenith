"""ShellTool: sandboxed shell command execution."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from runtime.capabilities.tool import Tool, ToolParameter
from runtime.tools.arguments import optional_float, optional_mapping, optional_str, require_str
from runtime.tools.process import run_process
from runtime.tools.sandbox import resolve_within_root

if TYPE_CHECKING:
    from runtime.commands.context import CommandContext

DEFAULT_LOGGER_NAME = "zenith.tools.shell"
DEFAULT_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class ShellResult:
    """The structured outcome of one shell command."""

    command: str
    cwd: str
    exit_code: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False

    @property
    def success(self) -> bool:
        """Whether the command exited zero without timing out."""
        return self.exit_code == 0 and not self.timed_out

    def __str__(self) -> str:
        lines = [f"$ {self.command}  (cwd={self.cwd}, exit={self.exit_code})"]
        if self.stdout.strip():
            lines.append("--- stdout ---")
            lines.append(self.stdout.rstrip())
        if self.stderr.strip():
            lines.append("--- stderr ---")
            lines.append(self.stderr.rstrip())
        if self.timed_out:
            lines.append("(timed out and was killed)")
        return "\n".join(lines)


class ShellTool(Tool):
    """Runs one shell command inside a sandboxed working directory.

    The command line itself is trusted verbatim — like a real terminal,
    this tool does not attempt to sanitize or interpret it. Whether it
    may run at all for a given call is the `PermissionPolicy`'s decision,
    made before `invoke` is ever reached (ADR 0016). What this tool does
    enforce is *where* it runs: `cwd` is resolved through
    `resolve_within_root` against the configured `root`, so a command
    cannot be pointed at a working directory outside the sandbox.
    """

    def __init__(
        self,
        root: Path,
        *,
        default_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        logger: logging.Logger | None = None,
    ) -> None:
        """Create a ShellTool sandboxed to `root`.

        Args:
            root: The default, and outer bound, working directory.
            default_timeout_seconds: Timeout used when a call does not
                supply its own `timeout_seconds`.
            logger: Defaults to a module logger.
        """
        self._root = root.resolve()
        self._default_timeout_seconds = default_timeout_seconds
        self._logger = logger or logging.getLogger(DEFAULT_LOGGER_NAME)

    @property
    def tool_id(self) -> str:
        return "shell"

    @property
    def name(self) -> str:
        return "Shell"

    @property
    def description(self) -> str:
        return (
            "Runs a shell command inside a sandboxed working directory and reports "
            "its exit code, stdout, and stderr."
        )

    @property
    def parameters(self) -> tuple[ToolParameter, ...]:
        return (
            ToolParameter(
                name="command", description="The shell command line to execute.", required=True
            ),
            ToolParameter(
                name="cwd",
                description=(
                    "Working directory, relative to the sandbox root. Defaults to the root."
                ),
                required=False,
            ),
            ToolParameter(
                name="env",
                description="Extra environment variables, merged over the inherited environment.",
                required=False,
                type="object",
            ),
            ToolParameter(
                name="timeout_seconds",
                description="Overrides the tool's default timeout.",
                required=False,
                type="number",
            ),
        )

    def invoke(self, context: CommandContext, arguments: dict[str, Any]) -> ShellResult:
        """Run the requested command and return its structured result.

        Raises:
            ToolExecutionError: If `cwd` escapes the sandbox root or the
                process could not be started.
            CommandCancelledError: If the command's cancellation token is
                already set.
        """
        command = require_str(arguments, "command")
        cwd = resolve_within_root(self._root, optional_str(arguments, "cwd"))
        env = {**os.environ, **optional_mapping(arguments, "env")}
        timeout_seconds = optional_float(
            arguments, "timeout_seconds", default=self._default_timeout_seconds
        )

        self._logger.info("Running shell command %r in %s", command, cwd)
        outcome = run_process(
            command,
            cwd=cwd,
            env=env,
            timeout_seconds=timeout_seconds,
            cancellation_token=context.cancellation_token,
            shell=True,
        )
        return ShellResult(
            command=command,
            cwd=str(cwd.relative_to(self._root)) if cwd != self._root else ".",
            exit_code=outcome.exit_code,
            stdout=outcome.stdout,
            stderr=outcome.stderr,
            duration_seconds=outcome.duration_seconds,
            timed_out=outcome.timed_out,
        )

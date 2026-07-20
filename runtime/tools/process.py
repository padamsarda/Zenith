"""run_process: the shared subprocess harness for Shell, Git, and Test Runner.

Wraps `subprocess.Popen` with the two concerns every tool that shells
out needs identically: a wall-clock timeout, and cooperative
cancellation through `CommandContext.cancellation_token` — the same
reserved seam `runtime.commands.context.CancellationToken` describes for
every command action (`docs/commands.md`). Nothing else about running a
subprocess is tool-specific, so it lives here once rather than once per
tool.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from runtime.commands.context import CancellationToken
from runtime.exceptions import CommandCancelledError, ToolExecutionError

DEFAULT_POLL_INTERVAL_SECONDS = 0.05
_IS_WINDOWS = sys.platform == "win32"


@dataclass(frozen=True)
class ProcessOutcome:
    """What running a subprocess to completion (or timeout) produced."""

    exit_code: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False


def _process_group_kwargs() -> dict[str, object]:
    """Popen kwargs that isolate the child into its own process group/session.

    Required so `_terminate_tree` can kill an entire shell-spawned tree
    (e.g. `cmd.exe` -> the program it launched) without also killing
    ourselves: on POSIX, a new session makes the child's pgid equal to
    its own pid, safe to target with `killpg`; on Windows, a new process
    group is what lets `taskkill /T` walk the tree from that root.
    """
    if _IS_WINDOWS:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _terminate_tree(process: subprocess.Popen[str]) -> None:
    """Kill `process` and any descendants it spawned.

    A plain `Popen.kill()` only signals the directly tracked process. If
    it was launched with `shell=True`, that process is the shell, and
    the program the shell ran can survive as an orphan holding the
    stdout/stderr pipes open — the very thing a timeout or cancellation
    is meant to stop. Combined with `_process_group_kwargs`, this reaches
    the whole tree instead.
    """
    if _IS_WINDOWS:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.kill()
    except OSError:
        pass


def run_process(
    args: Sequence[str] | str,
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout_seconds: float | None,
    cancellation_token: CancellationToken,
    shell: bool = False,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
) -> ProcessOutcome:
    """Run `args` to completion, enforcing a timeout and cancellation.

    Polls with short `Popen.communicate(timeout=...)` calls — safe to
    retry after `TimeoutExpired`, per the standard library's own
    documented pattern — so a cancelled token is noticed promptly rather
    than only after the whole timeout window elapses. The child runs in
    its own process group/session (`_process_group_kwargs`) so that on
    timeout or cancellation `_terminate_tree` can kill the whole tree —
    including a program a shell command (`shell=True`) launched — rather
    than leaving it running as an orphan that keeps the stdout/stderr
    pipes open.

    Args:
        args: The command to run — an argv sequence when `shell=False`,
            or a full command line string when `shell=True`.
        cwd: Working directory for the child process.
        env: The complete environment to run with.
        timeout_seconds: Wall-clock limit. `None` means no limit.
        cancellation_token: Checked before starting and between polls; if
            `cancelled` is ever true, the process is killed and
            `CommandCancelledError` is raised.
        shell: Whether to run `args` through the platform shell.
        poll_interval_seconds: How often to check for cancellation while
            waiting for the process to exit.

    Returns:
        A `ProcessOutcome`. `timed_out=True` means `timeout_seconds`
        elapsed before the process exited on its own (it is killed
        either way, and `stdout`/`stderr` hold whatever it had already
        produced).

    Raises:
        ToolExecutionError: If the process could not be started.
        CommandCancelledError: If `cancellation_token.cancelled` is, or
            becomes, true.
    """
    command_label = args if isinstance(args, str) else " ".join(args)
    if cancellation_token.cancelled:
        raise CommandCancelledError(f"Process cancelled before it started: {command_label!r}")

    start = perf_counter()
    try:
        process = subprocess.Popen(
            args,
            cwd=str(cwd),
            env=dict(env),
            shell=shell,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **_process_group_kwargs(),
        )
    except OSError as exc:
        raise ToolExecutionError(f"Failed to start process {command_label!r}: {exc}") from exc

    while True:
        try:
            stdout, stderr = process.communicate(timeout=poll_interval_seconds)
        except subprocess.TimeoutExpired:
            if cancellation_token.cancelled:
                _terminate_tree(process)
                process.communicate()
                raise CommandCancelledError(f"Process cancelled: {command_label!r}") from None
            elapsed = perf_counter() - start
            if timeout_seconds is not None and elapsed >= timeout_seconds:
                _terminate_tree(process)
                stdout, stderr = process.communicate()
                return ProcessOutcome(
                    exit_code=process.returncode,
                    stdout=stdout,
                    stderr=stderr,
                    duration_seconds=perf_counter() - start,
                    timed_out=True,
                )
            continue
        else:
            return ProcessOutcome(
                exit_code=process.returncode,
                stdout=stdout,
                stderr=stderr,
                duration_seconds=perf_counter() - start,
            )

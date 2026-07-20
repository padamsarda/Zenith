"""Subprocess plumbing for the Claude Code CLI provider.

Split out from `claude_code.py` so process mechanics (launching a
subprocess, draining its output without deadlocking, resolving
per-account credentials) stay a separate responsibility from the
`Provider` contract implementation itself.
"""

from __future__ import annotations

import os
import subprocess
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Protocol

DEFAULT_COMMAND: tuple[str, ...] = ("claude",)

# An account "personal" resolves its credential from
# ZENITH_CLAUDE_PERSONAL_API_KEY (the account ID upper-cased, with any
# non-alphanumeric character replaced by "_"). This is deliberately an
# environment-variable convention rather than anything stored by the
# Engineering Manager: ADR 0005 forbids the Engineering Manager from
# holding credentials, so each provider resolves its own from the account
# ID, exactly as this does.
ACCOUNT_API_KEY_TEMPLATE = "ZENITH_CLAUDE_{account}_API_KEY"


class ProcessLike(Protocol):
    """The subset of `subprocess.Popen` the provider depends on.

    Named as a Protocol so tests can supply a fake process without
    spawning a real one or importing `subprocess`.
    """

    stdout: object

    def poll(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


Launcher = Callable[[Sequence[str], dict[str, str], Path], ProcessLike]


def default_launcher(command: Sequence[str], env: dict[str, str], cwd: Path) -> subprocess.Popen:
    """Launch `command` in `cwd` with `env`, combining stdout and stderr.

    Text mode, UTF-8, decoding errors ignored rather than raised — matches
    `engineering_tools.watchdog.watchdog.run_and_stream`, whose output
    handling this generalizes.

    Raises:
        FileNotFoundError: If the executable cannot be found.
    """
    return subprocess.Popen(
        list(command),
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="ignore",
    )


def account_env(
    account_id: str, environ: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Return the subprocess environment to use for `account_id`.

    Copies `environ` (the real process environment by default) and, if a
    per-account API key variable is set, overrides `ANTHROPIC_API_KEY`
    with it. Without one, the environment — and therefore however
    `claude` is already authenticated on this machine — passes through
    unchanged, so a single-account setup needs no configuration at all.
    """
    env = dict(environ if environ is not None else os.environ)
    variable = ACCOUNT_API_KEY_TEMPLATE.format(account=_normalize(account_id))
    api_key = env.get(variable)
    if api_key:
        env["ANTHROPIC_API_KEY"] = api_key
    return env


def _normalize(account_id: str) -> str:
    """Turn an account ID into an environment-variable-safe fragment."""
    return "".join(char if char.isalnum() else "_" for char in account_id).upper()


class OutputDrain:
    """Continuously reads a process stream on a background thread.

    A subprocess's stdout pipe has a small OS-level buffer; if nothing
    reads it while the child keeps writing, the child blocks on its own
    output. `Provider.check_session` only polls occasionally, so the pipe
    must be drained continuously between polls rather than read on
    demand — the same problem `engineering_tools/watchdog` solves with
    its own read loop, generalized here into a reusable helper.
    """

    def __init__(self, stream) -> None:
        self._lines: list[str] = []
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._drain, args=(stream,), daemon=True)
        self._thread.start()

    def _drain(self, stream) -> None:
        try:
            for line in stream:
                with self._lock:
                    self._lines.append(line)
        except (ValueError, OSError):
            # The stream was closed out from under us (process killed);
            # whatever was captured before that stands.
            pass

    def text(self) -> str:
        """Return everything captured so far, joined into one string."""
        with self._lock:
            return "".join(self._lines)

    def join(self, timeout: float = 2.0) -> None:
        """Wait briefly for the drain thread to notice EOF."""
        self._thread.join(timeout)

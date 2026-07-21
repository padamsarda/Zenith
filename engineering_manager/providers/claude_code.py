"""ClaudeCodeProvider: drives the `claude` CLI as a Provider integration.

The Engineering Manager's first real provider (ADR 0014), generalizing
`engineering_tools/watchdog`: each session is one non-interactive
`claude --print` subprocess started in the task's project directory.
`check_session` polls the process rather than blocking on it; a clean
exit is parsed as the CLI's own `--output-format json` result, a nonzero
exit is scanned for the same session-limit line the watchdog detects
(reusing its proven `parse_reset_time`), and `resume_session` starts a
fresh `claude --continue` process — the same recovery the watchdog
performs by hand, now expressed through the `Provider` contract so the
`ExecutionEngine` drives it automatically.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from subprocess import TimeoutExpired
from uuid import uuid4

from engineering_manager.exceptions import ProviderSessionError
from engineering_manager.providers.base import (
    Provider,
    ProviderSessionState,
    ProviderSessionStatus,
    SessionHandle,
    SessionSpec,
)
from engineering_manager.providers.claude_code_output import interpret_exit
from engineering_manager.providers.claude_code_process import (
    DEFAULT_COMMAND,
    Launcher,
    OutputDrain,
    ProcessLike,
    account_env,
    default_launcher,
)

DEFAULT_LOGGER_NAME = "zenith.em.claude_code"
DEFAULT_PROVIDER_ID = "claude-code"
DEFAULT_RESUME_PROMPT = "Continue the previous task."
TERMINATE_TIMEOUT_SECONDS = 5.0

# Claude Code's own permission modes. `default` prompts for approval,
# which a `--print` session with no stdin can never receive — every tool
# call is denied and the session accomplishes nothing. Granting
# authority is therefore a deliberate argument, not a default: ADR 0022
# explains why the safe default stays safe and merely became honest.
PERMISSION_MODES = ("default", "acceptEdits", "bypassPermissions", "plan")
DEFAULT_PERMISSION_MODE = "default"


@dataclass
class _RunningSession:
    """Everything tracked about one live or just-finished subprocess.

    In-memory only: an Engineering Manager restart loses this bookkeeping
    for any session still running. That session's next `check_session`
    then raises `ProviderSessionError` (unknown handle), which the
    execution engine already treats as "the work is gone" and recovers
    from through the retry policy (ADR 0008) — the same category of
    deferral `ConversationStore` accepts for the Zenith runtime.
    """

    process: ProcessLike
    drain: OutputDrain
    root_path: Path
    account_id: str
    model: str | None
    resume_prompt: str
    permission_mode: str


class ClaudeCodeProvider(Provider):
    """Runs Claude Code non-interactively, one subprocess per session."""

    def __init__(
        self,
        *,
        command: tuple[str, ...] = DEFAULT_COMMAND,
        provider_id: str = DEFAULT_PROVIDER_ID,
        launcher: Launcher = default_launcher,
        resume_prompt: str = DEFAULT_RESUME_PROMPT,
        permission_mode: str = DEFAULT_PERMISSION_MODE,
        logger: logging.Logger | None = None,
    ) -> None:
        self._command = command
        self._provider_id = provider_id
        self._launcher = launcher
        self._resume_prompt = resume_prompt
        self._permission_mode = permission_mode
        self._logger = logger or logging.getLogger(DEFAULT_LOGGER_NAME)
        self._sessions: dict[str, _RunningSession] = {}

    @property
    def provider_id(self) -> str:
        """Stable identifier for this provider."""
        return self._provider_id

    @property
    def name(self) -> str:
        """Human-readable display name."""
        return "Claude Code"

    def start_session(self, spec: SessionSpec) -> SessionHandle:
        """Launch `claude --print` for `spec` in the project's directory.

        There is no session-length timeout: Claude Code sessions may
        legitimately run for hours, and the `ExecutionEngine`'s poll
        interval — not this provider — governs how promptly completion
        is noticed.

        Raises:
            ProviderSessionError: If the project path does not exist, no
                instructions were supplied, or the `claude` executable
                could not be launched.
        """
        instructions = spec.instructions
        if not instructions or not instructions.strip():
            raise ProviderSessionError(
                f"Session {spec.session_id} has no instructions to run."
            )
        root_path = spec.project.root_path
        if not root_path.is_dir():
            raise ProviderSessionError(
                f"Project '{spec.project.project_id}' path does not exist: {root_path}"
            )

        permission_mode = str(
            spec.metadata.get("permission_mode", self._permission_mode)
        )
        args = [*self._command, "--print", instructions, "--output-format", "json"]
        args.extend(["--permission-mode", permission_mode])
        if spec.model:
            args.extend(["--model", spec.model])
        args.extend(str(arg) for arg in spec.metadata.get("args", []))

        process = self._launch(args, spec.account_id, root_path)
        external_ref = f"{self._provider_id}/{uuid4()}"
        self._sessions[external_ref] = _RunningSession(
            process=process,
            drain=OutputDrain(process.stdout),
            root_path=root_path,
            account_id=spec.account_id,
            model=spec.model,
            resume_prompt=str(spec.metadata.get("resume_prompt", self._resume_prompt)),
            permission_mode=permission_mode,
        )
        self._logger.info("Started Claude Code session %s in %s.", external_ref, root_path)
        return SessionHandle(provider_id=self._provider_id, external_ref=external_ref)

    def check_session(self, handle: SessionHandle) -> ProviderSessionStatus:
        """Report whether the subprocess behind `handle` has finished.

        Raises:
            ProviderSessionError: If `handle` is unknown to this provider.
        """
        running = self._get(handle)
        exit_code = running.process.poll()
        if exit_code is None:
            return ProviderSessionStatus(state=ProviderSessionState.RUNNING)

        status = interpret_exit(running.drain.text(), exit_code)
        self._logger.info(
            "Session %s finished (%s).", handle.external_ref, status.state.name
        )
        return status

    def resume_session(self, handle: SessionHandle) -> SessionHandle:
        """Start a fresh `claude --continue` process in the same directory.

        Raises:
            ProviderSessionError: If `handle` is unknown, or the
                executable could not be launched.
        """
        running = self._get(handle)
        args = [
            *self._command,
            "--continue",
            "--print",
            running.resume_prompt,
            "--output-format",
            "json",
            "--permission-mode",
            running.permission_mode,
        ]
        if running.model:
            args.extend(["--model", running.model])

        process = self._launch(args, running.account_id, running.root_path)
        del self._sessions[handle.external_ref]
        new_ref = f"{self._provider_id}/{uuid4()}"
        self._sessions[new_ref] = _RunningSession(
            process=process,
            drain=OutputDrain(process.stdout),
            root_path=running.root_path,
            account_id=running.account_id,
            model=running.model,
            resume_prompt=running.resume_prompt,
            permission_mode=running.permission_mode,
        )
        self._logger.info("Resumed Claude Code session %s as %s.", handle.external_ref, new_ref)
        return SessionHandle(provider_id=self._provider_id, external_ref=new_ref)

    def stop_session(self, handle: SessionHandle) -> None:
        """Terminate the subprocess behind `handle`.

        Raises:
            ProviderSessionError: If `handle` is unknown to this provider.
        """
        running = self._sessions.pop(handle.external_ref, None)
        if running is None:
            raise ProviderSessionError(
                f"Provider '{self._provider_id}' has no session {handle.external_ref!r}."
            )
        self._terminate(running.process)
        self._logger.info("Stopped Claude Code session %s.", handle.external_ref)

    # -- internals -----------------------------------------------------

    def _launch(self, args: list[str], account_id: str, root_path: Path) -> ProcessLike:
        """Launch `args` for `account_id` in `root_path`.

        Raises:
            ProviderSessionError: If the executable could not be found.
        """
        try:
            return self._launcher(args, account_env(account_id), root_path)
        except FileNotFoundError as exc:
            raise ProviderSessionError(
                f"Could not launch '{self._command[0]}': {exc}"
            ) from exc

    def _get(self, handle: SessionHandle) -> _RunningSession:
        """Look up the tracked session behind `handle`.

        Raises:
            ProviderSessionError: If `handle` is unknown to this provider.
        """
        try:
            return self._sessions[handle.external_ref]
        except KeyError:
            raise ProviderSessionError(
                f"Provider '{self._provider_id}' has no session {handle.external_ref!r}."
            ) from None

    def _terminate(self, process: ProcessLike) -> None:
        """Best-effort graceful-then-forceful shutdown of `process`."""
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=TERMINATE_TIMEOUT_SECONDS)
        except TimeoutExpired:
            process.kill()

"""Tests for ClaudeCodeProvider."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from subprocess import TimeoutExpired
from typing import Any

import pytest

from engineering_manager.domain.project import Project
from engineering_manager.domain.task import Task
from engineering_manager.exceptions import ProviderSessionError
from engineering_manager.providers.base import (
    ProviderSessionState,
    SessionHandle,
    SessionSpec,
)
from engineering_manager.providers.claude_code import ClaudeCodeProvider
from shared.utils.uuid_utils import generate_id


class FakeProcess:
    """A ProcessLike double with a scriptable exit code and output."""

    def __init__(self, lines: list[str], returncode: int = 0) -> None:
        self.stdout = iter(lines)
        self.returncode = returncode
        self._running = True
        self.terminated = False
        self.killed = False

    def finish(self) -> None:
        """Simulate the process exiting with its configured `returncode`."""
        self._running = False

    def poll(self) -> int | None:
        return None if self._running else self.returncode

    def wait(self, timeout: float | None = None) -> int:
        self._running = False
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self._running = False

    def kill(self) -> None:
        self.killed = True
        self._running = False


class StubbornProcess(FakeProcess):
    """A process that ignores `terminate()` until `kill()` is called."""

    def wait(self, timeout: float | None = None) -> int:
        raise TimeoutExpired(cmd="claude", timeout=timeout)


class FakeLauncher:
    """A Launcher double recording every command it is asked to run."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, str], Path]] = []
        self._queue: list[FakeProcess] = []

    def queue(self, process: FakeProcess) -> None:
        self._queue.append(process)

    def __call__(self, args: list[str], env: dict[str, str], cwd: Path) -> FakeProcess:
        self.calls.append((list(args), dict(env), cwd))
        return self._queue.pop(0)


def make_spec(
    tmp_path: Path,
    *,
    instructions: str | None = "Write docs",
    model: str | None = None,
    account_id: str = "personal",
    metadata: dict[str, Any] | None = None,
    root_path: Path | None = None,
) -> SessionSpec:
    project = Project(project_id="zenith", name="Zenith", root_path=root_path or tmp_path)
    task = Task(project_id="zenith", title="Write docs")
    return SessionSpec(
        session_id=generate_id(),
        project=project,
        task=task,
        account_id=account_id,
        model=model,
        instructions=instructions,
        metadata=metadata or {},
    )


def _settle(provider: ClaudeCodeProvider, handle: SessionHandle) -> None:
    """Wait for a fake process's background output drain to finish.

    Whitebox: reaches into the provider's own bookkeeping so assertions
    made right after `finish()` see everything the drain thread captured,
    the way they would after a real (slower) subprocess actually exited.
    """
    provider._sessions[handle.external_ref].drain.join()


def test_start_session_launches_print_mode_with_instructions_and_model(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    launcher.queue(FakeProcess([]))
    provider = ClaudeCodeProvider(launcher=launcher)

    handle = provider.start_session(make_spec(tmp_path, model="claude-sonnet-5"))

    assert handle.provider_id == "claude-code"
    args, _env, cwd = launcher.calls[0]
    assert args[:2] == ["claude", "--print"]
    assert "Write docs" in args[2]
    assert "--output-format" in args and "json" in args
    assert args[args.index("--model") + 1] == "claude-sonnet-5"
    assert cwd == tmp_path


def test_start_session_without_instructions_raises(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    provider = ClaudeCodeProvider(launcher=launcher)

    with pytest.raises(ProviderSessionError):
        provider.start_session(make_spec(tmp_path, instructions="   "))
    assert launcher.calls == []


def test_start_session_missing_project_path_raises(tmp_path: Path) -> None:
    provider = ClaudeCodeProvider(launcher=FakeLauncher())

    with pytest.raises(ProviderSessionError):
        provider.start_session(make_spec(tmp_path, root_path=tmp_path / "missing"))


def test_start_session_missing_executable_raises(tmp_path: Path) -> None:
    def exploding_launcher(args: list[str], env: dict[str, str], cwd: Path) -> FakeProcess:
        raise FileNotFoundError("no such file")

    provider = ClaudeCodeProvider(launcher=exploding_launcher)

    with pytest.raises(ProviderSessionError):
        provider.start_session(make_spec(tmp_path))


def test_start_session_with_real_nonexistent_executable_raises(tmp_path: Path) -> None:
    provider = ClaudeCodeProvider(command=("non_existent_executable_12345",))

    with pytest.raises(ProviderSessionError):
        provider.start_session(make_spec(tmp_path))


def test_check_session_reports_running_while_process_is_alive(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    launcher.queue(FakeProcess([]))
    provider = ClaudeCodeProvider(launcher=launcher)
    handle = provider.start_session(make_spec(tmp_path))

    assert provider.check_session(handle).state is ProviderSessionState.RUNNING


def test_check_session_parses_json_result_as_finished(tmp_path: Path) -> None:
    payload = (
        '{"is_error": false, "result": "Docs written.", '
        '"usage": {"input_tokens": 10, "output_tokens": 20}, "total_cost_usd": 0.01}'
    )
    launcher = FakeLauncher()
    process = FakeProcess([payload], returncode=0)
    launcher.queue(process)
    provider = ClaudeCodeProvider(launcher=launcher)
    handle = provider.start_session(make_spec(tmp_path))
    process.finish()
    _settle(provider, handle)

    status = provider.check_session(handle)

    assert status.state is ProviderSessionState.FINISHED
    assert status.detail == "Docs written."
    assert status.usage["input_tokens"] == 10
    assert status.usage["total_cost_usd"] == 0.01


def test_check_session_json_is_error_reports_failed(tmp_path: Path) -> None:
    payload = '{"is_error": true, "result": "could not comply"}'
    launcher = FakeLauncher()
    process = FakeProcess([payload], returncode=0)
    launcher.queue(process)
    provider = ClaudeCodeProvider(launcher=launcher)
    handle = provider.start_session(make_spec(tmp_path))
    process.finish()
    _settle(provider, handle)

    status = provider.check_session(handle)

    assert status.state is ProviderSessionState.FAILED
    assert status.detail == "could not comply"


def test_check_session_non_json_output_finishes_with_raw_text(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    process = FakeProcess(["Plain text output\n"], returncode=0)
    launcher.queue(process)
    provider = ClaudeCodeProvider(launcher=launcher)
    handle = provider.start_session(make_spec(tmp_path))
    process.finish()
    _settle(provider, handle)

    status = provider.check_session(handle)

    assert status.state is ProviderSessionState.FINISHED
    assert status.detail == "Plain text output"


def test_check_session_detects_limit_line_with_resume_at(tmp_path: Path) -> None:
    line = "You've hit your session limit · resets 1:40am (Asia/Calcutta)\n"
    launcher = FakeLauncher()
    process = FakeProcess([line], returncode=1)
    launcher.queue(process)
    provider = ClaudeCodeProvider(launcher=launcher)
    handle = provider.start_session(make_spec(tmp_path))
    process.finish()
    _settle(provider, handle)

    status = provider.check_session(handle)

    assert status.state is ProviderSessionState.LIMIT_REACHED
    assert status.resume_at is not None
    assert "session limit" in status.detail


def test_check_session_generic_failure_reports_last_output_line(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    process = FakeProcess(["some error\n", "traceback line\n"], returncode=1)
    launcher.queue(process)
    provider = ClaudeCodeProvider(launcher=launcher)
    handle = provider.start_session(make_spec(tmp_path))
    process.finish()
    _settle(provider, handle)

    status = provider.check_session(handle)

    assert status.state is ProviderSessionState.FAILED
    assert status.detail == "traceback line"


@pytest.mark.parametrize("method", ["check_session", "resume_session", "stop_session"])
def test_unknown_handle_raises(method: str) -> None:
    provider = ClaudeCodeProvider(launcher=FakeLauncher())
    unknown = SessionHandle(provider_id="claude-code", external_ref="missing")

    with pytest.raises(ProviderSessionError):
        getattr(provider, method)(unknown)


def test_resume_session_starts_continue_process_with_fresh_ref(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    launcher.queue(FakeProcess([]))
    launcher.queue(FakeProcess([]))
    provider = ClaudeCodeProvider(launcher=launcher)
    handle = provider.start_session(make_spec(tmp_path))

    resumed = provider.resume_session(handle)

    assert resumed.external_ref != handle.external_ref
    args, _env, _cwd = launcher.calls[1]
    assert "--continue" in args
    assert provider.check_session(resumed).state is ProviderSessionState.RUNNING
    with pytest.raises(ProviderSessionError):
        provider.check_session(handle)


def test_resume_session_uses_custom_resume_prompt_from_metadata(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    launcher.queue(FakeProcess([]))
    launcher.queue(FakeProcess([]))
    provider = ClaudeCodeProvider(launcher=launcher)
    handle = provider.start_session(make_spec(tmp_path, metadata={"resume_prompt": "Keep going."}))

    provider.resume_session(handle)

    args, _env, _cwd = launcher.calls[1]
    assert "Keep going." in args


def test_resume_session_carries_the_model_forward(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    launcher.queue(FakeProcess([]))
    launcher.queue(FakeProcess([]))
    provider = ClaudeCodeProvider(launcher=launcher)
    handle = provider.start_session(make_spec(tmp_path, model="claude-opus-4-8"))

    provider.resume_session(handle)

    args, _env, _cwd = launcher.calls[1]
    assert args[args.index("--model") + 1] == "claude-opus-4-8"


def test_stop_session_terminates_running_process(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    process = FakeProcess([])
    launcher.queue(process)
    provider = ClaudeCodeProvider(launcher=launcher)
    handle = provider.start_session(make_spec(tmp_path))

    provider.stop_session(handle)

    assert process.terminated
    with pytest.raises(ProviderSessionError):
        provider.stop_session(handle)


def test_stop_session_kills_process_that_ignores_terminate(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    process = StubbornProcess([])
    launcher.queue(process)
    provider = ClaudeCodeProvider(launcher=launcher)
    handle = provider.start_session(make_spec(tmp_path))

    provider.stop_session(handle)

    assert process.terminated
    assert process.killed


def test_stop_session_on_finished_process_skips_terminate(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    process = FakeProcess([], returncode=0)
    process.finish()
    launcher.queue(process)
    provider = ClaudeCodeProvider(launcher=launcher)
    handle = provider.start_session(make_spec(tmp_path))

    provider.stop_session(handle)

    assert not process.terminated


def test_real_subprocess_end_to_end_reports_finished(tmp_path: Path) -> None:
    script = (
        "import json; "
        "print(json.dumps({'result': 'All done.', 'is_error': False}))"
    )
    provider = ClaudeCodeProvider(command=(sys.executable, "-c", script))

    handle = provider.start_session(make_spec(tmp_path))
    status = provider.check_session(handle)
    deadline = time.time() + 10
    while status.state is ProviderSessionState.RUNNING and time.time() < deadline:
        time.sleep(0.05)
        status = provider.check_session(handle)

    assert status.state is ProviderSessionState.FINISHED
    assert status.detail == "All done."


def test_start_session_passes_the_default_permission_mode(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    launcher.queue(FakeProcess([]))
    provider = ClaudeCodeProvider(launcher=launcher)

    provider.start_session(make_spec(tmp_path))

    args, _env, _cwd = launcher.calls[0]
    assert args[args.index("--permission-mode") + 1] == "default"


def test_start_session_passes_a_configured_permission_mode(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    launcher.queue(FakeProcess([]))
    provider = ClaudeCodeProvider(launcher=launcher, permission_mode="acceptEdits")

    provider.start_session(make_spec(tmp_path))

    args, _env, _cwd = launcher.calls[0]
    assert args[args.index("--permission-mode") + 1] == "acceptEdits"


def test_session_metadata_overrides_the_provider_permission_mode(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    launcher.queue(FakeProcess([]))
    provider = ClaudeCodeProvider(launcher=launcher, permission_mode="default")

    provider.start_session(
        make_spec(tmp_path, metadata={"permission_mode": "acceptEdits"})
    )

    args, _env, _cwd = launcher.calls[0]
    assert args[args.index("--permission-mode") + 1] == "acceptEdits"


def test_resume_session_keeps_the_original_permission_mode(tmp_path: Path) -> None:
    """A resumed session needs the same authority the first one had.

    Losing it on resume would make a limit-interrupted task quietly
    switch to a mode that cannot act — the ADR 0022 failure, reappearing
    only for long-running work.
    """
    launcher = FakeLauncher()
    launcher.queue(FakeProcess([]))
    launcher.queue(FakeProcess([]))
    provider = ClaudeCodeProvider(launcher=launcher, permission_mode="acceptEdits")
    handle = provider.start_session(make_spec(tmp_path))

    provider.resume_session(handle)

    args, _env, _cwd = launcher.calls[1]
    assert args[args.index("--permission-mode") + 1] == "acceptEdits"

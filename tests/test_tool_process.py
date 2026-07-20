"""Tests for the shared subprocess harness (`run_process`)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from runtime.commands.context import CancellationToken
from runtime.exceptions import CommandCancelledError, ToolExecutionError
from runtime.tools.process import run_process

NOT_CANCELLED = CancellationToken(cancelled=False)


def test_runs_argv_command_and_captures_stdout(tmp_path: Path) -> None:
    outcome = run_process(
        [sys.executable, "-c", "print('hello')"],
        cwd=tmp_path,
        env=dict(os.environ),
        timeout_seconds=10,
        cancellation_token=NOT_CANCELLED,
    )

    assert outcome.exit_code == 0
    assert outcome.stdout.strip() == "hello"
    assert outcome.timed_out is False


def test_reports_nonzero_exit_code(tmp_path: Path) -> None:
    outcome = run_process(
        [sys.executable, "-c", "import sys; sys.exit(3)"],
        cwd=tmp_path,
        env=dict(os.environ),
        timeout_seconds=10,
        cancellation_token=NOT_CANCELLED,
    )

    assert outcome.exit_code == 3


def test_captures_stderr(tmp_path: Path) -> None:
    outcome = run_process(
        [sys.executable, "-c", "import sys; sys.stderr.write('oops')"],
        cwd=tmp_path,
        env=dict(os.environ),
        timeout_seconds=10,
        cancellation_token=NOT_CANCELLED,
    )

    assert "oops" in outcome.stderr


def test_runs_via_shell_when_shell_true(tmp_path: Path) -> None:
    command = f'"{sys.executable}" -c "print(2 + 2)"'

    outcome = run_process(
        command,
        cwd=tmp_path,
        env=dict(os.environ),
        timeout_seconds=10,
        cancellation_token=NOT_CANCELLED,
        shell=True,
    )

    assert outcome.exit_code == 0
    assert outcome.stdout.strip() == "4"


def test_respects_cwd(tmp_path: Path) -> None:
    (tmp_path / "marker.txt").write_text("here", encoding="utf-8")

    outcome = run_process(
        [sys.executable, "-c", "import pathlib; print(pathlib.Path('marker.txt').exists())"],
        cwd=tmp_path,
        env=dict(os.environ),
        timeout_seconds=10,
        cancellation_token=NOT_CANCELLED,
    )

    assert outcome.stdout.strip() == "True"


def test_respects_env(tmp_path: Path) -> None:
    env = dict(os.environ)
    env["ZENITH_TOOL_TEST_VAR"] = "hi"

    outcome = run_process(
        [sys.executable, "-c", "import os; print(os.environ.get('ZENITH_TOOL_TEST_VAR'))"],
        cwd=tmp_path,
        env=env,
        timeout_seconds=10,
        cancellation_token=NOT_CANCELLED,
    )

    assert outcome.stdout.strip() == "hi"


def test_times_out_a_long_running_process(tmp_path: Path) -> None:
    outcome = run_process(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=tmp_path,
        env=dict(os.environ),
        timeout_seconds=0.3,
        cancellation_token=NOT_CANCELLED,
    )

    assert outcome.timed_out is True


def test_cancelled_before_start_raises_without_running_anything(tmp_path: Path) -> None:
    marker = tmp_path / "should_not_exist.txt"

    with pytest.raises(CommandCancelledError):
        run_process(
            [sys.executable, "-c", f"open(r'{marker}', 'w').close()"],
            cwd=tmp_path,
            env=dict(os.environ),
            timeout_seconds=10,
            cancellation_token=CancellationToken(cancelled=True),
        )

    assert not marker.exists()


def test_missing_executable_raises_tool_execution_error(tmp_path: Path) -> None:
    with pytest.raises(ToolExecutionError):
        run_process(
            ["definitely-not-a-real-executable-xyz"],
            cwd=tmp_path,
            env=dict(os.environ),
            timeout_seconds=10,
            cancellation_token=NOT_CANCELLED,
        )

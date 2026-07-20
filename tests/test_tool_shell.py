"""Tests for ShellTool."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from configs.config import Config
from runtime.commands.context import CancellationToken, CommandContext
from runtime.context import ApplicationContext
from runtime.exceptions import CommandCancelledError, ToolExecutionError
from runtime.tools.shell import ShellTool

PY = f'"{sys.executable}"'


def make_context(cancelled: bool = False) -> CommandContext:
    app_context = ApplicationContext(config=Config(), logger=logging.getLogger("test.shell_tool"))
    return CommandContext(
        application_context=app_context,
        command_id=uuid4(),
        cancellation_token=CancellationToken(cancelled=cancelled),
    )


def invoke(tool: ShellTool, arguments: dict, cancelled: bool = False) -> object:
    return tool.invoke(make_context(cancelled=cancelled), arguments)


# --- identity ----------------------------------------------------------------


def test_tool_identity(tmp_path: Path) -> None:
    tool = ShellTool(tmp_path)

    assert tool.tool_id == "shell"
    assert tool.name == "Shell"


def test_parameters_declare_command(tmp_path: Path) -> None:
    names = {parameter.name for parameter in ShellTool(tmp_path).parameters}

    assert {"command", "cwd", "env", "timeout_seconds"} <= names


# --- execution ----------------------------------------------------------------


def test_runs_a_command_and_captures_stdout(tmp_path: Path) -> None:
    tool = ShellTool(tmp_path)

    result = invoke(tool, {"command": f"{PY} -c \"print('hi')\""})

    assert result.exit_code == 0
    assert result.stdout.strip() == "hi"
    assert result.success is True


def test_reports_nonzero_exit_code(tmp_path: Path) -> None:
    tool = ShellTool(tmp_path)

    result = invoke(tool, {"command": f"{PY} -c \"import sys; sys.exit(2)\""})

    assert result.exit_code == 2
    assert result.success is False


def test_defaults_cwd_to_sandbox_root(tmp_path: Path) -> None:
    (tmp_path / "marker.txt").write_text("x", encoding="utf-8")
    tool = ShellTool(tmp_path)

    result = invoke(
        tool,
        {"command": f"{PY} -c \"import pathlib; print(pathlib.Path('marker.txt').exists())\""},
    )

    assert result.stdout.strip() == "True"
    assert result.cwd == "."


def test_runs_in_a_sandboxed_subdirectory(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "marker.txt").write_text("x", encoding="utf-8")
    tool = ShellTool(tmp_path)

    result = invoke(
        tool,
        {
            "command": f"{PY} -c \"import pathlib; print(pathlib.Path('marker.txt').exists())\"",
            "cwd": "sub",
        },
    )

    assert result.stdout.strip() == "True"
    assert result.cwd == "sub"


def test_cwd_escaping_sandbox_raises(tmp_path: Path) -> None:
    tool = ShellTool(tmp_path)

    with pytest.raises(ToolExecutionError):
        invoke(tool, {"command": "echo hi", "cwd": "../outside"})


def test_env_variables_are_merged_over_inherited_environment(tmp_path: Path) -> None:
    tool = ShellTool(tmp_path)

    result = invoke(
        tool,
        {
            "command": f"{PY} -c \"import os; print(os.environ.get('ZENITH_SHELL_TEST'))\"",
            "env": {"ZENITH_SHELL_TEST": "present"},
        },
    )

    assert result.stdout.strip() == "present"


def test_timeout_seconds_overrides_default(tmp_path: Path) -> None:
    tool = ShellTool(tmp_path, default_timeout_seconds=30.0)

    result = invoke(
        tool,
        {"command": f"{PY} -c \"import time; time.sleep(30)\"", "timeout_seconds": 0.3},
    )

    assert result.timed_out is True


def test_cancelled_token_raises_before_running(tmp_path: Path) -> None:
    marker = tmp_path / "should_not_exist.txt"
    tool = ShellTool(tmp_path)

    with pytest.raises(CommandCancelledError):
        invoke(
            tool,
            {"command": f"{PY} -c \"open('should_not_exist.txt', 'w').close()\""},
            cancelled=True,
        )

    assert not marker.exists()


def test_str_includes_command_and_streams(tmp_path: Path) -> None:
    tool = ShellTool(tmp_path)

    result = invoke(tool, {"command": f"{PY} -c \"print('out'); import sys; sys.exit(0)\""})

    rendered = str(result)
    assert "$ " in rendered
    assert "out" in rendered

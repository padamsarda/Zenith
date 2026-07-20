"""Tests for TestRunnerTool."""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import uuid4

import pytest

from configs.config import Config
from runtime.commands.context import CancellationToken, CommandContext
from runtime.context import ApplicationContext
from runtime.exceptions import CommandCancelledError, ToolExecutionError
from runtime.tools.test_runner import TestRunnerTool


def make_context(cancelled: bool = False) -> CommandContext:
    app_context = ApplicationContext(
        config=Config(), logger=logging.getLogger("test.test_runner_tool")
    )
    return CommandContext(
        application_context=app_context,
        command_id=uuid4(),
        cancellation_token=CancellationToken(cancelled=cancelled),
    )


def invoke(tool: TestRunnerTool, arguments: dict, cancelled: bool = False) -> object:
    return tool.invoke(make_context(cancelled=cancelled), arguments)


PASSING_TEST = "def test_ok():\n    assert 1 + 1 == 2\n"
FAILING_TEST = "def test_bad():\n    assert 1 + 1 == 3\n"


# --- identity ----------------------------------------------------------------


def test_tool_identity(tmp_path: Path) -> None:
    tool = TestRunnerTool(tmp_path)

    assert tool.tool_id == "test_runner"
    assert tool.name == "Test Runner"


def test_parameters_declare_path_and_args(tmp_path: Path) -> None:
    names = {parameter.name for parameter in TestRunnerTool(tmp_path).parameters}

    assert {"path", "args", "timeout_seconds"} <= names


# --- running ----------------------------------------------------------------


def test_passing_test_reports_success(tmp_path: Path) -> None:
    (tmp_path / "test_pass.py").write_text(PASSING_TEST, encoding="utf-8")
    tool = TestRunnerTool(tmp_path)

    result = invoke(tool, {"path": "test_pass.py"})

    assert result.exit_code == 0
    assert result.success is True
    assert result.passed == 1
    assert result.failed == 0


def test_failing_test_reports_failure(tmp_path: Path) -> None:
    (tmp_path / "test_fail.py").write_text(FAILING_TEST, encoding="utf-8")
    tool = TestRunnerTool(tmp_path)

    result = invoke(tool, {"path": "test_fail.py"})

    assert result.exit_code == 1
    assert result.success is False
    assert result.failed == 1
    assert result.passed == 0


def test_runs_the_whole_directory_when_no_path_given(tmp_path: Path) -> None:
    (tmp_path / "test_pass.py").write_text(PASSING_TEST, encoding="utf-8")
    (tmp_path / "test_fail.py").write_text(FAILING_TEST, encoding="utf-8")
    tool = TestRunnerTool(tmp_path)

    result = invoke(tool, {})

    assert result.passed == 1
    assert result.failed == 1


def test_args_are_passed_through_to_the_runner(tmp_path: Path) -> None:
    (tmp_path / "test_both.py").write_text(PASSING_TEST + FAILING_TEST, encoding="utf-8")
    tool = TestRunnerTool(tmp_path)

    result = invoke(tool, {"path": "test_both.py", "args": ["-k", "test_ok"]})

    assert result.passed == 1
    assert result.failed == 0


def test_path_escaping_sandbox_raises(tmp_path: Path) -> None:
    tool = TestRunnerTool(tmp_path)

    with pytest.raises(ToolExecutionError):
        invoke(tool, {"path": "../outside_tests"})


def test_timeout_kills_a_long_running_test(tmp_path: Path) -> None:
    (tmp_path / "test_slow.py").write_text(
        "import time\n\n\ndef test_slow():\n    time.sleep(30)\n", encoding="utf-8"
    )
    tool = TestRunnerTool(tmp_path, default_timeout_seconds=30.0)

    result = invoke(tool, {"path": "test_slow.py", "timeout_seconds": 2.0})

    assert result.timed_out is True


def test_cancelled_token_raises_before_running(tmp_path: Path) -> None:
    (tmp_path / "test_pass.py").write_text(PASSING_TEST, encoding="utf-8")
    tool = TestRunnerTool(tmp_path)

    with pytest.raises(CommandCancelledError):
        invoke(tool, {"path": "test_pass.py"}, cancelled=True)


def test_str_includes_parsed_counts(tmp_path: Path) -> None:
    (tmp_path / "test_pass.py").write_text(PASSING_TEST, encoding="utf-8")
    tool = TestRunnerTool(tmp_path)

    result = invoke(tool, {"path": "test_pass.py"})

    rendered = str(result)
    assert "passed=1" in rendered

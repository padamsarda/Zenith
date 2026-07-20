"""Tests for DiffTool."""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import uuid4

import pytest

from configs.config import Config
from runtime.commands.context import CommandContext
from runtime.context import ApplicationContext
from runtime.exceptions import ToolExecutionError
from runtime.tools.diff import DiffTool


def make_context() -> CommandContext:
    app_context = ApplicationContext(config=Config(), logger=logging.getLogger("test.diff_tool"))
    return CommandContext(application_context=app_context, command_id=uuid4())


def invoke(tool: DiffTool, arguments: dict) -> object:
    return tool.invoke(make_context(), arguments)


# --- identity ----------------------------------------------------------------


def test_tool_identity(tmp_path: Path) -> None:
    tool = DiffTool(tmp_path)

    assert tool.tool_id == "diff"
    assert tool.name == "Diff"


def test_parameters_declare_both_modes(tmp_path: Path) -> None:
    names = {parameter.name for parameter in DiffTool(tmp_path).parameters}

    assert {"from_text", "to_text", "from_path", "to_path", "context_lines"} <= names


# --- text mode ----------------------------------------------------------------


def test_text_diff_reports_added_and_removed_lines(tmp_path: Path) -> None:
    tool = DiffTool(tmp_path)

    result = invoke(tool, {"from_text": "one\ntwo\n", "to_text": "one\nthree\n"})

    assert result.lines_added == 1
    assert result.lines_removed == 1
    assert "-two" in result.unified_diff
    assert "+three" in result.unified_diff


def test_identical_text_reports_no_differences(tmp_path: Path) -> None:
    tool = DiffTool(tmp_path)

    result = invoke(tool, {"from_text": "same\n", "to_text": "same\n"})

    assert result.identical is True
    assert result.unified_diff == ""
    assert "No differences" in str(result)


def test_str_returns_the_unified_diff_when_different(tmp_path: Path) -> None:
    tool = DiffTool(tmp_path)

    result = invoke(tool, {"from_text": "a\n", "to_text": "b\n"})

    assert str(result) == result.unified_diff


def test_only_from_text_raises(tmp_path: Path) -> None:
    tool = DiffTool(tmp_path)

    with pytest.raises(ToolExecutionError):
        invoke(tool, {"from_text": "a"})


def test_neither_pair_raises(tmp_path: Path) -> None:
    tool = DiffTool(tmp_path)

    with pytest.raises(ToolExecutionError):
        invoke(tool, {})


def test_mixing_text_and_path_raises(tmp_path: Path) -> None:
    tool = DiffTool(tmp_path)

    with pytest.raises(ToolExecutionError):
        invoke(tool, {"from_text": "a", "to_path": "b.txt"})


# --- path mode ----------------------------------------------------------------


def test_path_diff_reads_sandboxed_files(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("one\ntwo\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("one\nthree\n", encoding="utf-8")
    tool = DiffTool(tmp_path)

    result = invoke(tool, {"from_path": "a.txt", "to_path": "b.txt"})

    assert result.from_label == "a.txt"
    assert result.to_label == "b.txt"
    assert "-two" in result.unified_diff
    assert "+three" in result.unified_diff


def test_path_diff_missing_file_raises(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("one\n", encoding="utf-8")
    tool = DiffTool(tmp_path)

    with pytest.raises(ToolExecutionError):
        invoke(tool, {"from_path": "a.txt", "to_path": "missing.txt"})


def test_path_diff_escaping_sandbox_raises(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("one\n", encoding="utf-8")
    tool = DiffTool(tmp_path)

    with pytest.raises(ToolExecutionError):
        invoke(tool, {"from_path": "a.txt", "to_path": "../outside.txt"})


# --- context_lines ----------------------------------------------------------------


def test_context_lines_limits_surrounding_context(tmp_path: Path) -> None:
    from_text = "\n".join(f"line{i}" for i in range(20)) + "\n"
    to_lines = [f"line{i}" for i in range(20)]
    to_lines[10] = "CHANGED"
    to_text = "\n".join(to_lines) + "\n"
    tool = DiffTool(tmp_path)

    result = invoke(
        tool, {"from_text": from_text, "to_text": to_text, "context_lines": 1}
    )

    assert "line9" in result.unified_diff
    assert "line0" not in result.unified_diff

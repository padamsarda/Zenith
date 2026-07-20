"""Tests for FilesystemTool."""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import uuid4

import pytest

from configs.config import Config
from runtime.commands.context import CommandContext
from runtime.context import ApplicationContext
from runtime.exceptions import ToolExecutionError
from runtime.tools.filesystem import FilesystemTool


def make_context(root: Path) -> CommandContext:
    app_context = ApplicationContext(config=Config(), logger=logging.getLogger("test.fs_tool"))
    return CommandContext(application_context=app_context, command_id=uuid4())


def invoke(tool: FilesystemTool, root: Path, arguments: dict) -> object:
    return tool.invoke(make_context(root), arguments)


# --- identity ----------------------------------------------------------------


def test_tool_identity(tmp_path: Path) -> None:
    tool = FilesystemTool(tmp_path)

    assert tool.tool_id == "filesystem"
    assert tool.name == "Filesystem"
    assert "sandbox" in tool.description.lower()


def test_parameters_declare_operation_and_path(tmp_path: Path) -> None:
    names = {parameter.name for parameter in FilesystemTool(tmp_path).parameters}

    assert {"operation", "path", "content", "recursive", "create_parents"} <= names


# --- read ----------------------------------------------------------------


def test_read_returns_file_content(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello world", encoding="utf-8")
    tool = FilesystemTool(tmp_path)

    result = invoke(tool, tmp_path, {"operation": "read", "path": "a.txt"})

    assert result.content == "hello world"
    assert str(result) == "hello world"


def test_read_missing_file_raises(tmp_path: Path) -> None:
    tool = FilesystemTool(tmp_path)

    with pytest.raises(ToolExecutionError):
        invoke(tool, tmp_path, {"operation": "read", "path": "missing.txt"})


def test_read_directory_raises(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    tool = FilesystemTool(tmp_path)

    with pytest.raises(ToolExecutionError):
        invoke(tool, tmp_path, {"operation": "read", "path": "sub"})


def test_read_oversized_file_raises(tmp_path: Path) -> None:
    (tmp_path / "big.txt").write_text("x" * 100, encoding="utf-8")
    tool = FilesystemTool(tmp_path, max_read_bytes=10)

    with pytest.raises(ToolExecutionError):
        invoke(tool, tmp_path, {"operation": "read", "path": "big.txt"})


def test_read_escaping_sandbox_raises(tmp_path: Path) -> None:
    tool = FilesystemTool(tmp_path)

    with pytest.raises(ToolExecutionError):
        invoke(tool, tmp_path, {"operation": "read", "path": "../outside.txt"})


# --- write ----------------------------------------------------------------


def test_write_creates_a_file(tmp_path: Path) -> None:
    tool = FilesystemTool(tmp_path)

    result = invoke(tool, tmp_path, {"operation": "write", "path": "a.txt", "content": "hi"})

    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hi"
    assert "Wrote" in str(result)


def test_write_overwrites_existing_file(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("old", encoding="utf-8")
    tool = FilesystemTool(tmp_path)

    invoke(tool, tmp_path, {"operation": "write", "path": "a.txt", "content": "new"})

    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "new"


def test_write_allows_empty_content(tmp_path: Path) -> None:
    tool = FilesystemTool(tmp_path)

    invoke(tool, tmp_path, {"operation": "write", "path": "empty.txt", "content": ""})

    assert (tmp_path / "empty.txt").read_text(encoding="utf-8") == ""


def test_write_non_string_content_raises(tmp_path: Path) -> None:
    tool = FilesystemTool(tmp_path)

    with pytest.raises(ToolExecutionError):
        invoke(tool, tmp_path, {"operation": "write", "path": "a.txt", "content": 42})


def test_write_to_directory_raises(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    tool = FilesystemTool(tmp_path)

    with pytest.raises(ToolExecutionError):
        invoke(tool, tmp_path, {"operation": "write", "path": "sub", "content": "x"})


def test_write_missing_parent_without_create_parents_raises(tmp_path: Path) -> None:
    tool = FilesystemTool(tmp_path)

    with pytest.raises(ToolExecutionError):
        invoke(tool, tmp_path, {"operation": "write", "path": "a/b.txt", "content": "x"})


def test_write_missing_parent_with_create_parents_creates_it(tmp_path: Path) -> None:
    tool = FilesystemTool(tmp_path)

    invoke(
        tool,
        tmp_path,
        {"operation": "write", "path": "a/b.txt", "content": "x", "create_parents": True},
    )

    assert (tmp_path / "a" / "b.txt").read_text(encoding="utf-8") == "x"


# --- list ----------------------------------------------------------------


def test_list_returns_sorted_entries_with_trailing_slash_for_dirs(tmp_path: Path) -> None:
    (tmp_path / "b.txt").write_text("x", encoding="utf-8")
    (tmp_path / "a_dir").mkdir()
    tool = FilesystemTool(tmp_path)

    result = invoke(tool, tmp_path, {"operation": "list", "path": "."})

    assert result.entries == ("a_dir/", "b.txt")
    assert str(result) == "a_dir/\nb.txt"


def test_list_empty_directory(tmp_path: Path) -> None:
    tool = FilesystemTool(tmp_path)

    result = invoke(tool, tmp_path, {"operation": "list", "path": "."})

    assert result.entries == ()
    assert str(result) == "(empty directory)"


def test_list_non_directory_raises(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    tool = FilesystemTool(tmp_path)

    with pytest.raises(ToolExecutionError):
        invoke(tool, tmp_path, {"operation": "list", "path": "a.txt"})


# --- mkdir ----------------------------------------------------------------


def test_mkdir_creates_nested_directories(tmp_path: Path) -> None:
    tool = FilesystemTool(tmp_path)

    invoke(tool, tmp_path, {"operation": "mkdir", "path": "a/b/c"})

    assert (tmp_path / "a" / "b" / "c").is_dir()


def test_mkdir_is_idempotent(tmp_path: Path) -> None:
    tool = FilesystemTool(tmp_path)

    invoke(tool, tmp_path, {"operation": "mkdir", "path": "a"})
    invoke(tool, tmp_path, {"operation": "mkdir", "path": "a"})

    assert (tmp_path / "a").is_dir()


def test_mkdir_over_existing_file_raises(tmp_path: Path) -> None:
    (tmp_path / "a").write_text("x", encoding="utf-8")
    tool = FilesystemTool(tmp_path)

    with pytest.raises(ToolExecutionError):
        invoke(tool, tmp_path, {"operation": "mkdir", "path": "a"})


# --- delete ----------------------------------------------------------------


def test_delete_removes_a_file(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    tool = FilesystemTool(tmp_path)

    invoke(tool, tmp_path, {"operation": "delete", "path": "a.txt"})

    assert not (tmp_path / "a.txt").exists()


def test_delete_removes_an_empty_directory(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    tool = FilesystemTool(tmp_path)

    invoke(tool, tmp_path, {"operation": "delete", "path": "sub"})

    assert not (tmp_path / "sub").exists()


def test_delete_non_empty_directory_without_recursive_raises(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.txt").write_text("x", encoding="utf-8")
    tool = FilesystemTool(tmp_path)

    with pytest.raises(ToolExecutionError):
        invoke(tool, tmp_path, {"operation": "delete", "path": "sub"})


def test_delete_non_empty_directory_with_recursive_removes_it(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.txt").write_text("x", encoding="utf-8")
    tool = FilesystemTool(tmp_path)

    invoke(tool, tmp_path, {"operation": "delete", "path": "sub", "recursive": True})

    assert not (tmp_path / "sub").exists()


def test_delete_missing_path_raises(tmp_path: Path) -> None:
    tool = FilesystemTool(tmp_path)

    with pytest.raises(ToolExecutionError):
        invoke(tool, tmp_path, {"operation": "delete", "path": "missing"})


def test_delete_sandbox_root_raises(tmp_path: Path) -> None:
    tool = FilesystemTool(tmp_path)

    with pytest.raises(ToolExecutionError):
        invoke(tool, tmp_path, {"operation": "delete", "path": "."})


# --- exists ----------------------------------------------------------------


def test_exists_true_for_file(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    tool = FilesystemTool(tmp_path)

    result = invoke(tool, tmp_path, {"operation": "exists", "path": "a.txt"})

    assert result.exists is True


def test_exists_false_for_missing(tmp_path: Path) -> None:
    tool = FilesystemTool(tmp_path)

    result = invoke(tool, tmp_path, {"operation": "exists", "path": "missing"})

    assert result.exists is False


# --- invoke dispatch ----------------------------------------------------------------


def test_unknown_operation_raises(tmp_path: Path) -> None:
    tool = FilesystemTool(tmp_path)

    with pytest.raises(ToolExecutionError):
        invoke(tool, tmp_path, {"operation": "delete_everything", "path": "."})


def test_missing_operation_raises(tmp_path: Path) -> None:
    tool = FilesystemTool(tmp_path)

    with pytest.raises(ToolExecutionError):
        invoke(tool, tmp_path, {"path": "."})


def test_missing_path_raises(tmp_path: Path) -> None:
    tool = FilesystemTool(tmp_path)

    with pytest.raises(ToolExecutionError):
        invoke(tool, tmp_path, {"operation": "read"})

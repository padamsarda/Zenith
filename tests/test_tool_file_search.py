"""Tests for FileSearchTool."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from uuid import uuid4

import pytest

from configs.config import Config
from runtime.commands.context import CommandContext
from runtime.context import ApplicationContext
from runtime.exceptions import ToolExecutionError
from runtime.tools.file_search import FileSearchTool, default_roots


def make_context() -> CommandContext:
    app_context = ApplicationContext(config=Config(), logger=logging.getLogger("test.file_search"))
    return CommandContext(application_context=app_context, command_id=uuid4())


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A small tree resembling the folders a person actually has."""
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "mppt-design.md").write_text(
        "The MPPT charge controller tracks the panel's peak power point.",
        encoding="utf-8",
    )
    (tmp_path / "notes" / "meeting.md").write_text(
        "Discussed the battery chemistry.", encoding="utf-8"
    )
    (tmp_path / "datasheets").mkdir()
    (tmp_path / "datasheets" / "lt3652-datasheet.txt").write_text(
        "LT3652 Power Tracking Battery Charger", encoding="utf-8"
    )
    (tmp_path / "datasheets" / "scan.png").write_bytes(b"\x89PNG\r\n\x1a\n binary MPPT")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "mppt-imposter.md").write_text("MPPT", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("MPPT", encoding="utf-8")
    return tmp_path


def make_tool(workspace: Path, **kwargs) -> FileSearchTool:
    return FileSearchTool({"work": workspace}, **kwargs)


def search(tool: FileSearchTool, **arguments) -> object:
    return tool.invoke(make_context(), arguments)


# --- identity ----------------------------------------------------------------


def test_tool_identity(workspace: Path) -> None:
    tool = make_tool(workspace)

    assert tool.tool_id == "file_search"
    assert tool.name == "File Search"
    assert {parameter.name for parameter in tool.parameters} == {
        "operation",
        "query",
        "root",
        "limit",
    }


def test_read_only_operations_only(workspace: Path) -> None:
    # The property that makes searching several roots safe to allow.
    descriptions = " ".join(
        str(parameter.description) for parameter in make_tool(workspace).parameters
    )
    for verb in ("write", "delete", "move", "rename"):
        assert verb not in descriptions.lower()


# --- name search ----------------------------------------------------------------


def test_name_search_finds_a_substring_match(workspace: Path) -> None:
    result = search(make_tool(workspace), operation="name", query="mppt")

    # Forward slashes on every platform, so a path never renders as a
    # mix of both.
    assert [hit.path for hit in result.hits] == ["work/notes/mppt-design.md"]


def test_name_search_is_case_insensitive(workspace: Path) -> None:
    result = search(make_tool(workspace), operation="name", query="MPPT")

    assert len(result.hits) == 1


def test_name_search_supports_wildcards(workspace: Path) -> None:
    result = search(make_tool(workspace), operation="name", query="*.md")

    assert len(result.hits) == 2


def test_name_search_with_no_match(workspace: Path) -> None:
    result = search(make_tool(workspace), operation="name", query="nonexistent")

    assert result.hits == ()
    assert "No files matched" in str(result)


def test_name_search_requires_a_query(workspace: Path) -> None:
    with pytest.raises(ToolExecutionError):
        search(make_tool(workspace), operation="name")


# --- content search ----------------------------------------------------------------


def test_content_search_finds_text_inside_a_file(workspace: Path) -> None:
    result = search(make_tool(workspace), operation="content", query="peak power")

    assert len(result.hits) == 1
    assert "mppt-design.md" in result.hits[0].path


def test_content_search_returns_the_matching_line(workspace: Path) -> None:
    result = search(make_tool(workspace), operation="content", query="peak power")

    assert "peak power point" in result.hits[0].excerpt


def test_content_search_matches_across_different_files(workspace: Path) -> None:
    result = search(make_tool(workspace), operation="content", query="battery")

    assert len(result.hits) == 2


def test_content_search_skips_binary_extensions(workspace: Path) -> None:
    # The .png contains the bytes "MPPT" but is not a text file; matching
    # it would be noise, not a find.
    result = search(make_tool(workspace), operation="content", query="MPPT")

    assert all(not hit.path.endswith(".png") for hit in result.hits)


def test_content_search_skips_oversized_files(workspace: Path) -> None:
    (workspace / "notes" / "huge.txt").write_text("MPPT " * 1000, encoding="utf-8")

    result = search(make_tool(workspace, max_content_bytes=50), operation="content", query="MPPT")

    assert all("huge.txt" not in hit.path for hit in result.hits)


def test_content_search_requires_a_query(workspace: Path) -> None:
    with pytest.raises(ToolExecutionError):
        search(make_tool(workspace), operation="content", query="   ")


# --- pruning ----------------------------------------------------------------


def test_node_modules_is_not_searched(workspace: Path) -> None:
    result = search(make_tool(workspace), operation="name", query="mppt")

    assert all("node_modules" not in hit.path for hit in result.hits)


def test_dot_directories_are_not_searched(workspace: Path) -> None:
    result = search(make_tool(workspace), operation="content", query="MPPT")

    assert all(".git" not in hit.path for hit in result.hits)


# --- recent ----------------------------------------------------------------


def test_recent_returns_newest_first(workspace: Path) -> None:
    time.sleep(0.01)
    (workspace / "notes" / "newest.md").write_text("just written", encoding="utf-8")

    result = search(make_tool(workspace), operation="recent")

    assert "newest.md" in result.hits[0].path


def test_recent_can_filter_by_name(workspace: Path) -> None:
    result = search(make_tool(workspace), operation="recent", query="datasheet")

    assert len(result.hits) == 1
    assert "lt3652" in result.hits[0].path


def test_recent_needs_no_query(workspace: Path) -> None:
    result = search(make_tool(workspace), operation="recent")

    assert len(result.hits) > 1


# --- roots ----------------------------------------------------------------


def test_search_can_be_restricted_to_one_root(tmp_path: Path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    (first / "target.md").write_text("x", encoding="utf-8")
    (second / "target.md").write_text("x", encoding="utf-8")
    tool = FileSearchTool({"a": first, "b": second})

    result = search(tool, operation="name", query="target", root="a")

    assert len(result.hits) == 1
    assert result.hits[0].root == "a"


def test_all_roots_are_searched_by_default(tmp_path: Path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    (first / "target.md").write_text("x", encoding="utf-8")
    (second / "target.md").write_text("x", encoding="utf-8")
    tool = FileSearchTool({"a": first, "b": second})

    result = search(tool, operation="name", query="target")

    assert {hit.root for hit in result.hits} == {"a", "b"}


def test_unknown_root_raises(workspace: Path) -> None:
    with pytest.raises(ToolExecutionError):
        search(make_tool(workspace), operation="name", query="x", root="elsewhere")


def test_explicitly_empty_roots_searches_nothing_rather_than_everything() -> None:
    # An empty mapping means "no roots". Falling back to the default
    # (the user's whole home directory) would be the worst possible
    # reading of that call.
    with pytest.raises(ToolExecutionError):
        search(FileSearchTool({}), operation="name", query="x")


def test_omitting_roots_uses_the_defaults() -> None:
    tool = FileSearchTool()

    assert {parameter.name for parameter in tool.parameters} == {
        "operation",
        "query",
        "root",
        "limit",
    }


def test_default_roots_all_exist() -> None:
    assert all(path.is_dir() for path in default_roots().values())


# --- limits ----------------------------------------------------------------


def test_limit_caps_results(workspace: Path) -> None:
    result = search(make_tool(workspace), operation="recent", limit=1)

    assert len(result.hits) == 1


def test_truncation_is_reported(workspace: Path) -> None:
    result = search(make_tool(workspace), operation="recent", limit=1)

    assert result.truncated is True
    assert "more exist" in str(result)


@pytest.mark.parametrize("limit", [0, -1, 101])
def test_out_of_range_limit_raises(workspace: Path, limit: int) -> None:
    with pytest.raises(ToolExecutionError):
        search(make_tool(workspace), operation="recent", limit=limit)


def test_scan_budget_is_respected(workspace: Path) -> None:
    result = search(make_tool(workspace, max_scanned=2), operation="recent")

    assert result.scanned <= 2


# --- resilience ----------------------------------------------------------------


def test_a_missing_root_does_not_raise(tmp_path: Path) -> None:
    # A configured folder that has since been deleted must degrade to no
    # results, not an error on every search.
    tool = FileSearchTool({"gone": tmp_path / "does-not-exist"})

    assert search(tool, operation="name", query="anything").hits == ()


def test_unknown_operation_raises(workspace: Path) -> None:
    with pytest.raises(ToolExecutionError):
        search(make_tool(workspace), operation="grep", query="x")

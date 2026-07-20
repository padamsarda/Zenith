"""Tests for GitTool."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from configs.config import Config
from runtime.commands.context import CancellationToken, CommandContext
from runtime.context import ApplicationContext
from runtime.exceptions import CommandCancelledError, ToolExecutionError
from runtime.tools.git import GitTool


def init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-b", "master", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@example.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"], check=True, capture_output=True
    )


def make_context(cancelled: bool = False) -> CommandContext:
    app_context = ApplicationContext(config=Config(), logger=logging.getLogger("test.git_tool"))
    return CommandContext(
        application_context=app_context,
        command_id=uuid4(),
        cancellation_token=CancellationToken(cancelled=cancelled),
    )


def invoke(tool: GitTool, arguments: dict, cancelled: bool = False) -> object:
    return tool.invoke(make_context(cancelled=cancelled), arguments)


# --- identity ----------------------------------------------------------------


def test_tool_identity(tmp_path: Path) -> None:
    tool = GitTool(tmp_path)

    assert tool.tool_id == "git"
    assert tool.name == "Git"


def test_parameters_declare_operation(tmp_path: Path) -> None:
    names = {parameter.name for parameter in GitTool(tmp_path).parameters}

    assert {"operation", "path", "paths", "message", "ref"} <= names


def test_not_a_repository_raises(tmp_path: Path) -> None:
    tool = GitTool(tmp_path)

    with pytest.raises(ToolExecutionError):
        invoke(tool, {"operation": "status"})


def test_unknown_operation_raises(tmp_path: Path) -> None:
    init_repo(tmp_path)
    tool = GitTool(tmp_path)

    with pytest.raises(ToolExecutionError):
        invoke(tool, {"operation": "push"})


# --- status / diff ----------------------------------------------------------------


def test_status_reports_untracked_file(tmp_path: Path) -> None:
    init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    tool = GitTool(tmp_path)

    result = invoke(tool, {"operation": "status"})

    assert result.success is True
    assert "a.txt" in result.stdout


def test_diff_shows_unstaged_changes(tmp_path: Path) -> None:
    init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "a.txt"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "add a"], check=True, capture_output=True
    )
    (tmp_path / "a.txt").write_text("two\n", encoding="utf-8")
    tool = GitTool(tmp_path)

    result = invoke(tool, {"operation": "diff"})

    assert "-one" in result.stdout
    assert "+two" in result.stdout


def test_diff_staged_shows_the_cached_diff(tmp_path: Path) -> None:
    init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    tool = GitTool(tmp_path)
    invoke(tool, {"operation": "add", "paths": ["a.txt"]})

    result = invoke(tool, {"operation": "diff", "staged": True})

    assert "a.txt" in result.stdout


def test_diff_path_escaping_repo_raises(tmp_path: Path) -> None:
    init_repo(tmp_path)
    tool = GitTool(tmp_path)

    with pytest.raises(ToolExecutionError):
        invoke(tool, {"operation": "diff", "path": "../outside.txt"})


# --- add / commit ----------------------------------------------------------------


def test_add_stages_a_file(tmp_path: Path) -> None:
    init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    tool = GitTool(tmp_path)

    result = invoke(tool, {"operation": "add", "paths": ["a.txt"]})
    status = invoke(tool, {"operation": "status"})

    assert result.success is True
    assert "A  a.txt" in status.stdout


def test_add_without_paths_raises(tmp_path: Path) -> None:
    init_repo(tmp_path)
    tool = GitTool(tmp_path)

    with pytest.raises(ToolExecutionError):
        invoke(tool, {"operation": "add", "paths": []})


def test_commit_records_a_commit(tmp_path: Path) -> None:
    init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    tool = GitTool(tmp_path)
    invoke(tool, {"operation": "add", "paths": ["a.txt"]})

    result = invoke(tool, {"operation": "commit", "message": "initial commit"})

    assert result.success is True
    log = subprocess.run(
        ["git", "-C", str(tmp_path), "log", "--oneline"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "initial commit" in log.stdout


def test_commit_with_all_stages_tracked_modifications(tmp_path: Path) -> None:
    init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("one", encoding="utf-8")
    tool = GitTool(tmp_path)
    invoke(tool, {"operation": "add", "paths": ["a.txt"]})
    invoke(tool, {"operation": "commit", "message": "first"})
    (tmp_path / "a.txt").write_text("two", encoding="utf-8")

    result = invoke(tool, {"operation": "commit", "message": "second", "all": True})

    assert result.success is True
    status = invoke(tool, {"operation": "status"})
    assert "a.txt" not in status.stdout


def test_commit_missing_message_raises(tmp_path: Path) -> None:
    init_repo(tmp_path)
    tool = GitTool(tmp_path)

    with pytest.raises(ToolExecutionError):
        invoke(tool, {"operation": "commit"})


# --- branch / checkout ----------------------------------------------------------------


def test_branch_lists_current_branch(tmp_path: Path) -> None:
    init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    tool = GitTool(tmp_path)
    invoke(tool, {"operation": "add", "paths": ["a.txt"]})
    invoke(tool, {"operation": "commit", "message": "first"})

    result = invoke(tool, {"operation": "branch"})

    assert "master" in result.stdout


def test_checkout_create_switches_to_a_new_branch(tmp_path: Path) -> None:
    init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    tool = GitTool(tmp_path)
    invoke(tool, {"operation": "add", "paths": ["a.txt"]})
    invoke(tool, {"operation": "commit", "message": "first"})

    result = invoke(tool, {"operation": "checkout", "ref": "feature", "create": True})

    assert result.success is True
    branch = subprocess.run(
        ["git", "-C", str(tmp_path), "branch", "--show-current"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert branch.stdout.strip() == "feature"


def test_checkout_missing_ref_raises(tmp_path: Path) -> None:
    init_repo(tmp_path)
    tool = GitTool(tmp_path)

    with pytest.raises(ToolExecutionError):
        invoke(tool, {"operation": "checkout"})


# --- log ----------------------------------------------------------------


def test_log_returns_structured_entries_most_recent_first(tmp_path: Path) -> None:
    init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("one", encoding="utf-8")
    tool = GitTool(tmp_path)
    invoke(tool, {"operation": "add", "paths": ["a.txt"]})
    invoke(tool, {"operation": "commit", "message": "first commit"})
    (tmp_path / "a.txt").write_text("two", encoding="utf-8")
    invoke(tool, {"operation": "add", "paths": ["a.txt"]})
    invoke(tool, {"operation": "commit", "message": "second commit"})

    result = invoke(tool, {"operation": "log"})

    assert [entry.subject for entry in result.entries] == ["second commit", "first commit"]
    assert "second commit" in str(result)


def test_log_respects_max_count(tmp_path: Path) -> None:
    init_repo(tmp_path)
    tool = GitTool(tmp_path)
    for index in range(3):
        (tmp_path / "a.txt").write_text(str(index), encoding="utf-8")
        invoke(tool, {"operation": "add", "paths": ["a.txt"]})
        invoke(tool, {"operation": "commit", "message": f"commit {index}"})

    result = invoke(tool, {"operation": "log", "max_count": 2})

    assert len(result.entries) == 2


# --- reset ----------------------------------------------------------------


def test_reset_unstages_everything(tmp_path: Path) -> None:
    init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    tool = GitTool(tmp_path)
    invoke(tool, {"operation": "add", "paths": ["a.txt"]})

    result = invoke(tool, {"operation": "reset"})
    status = invoke(tool, {"operation": "status"})

    assert result.success is True
    assert "?? a.txt" in status.stdout


def test_reset_specific_paths(tmp_path: Path) -> None:
    init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    tool = GitTool(tmp_path)
    invoke(tool, {"operation": "add", "paths": ["a.txt", "b.txt"]})

    invoke(tool, {"operation": "reset", "paths": ["a.txt"]})
    status = invoke(tool, {"operation": "status"})

    assert "?? a.txt" in status.stdout
    assert "A  b.txt" in status.stdout


def test_reset_path_escaping_repo_raises(tmp_path: Path) -> None:
    init_repo(tmp_path)
    tool = GitTool(tmp_path)

    with pytest.raises(ToolExecutionError):
        invoke(tool, {"operation": "reset", "paths": ["../outside.txt"]})


# --- cancellation ----------------------------------------------------------------


def test_cancelled_token_raises_before_running(tmp_path: Path) -> None:
    init_repo(tmp_path)
    tool = GitTool(tmp_path)

    with pytest.raises(CommandCancelledError):
        invoke(tool, {"operation": "status"}, cancelled=True)

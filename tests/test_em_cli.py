"""Tests for the Engineering Manager CLI."""

from __future__ import annotations

from pathlib import Path

import pytest

from engineering_manager.cli import main


def run(tmp_path: Path, *arguments: str) -> int:
    """Run the CLI against a database in tmp_path."""
    return main(["--db", str(tmp_path / "em.db"), *arguments])


def test_init_creates_database(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    exit_code = run(tmp_path, "init")

    assert exit_code == 0
    assert (tmp_path / "em.db").exists()
    assert "Database ready" in capsys.readouterr().out


def test_project_add_and_list(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    assert run(tmp_path, "project", "add", "zenith", "Zenith") == 0

    assert run(tmp_path, "project", "list") == 0
    output = capsys.readouterr().out
    assert "zenith" in output
    assert "ACTIVE" in output


def test_task_add_approve_and_list(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    run(tmp_path, "project", "add", "zenith", "Zenith")
    capsys.readouterr()
    run(tmp_path, "task", "add", "zenith", "Write docs", "--priority", "5")
    task_id = capsys.readouterr().out.split()[2]

    assert run(tmp_path, "task", "approve", task_id) == 0
    assert "READY" in capsys.readouterr().out

    run(tmp_path, "task", "list", "--status", "READY")
    listing = capsys.readouterr().out
    assert "Write docs" in listing
    assert "p5" in listing


def test_task_add_with_dependency(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    run(tmp_path, "project", "add", "zenith", "Zenith")
    capsys.readouterr()
    run(tmp_path, "task", "add", "zenith", "Foundation")
    dependency_id = capsys.readouterr().out.split()[2]

    exit_code = run(
        tmp_path, "task", "add", "zenith", "Building", "--depends-on", dependency_id
    )

    assert exit_code == 0


def test_account_add_and_list(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    run(tmp_path, "account", "add", "claude", "personal", "--label", "Personal")

    assert run(tmp_path, "account", "list") == 0
    assert "claude/personal" in capsys.readouterr().out


def test_status_summarizes_projects_and_tasks(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    run(tmp_path, "project", "add", "zenith", "Zenith")
    run(tmp_path, "task", "add", "zenith", "Write docs")
    capsys.readouterr()

    assert run(tmp_path, "status") == 0
    output = capsys.readouterr().out
    assert "Projects: 1" in output
    assert "1 DRAFT" in output
    assert "Open sessions: 0" in output


def test_log_shows_events_newest_first(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    run(tmp_path, "project", "add", "zenith", "Zenith")
    run(tmp_path, "task", "add", "zenith", "Write docs")
    capsys.readouterr()

    assert run(tmp_path, "log") == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert "TaskAdded" in lines[0]
    assert "ProjectAdded" in lines[1]


def test_domain_error_prints_and_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    exit_code = run(tmp_path, "task", "add", "missing-project", "Write docs")

    assert exit_code == 1
    assert "Error:" in capsys.readouterr().err


def test_duplicate_project_returns_1(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    run(tmp_path, "project", "add", "zenith", "Zenith")

    assert run(tmp_path, "project", "add", "zenith", "Zenith") == 1


def test_invalid_task_id_is_an_argparse_error(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as excinfo:
        run(tmp_path, "task", "approve", "not-a-uuid")

    assert excinfo.value.code == 2

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


def test_plan_add_list_and_approve(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    run(tmp_path, "project", "add", "zenith", "Zenith")
    capsys.readouterr()
    run(tmp_path, "plan", "add", "zenith", "Ship plugins")
    plan_id = capsys.readouterr().out.split()[2]
    run(tmp_path, "task", "add", "zenith", "Write the loader", "--plan", plan_id)
    capsys.readouterr()

    assert run(tmp_path, "plan", "approve", plan_id) == 0
    assert "IN_PROGRESS" in capsys.readouterr().out

    run(tmp_path, "plan", "list")
    listing = capsys.readouterr().out
    assert "Ship plugins" in listing
    assert "IN_PROGRESS" in listing


def test_plan_show_prints_waves(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    run(tmp_path, "project", "add", "zenith", "Zenith")
    capsys.readouterr()
    run(tmp_path, "plan", "add", "zenith", "Ship plugins")
    plan_id = capsys.readouterr().out.split()[2]
    run(tmp_path, "task", "add", "zenith", "Design", "--plan", plan_id)
    design_id = capsys.readouterr().out.split()[2]
    run(
        tmp_path, "task", "add", "zenith", "Build",
        "--plan", plan_id, "--depends-on", design_id,
    )
    capsys.readouterr()

    assert run(tmp_path, "plan", "show", plan_id) == 0
    output = capsys.readouterr().out
    assert "Ship plugins" in output
    assert output.index("Design") < output.index("Build")
    assert "Wave 2" in output


def test_plan_approve_without_tasks_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    run(tmp_path, "project", "add", "zenith", "Zenith")
    capsys.readouterr()
    run(tmp_path, "plan", "add", "zenith", "Empty goal")
    plan_id = capsys.readouterr().out.split()[2]

    assert run(tmp_path, "plan", "approve", plan_id) == 1
    assert "Error" in capsys.readouterr().err


def test_plan_cancel(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    run(tmp_path, "project", "add", "zenith", "Zenith")
    capsys.readouterr()
    run(tmp_path, "plan", "add", "zenith", "Doomed")
    plan_id = capsys.readouterr().out.split()[2]

    assert run(tmp_path, "plan", "cancel", plan_id) == 0
    assert "CANCELLED" in capsys.readouterr().out


def test_task_depend_links_existing_tasks(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    run(tmp_path, "project", "add", "zenith", "Zenith")
    capsys.readouterr()
    run(tmp_path, "task", "add", "zenith", "First")
    first_id = capsys.readouterr().out.split()[2]
    run(tmp_path, "task", "add", "zenith", "Second")
    second_id = capsys.readouterr().out.split()[2]

    assert run(tmp_path, "task", "depend", second_id, first_id) == 0
    assert "depends on" in capsys.readouterr().out


def test_run_registers_claude_code_provider_and_ticks_once(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    run(tmp_path, "project", "add", "zenith", "Zenith")
    run(tmp_path, "account", "add", "claude-code", "personal")
    capsys.readouterr()

    exit_code = run(
        tmp_path,
        "run",
        "--max-ticks",
        "1",
        "--claude-command",
        "non_existent_executable_12345",
    )

    assert exit_code == 0
    assert "Running the execution engine" in capsys.readouterr().out


def test_task_depend_reports_cycle_as_error(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    run(tmp_path, "project", "add", "zenith", "Zenith")
    capsys.readouterr()
    run(tmp_path, "task", "add", "zenith", "First")
    first_id = capsys.readouterr().out.split()[2]
    run(tmp_path, "task", "add", "zenith", "Second", "--depends-on", first_id)
    second_id = capsys.readouterr().out.split()[2]

    assert run(tmp_path, "task", "depend", first_id, second_id) == 1
    assert "cycle" in capsys.readouterr().err


def test_plan_accept_closes_reviewed_work(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """Gate two, in bulk: the step that lets a plan reach COMPLETED."""
    run(tmp_path, "project", "add", "zenith", "Zenith", "--path", str(tmp_path))
    # A workflow run without --accept leaves its work in NEEDS_REVIEW.
    run(
        tmp_path,
        "workflow",
        "zenith",
        "Ship plugins",
        "--provider",
        "in-memory",
        "--interval",
        "0",
        "--artifacts",
        str(tmp_path / "artifacts"),
        "--yes",
    )
    run(tmp_path, "plan", "list")
    plan_id = capsys.readouterr().out.strip().splitlines()[-1].split()[0]

    assert run(tmp_path, "plan", "accept", plan_id) == 0
    assert "IN_PROGRESS" in capsys.readouterr().out

    run(tmp_path, "task", "list", "--status", "NEEDS_REVIEW")
    assert capsys.readouterr().out.strip() == ""


def test_run_until_quiescent_stops_on_its_own(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    run(tmp_path, "project", "add", "zenith", "Zenith")
    run(tmp_path, "account", "add", "claude-code", "personal")
    capsys.readouterr()

    exit_code = run(tmp_path, "run", "--until", "quiescent", "--interval", "0")

    assert exit_code == 0
    assert "Nothing left to advance" in capsys.readouterr().out


def test_run_defaults_to_running_until_the_tick_budget(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    run(tmp_path, "project", "add", "zenith", "Zenith")
    run(tmp_path, "account", "add", "claude-code", "personal")
    capsys.readouterr()

    exit_code = run(tmp_path, "run", "--interval", "0", "--max-ticks", "2")

    assert exit_code == 0
    assert "Nothing left to advance" not in capsys.readouterr().out


def test_run_without_an_account_fails_instead_of_idling(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """A run that could never dispatch should say so, not spin quietly."""
    run(tmp_path, "project", "add", "zenith", "Zenith")
    capsys.readouterr()

    exit_code = run(tmp_path, "run", "--interval", "0", "--max-ticks", "1")

    assert exit_code == 1
    assert "No account is registered" in capsys.readouterr().err


def test_plan_show_detail_includes_task_descriptions(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """Gate one is consent to what the tasks say, so it must be readable."""
    run(tmp_path, "project", "add", "zenith", "Zenith")
    capsys.readouterr()
    run(tmp_path, "plan", "add", "zenith", "Ship it")
    plan_id = capsys.readouterr().out.split()[2]
    run(
        tmp_path, "task", "add", "zenith", "Do the thing",
        "--plan", plan_id, "--description", "The detail that matters.",
    )
    capsys.readouterr()

    run(tmp_path, "plan", "show", plan_id, "--detail")

    assert "The detail that matters." in capsys.readouterr().out


def test_plan_show_without_detail_omits_descriptions(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    run(tmp_path, "project", "add", "zenith", "Zenith")
    capsys.readouterr()
    run(tmp_path, "plan", "add", "zenith", "Ship it")
    plan_id = capsys.readouterr().out.split()[2]
    run(
        tmp_path, "task", "add", "zenith", "Do the thing",
        "--plan", plan_id, "--description", "The detail that matters.",
    )
    capsys.readouterr()

    run(tmp_path, "plan", "show", plan_id)

    assert "The detail that matters." not in capsys.readouterr().out


def test_task_show_reports_the_task_in_full(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    run(tmp_path, "project", "add", "zenith", "Zenith")
    capsys.readouterr()
    run(tmp_path, "task", "add", "zenith", "Do the thing", "--description", "Line one.")
    task_id = capsys.readouterr().out.split()[2]

    run(tmp_path, "task", "show", task_id)

    output = capsys.readouterr().out
    assert "Do the thing" in output
    assert "Line one." in output
    assert "Sessions: 0" in output


def test_task_show_lists_dependencies(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    run(tmp_path, "project", "add", "zenith", "Zenith")
    capsys.readouterr()
    run(tmp_path, "task", "add", "zenith", "First")
    first_id = capsys.readouterr().out.split()[2]
    run(tmp_path, "task", "add", "zenith", "Second", "--depends-on", first_id)
    second_id = capsys.readouterr().out.split()[2]

    run(tmp_path, "task", "show", second_id)

    assert f"Depends on: {first_id}" in capsys.readouterr().out


def test_project_relocate_repoints_the_project(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """A project's identity is its id, not where it sits on disk."""
    destination = tmp_path / "worktree"
    destination.mkdir()
    run(tmp_path, "project", "add", "zenith", "Zenith")
    capsys.readouterr()

    exit_code = run(tmp_path, "project", "relocate", "zenith", "--path", str(destination))

    assert exit_code == 0
    assert str(destination.resolve()) in capsys.readouterr().out


def test_project_relocate_keeps_existing_tasks(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """Relocating must not cost the project its history."""
    destination = tmp_path / "worktree"
    destination.mkdir()
    run(tmp_path, "project", "add", "zenith", "Zenith")
    run(tmp_path, "task", "add", "zenith", "Write docs")
    run(tmp_path, "project", "relocate", "zenith", "--path", str(destination))
    capsys.readouterr()

    run(tmp_path, "task", "list", "--project", "zenith")

    assert "Write docs" in capsys.readouterr().out

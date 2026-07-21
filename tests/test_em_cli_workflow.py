"""Tests for the end-to-end `workflow` command.

These drive the real CLI against the simulated provider, so they cover
the lifecycle as a user meets it — decomposition, gate one, execution,
gate two, and the report — rather than any one step in isolation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engineering_manager.cli import main
from engineering_manager.domain.states import PlanStatus, TaskStatus
from engineering_manager.manager import EngineeringManager
from engineering_manager.store.store import Store


def run(tmp_path: Path, *arguments: str) -> int:
    """Run the CLI against a database in tmp_path."""
    return main(["--db", str(tmp_path / "em.db"), *arguments])


def workflow(tmp_path: Path, *arguments: str) -> int:
    """Run `workflow` against the simulated provider with no tick delay."""
    return run(
        tmp_path,
        "workflow",
        *arguments,
        "--provider",
        "in-memory",
        "--interval",
        "0",
        "--artifacts",
        str(tmp_path / "artifacts"),
    )


def inspect(tmp_path: Path) -> EngineeringManager:
    """Open the database the CLI wrote, for assertions."""
    return EngineeringManager(Store(tmp_path / "em.db"))


@pytest.fixture
def project(tmp_path: Path, capsys: pytest.CaptureFixture) -> Path:
    run(tmp_path, "project", "add", "demo", "Demo", "--path", str(tmp_path))
    capsys.readouterr()
    return tmp_path


def test_workflow_drives_a_goal_to_a_completed_plan(
    project: Path, capsys: pytest.CaptureFixture
) -> None:
    exit_code = workflow(project, "demo", "Ship it", "--yes", "--accept")

    assert exit_code == 0
    manager = inspect(project)
    try:
        plan = manager.list_plans(project_id="demo")[0]
        tasks = manager.plan_tasks(plan.plan_id)
        assert plan.status is PlanStatus.COMPLETED
        assert tasks
        assert all(task.status is TaskStatus.DONE for task in tasks)
    finally:
        manager.close()


def test_workflow_executes_dependent_waves_in_order(
    project: Path, capsys: pytest.CaptureFixture
) -> None:
    """The chain only finishes if acceptance is interleaved with execution."""
    workflow(project, "demo", "Ship it", "--yes", "--accept")

    manager = inspect(project)
    try:
        plan = manager.list_plans(project_id="demo")[0]
        sessions = [
            session
            for task in manager.plan_tasks(plan.plan_id)
            for session in manager.list_sessions(task_id=task.task_id)
        ]
        assert len(sessions) == 3
    finally:
        manager.close()


def test_workflow_registers_the_account_it_needs(
    project: Path, capsys: pytest.CaptureFixture
) -> None:
    workflow(project, "demo", "Ship it", "--yes", "--accept", "--account", "mine")

    output = capsys.readouterr().out
    assert "Registered account in-memory/mine." in output
    manager = inspect(project)
    try:
        assert [account.account_id for account in manager.list_accounts()] == ["mine"]
    finally:
        manager.close()


def test_workflow_reuses_an_account_that_already_exists(
    project: Path, capsys: pytest.CaptureFixture
) -> None:
    run(project, "account", "add", "in-memory", "mine")
    capsys.readouterr()

    workflow(project, "demo", "Ship it", "--yes", "--accept", "--account", "mine")

    assert "Registered account" not in capsys.readouterr().out


def test_workflow_writes_a_report_artifact(
    project: Path, capsys: pytest.CaptureFixture
) -> None:
    workflow(project, "demo", "Ship it", "--yes", "--accept")

    reports = list((project / "artifacts").glob("demo-*.md"))
    assert len(reports) == 1
    assert "# Engineering Report" in reports[0].read_text(encoding="utf-8")


def test_workflow_stops_at_gate_one_without_consent(
    project: Path, capsys: pytest.CaptureFixture
) -> None:
    """Non-interactive stdin declines rather than assuming approval."""
    exit_code = workflow(project, "demo", "Ship it")

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "plan approve" in output
    manager = inspect(project)
    try:
        plan = manager.list_plans(project_id="demo")[0]
        assert plan.status is PlanStatus.DRAFT
        assert not manager.list_sessions()
    finally:
        manager.close()


def test_workflow_stops_at_gate_two_without_consent(
    project: Path, capsys: pytest.CaptureFixture
) -> None:
    exit_code = workflow(project, "demo", "Ship it", "--yes")

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "plan accept" in output
    manager = inspect(project)
    try:
        plan = manager.list_plans(project_id="demo")[0]
        statuses = {task.status for task in manager.plan_tasks(plan.plan_id)}
        assert TaskStatus.NEEDS_REVIEW in statuses
        assert plan.status is PlanStatus.IN_PROGRESS
    finally:
        manager.close()


def test_workflow_requires_a_goal_or_a_plan_to_resume(
    project: Path, capsys: pytest.CaptureFixture
) -> None:
    exit_code = workflow(project, "demo")

    assert exit_code == 1
    assert "--resume" in capsys.readouterr().err


def test_workflow_resumes_an_unfinished_plan(
    project: Path, capsys: pytest.CaptureFixture
) -> None:
    workflow(project, "demo", "Ship it", "--yes", "--accept", "--max-ticks", "1")
    manager = inspect(project)
    try:
        plan = manager.list_plans(project_id="demo")[0]
        assert plan.status is PlanStatus.IN_PROGRESS
    finally:
        manager.close()
    capsys.readouterr()

    exit_code = workflow(
        project, "demo", "--resume", str(plan.plan_id), "--yes", "--accept"
    )

    assert exit_code == 0
    manager = inspect(project)
    try:
        assert manager.get_plan(plan.plan_id).status is PlanStatus.COMPLETED
    finally:
        manager.close()


def test_workflow_resume_reports_the_plan_it_continues(
    project: Path, capsys: pytest.CaptureFixture
) -> None:
    workflow(project, "demo", "Ship it", "--yes", "--accept", "--max-ticks", "1")
    manager = inspect(project)
    try:
        plan = manager.list_plans(project_id="demo")[0]
    finally:
        manager.close()
    capsys.readouterr()

    workflow(project, "demo", "--resume", str(plan.plan_id), "--yes", "--accept")

    assert f"Resuming plan {plan.plan_id}" in capsys.readouterr().out


def test_workflow_resume_rejects_an_unknown_plan(
    project: Path, capsys: pytest.CaptureFixture
) -> None:
    exit_code = workflow(
        project, "demo", "--resume", "00000000-0000-0000-0000-000000000000", "--yes"
    )

    assert exit_code == 1


def test_workflow_honors_the_tick_budget(
    project: Path, capsys: pytest.CaptureFixture
) -> None:
    workflow(project, "demo", "Ship it", "--yes", "--accept", "--max-ticks", "1")

    output = capsys.readouterr().out
    assert "1-tick budget" in output
    assert "--resume" in output


def test_workflow_reports_the_plan_status_it_reached(
    project: Path, capsys: pytest.CaptureFixture
) -> None:
    workflow(project, "demo", "Ship it", "--yes", "--accept")

    assert f"plan is {PlanStatus.COMPLETED.name}" in capsys.readouterr().out

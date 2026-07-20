"""Tests for the ContextAssembler."""

from __future__ import annotations

from pathlib import Path

import pytest

from engineering_manager.domain.plan import Plan
from engineering_manager.domain.project import Project
from engineering_manager.domain.session import Session
from engineering_manager.domain.states import PlanStatus, SessionStatus, TaskStatus
from engineering_manager.domain.task import Task
from engineering_manager.orchestration.context import NO_SUMMARY, ContextAssembler
from engineering_manager.store.store import Store


class Harness:
    """A Store plus helpers for building task histories."""

    def __init__(self, tmp_path: Path) -> None:
        self.store = Store(tmp_path / "em.db")
        self.project = Project(project_id="zenith", name="Zenith", root_path=Path("repo"))
        self.store.add_project(self.project)
        self.assembler = ContextAssembler(self.store)

    def add_task(self, title: str, **kwargs: object) -> Task:
        task = Task(project_id="zenith", title=title, **kwargs)  # type: ignore[arg-type]
        self.store.add_task(task)
        return task

    def add_session(
        self, task: Task, status: SessionStatus, summary: str | None = None
    ) -> Session:
        session = Session(
            task_id=task.task_id,
            project_id="zenith",
            provider_id="in-memory",
            account_id="a",
            summary=summary,
            status=status,
        )
        self.store.add_session(session)
        return session

    def close(self) -> None:
        self.store.close()


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    harness = Harness(tmp_path)
    yield harness
    harness.close()


def test_briefing_includes_project_and_task(harness: Harness) -> None:
    task = harness.add_task("Write the loader", description="Load plugins at startup.")

    brief = harness.assembler.briefing(task, harness.project)

    assert "Project: Zenith (repo)" in brief
    assert "Task: Write the loader\nLoad plugins at startup." in brief


def test_briefing_without_history_has_no_extra_sections(harness: Harness) -> None:
    task = harness.add_task("Write the loader")

    brief = harness.assembler.briefing(task, harness.project)

    assert "Goal:" not in brief
    assert "prerequisite" not in brief
    assert "attempts" not in brief


def test_briefing_includes_plan_goal(harness: Harness) -> None:
    plan = Plan(
        project_id="zenith",
        goal="Ship plugin support",
        description="Everything needed for plugins.",
        status=PlanStatus.IN_PROGRESS,
    )
    harness.store.add_plan(plan)
    task = harness.add_task("Write the loader", plan_id=plan.plan_id)

    brief = harness.assembler.briefing(task, harness.project)

    assert "Goal: Ship plugin support\nEverything needed for plugins." in brief


def test_briefing_includes_completed_dependency_summaries(harness: Harness) -> None:
    dependency = harness.add_task("Design the API", status=TaskStatus.DONE)
    harness.add_session(dependency, SessionStatus.COMPLETED, "API uses explicit registry.")
    task = harness.add_task("Write the loader", depends_on=frozenset({dependency.task_id}))

    brief = harness.assembler.briefing(task, harness.project)

    assert (
        "Completed prerequisite work:\n- Design the API: API uses explicit registry."
        in brief
    )


def test_briefing_uses_latest_completed_session_summary(harness: Harness) -> None:
    dependency = harness.add_task("Design the API", status=TaskStatus.DONE)
    harness.add_session(dependency, SessionStatus.FAILED, "First try broke.")
    harness.add_session(dependency, SessionStatus.COMPLETED, "Second try landed.")
    task = harness.add_task("Write the loader", depends_on=frozenset({dependency.task_id}))

    brief = harness.assembler.briefing(task, harness.project)

    assert "- Design the API: Second try landed." in brief


def test_briefing_marks_missing_dependency_summary(harness: Harness) -> None:
    dependency = harness.add_task("Design the API", status=TaskStatus.DONE)
    task = harness.add_task("Write the loader", depends_on=frozenset({dependency.task_id}))

    brief = harness.assembler.briefing(task, harness.project)

    assert f"- Design the API: {NO_SUMMARY}" in brief


def test_briefing_omits_incomplete_dependencies(harness: Harness) -> None:
    dependency = harness.add_task("Design the API", status=TaskStatus.READY)
    task = harness.add_task("Write the loader", depends_on=frozenset({dependency.task_id}))

    brief = harness.assembler.briefing(task, harness.project)

    assert "prerequisite" not in brief


def test_briefing_includes_previous_failed_attempts(harness: Harness) -> None:
    task = harness.add_task("Write the loader")
    harness.add_session(task, SessionStatus.FAILED, "Tests would not pass.")
    harness.add_session(task, SessionStatus.ABANDONED)

    brief = harness.assembler.briefing(task, harness.project)

    assert (
        "Previous attempts at this task:\n"
        "- attempt 1 (FAILED): Tests would not pass.\n"
        f"- attempt 2 (ABANDONED): {NO_SUMMARY}" in brief
    )


def test_briefing_ignores_completed_sessions_of_the_task_itself(harness: Harness) -> None:
    task = harness.add_task("Write the loader")
    harness.add_session(task, SessionStatus.COMPLETED, "Landed earlier.")

    brief = harness.assembler.briefing(task, harness.project)

    assert "attempts" not in brief


def test_briefing_is_deterministic(harness: Harness) -> None:
    first_dep = harness.add_task("First", status=TaskStatus.DONE)
    second_dep = harness.add_task("Second", status=TaskStatus.DONE)
    task = harness.add_task(
        "Write the loader",
        depends_on=frozenset({first_dep.task_id, second_dep.task_id}),
    )

    assert harness.assembler.briefing(task, harness.project) == harness.assembler.briefing(
        task, harness.project
    )

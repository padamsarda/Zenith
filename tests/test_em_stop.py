"""Tests for run-loop stop conditions."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from engineering_manager.domain.plan import Plan
from engineering_manager.domain.project import Project
from engineering_manager.domain.session import Session
from engineering_manager.domain.states import PlanStatus, SessionStatus, TaskStatus
from engineering_manager.domain.task import Task
from engineering_manager.orchestration.stop import (
    RunForever,
    WhenPlanSettled,
    WhenQuiescent,
)
from engineering_manager.store.store import Store


class Harness:
    """A Store holding one project and one plan, for building task graphs."""

    def __init__(self, tmp_path: Path) -> None:
        self.store = Store(tmp_path / "em.db")
        self.store.add_project(
            Project(project_id="zenith", name="Zenith", root_path=Path("."))
        )
        self.plan = Plan(
            project_id="zenith", goal="Ship it", status=PlanStatus.IN_PROGRESS
        )
        self.store.add_plan(self.plan)

    def add_task(
        self,
        status: TaskStatus,
        *,
        depends_on: tuple[UUID, ...] = (),
        in_plan: bool = True,
    ) -> Task:
        task = Task(
            project_id="zenith",
            title=f"Task {status.name}",
            status=status,
            depends_on=frozenset(depends_on),
            plan_id=self.plan.plan_id if in_plan else None,
        )
        self.store.add_task(task)
        return task

    def add_session(self, task: Task, status: SessionStatus) -> Session:
        session = Session(
            task_id=task.task_id,
            project_id="zenith",
            provider_id="in-memory",
            account_id="default",
            status=status,
        )
        self.store.add_session(session)
        return session


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    return Harness(tmp_path)


def test_run_forever_never_stops(harness: Harness) -> None:
    assert RunForever().should_stop(harness.store) is None


def test_quiescent_stops_when_no_tasks_exist(harness: Harness) -> None:
    reason = WhenQuiescent().should_stop(harness.store)

    assert reason is not None
    assert "every project" in reason


def test_quiescent_keeps_running_while_a_task_is_ready(harness: Harness) -> None:
    harness.add_task(TaskStatus.READY)

    assert WhenQuiescent().should_stop(harness.store) is None


def test_quiescent_keeps_running_while_a_task_is_in_progress(harness: Harness) -> None:
    harness.add_task(TaskStatus.IN_PROGRESS)

    assert WhenQuiescent().should_stop(harness.store) is None


def test_quiescent_stops_when_everything_awaits_review(harness: Harness) -> None:
    harness.add_task(TaskStatus.NEEDS_REVIEW)

    assert WhenQuiescent().should_stop(harness.store) is not None


def test_quiescent_stops_when_a_failed_task_was_declined_by_retry(
    harness: Harness,
) -> None:
    harness.add_task(TaskStatus.FAILED)

    assert WhenQuiescent().should_stop(harness.store) is not None


def test_quiescent_names_the_project_it_was_scoped_to(harness: Harness) -> None:
    reason = WhenQuiescent(project_id="zenith").should_stop(harness.store)

    assert reason is not None
    assert "zenith" in reason


def test_ready_task_blocked_by_review_does_not_count_as_advancing(
    harness: Harness,
) -> None:
    """The bug that made unattended runs spin forever with nothing eligible."""
    blocker = harness.add_task(TaskStatus.NEEDS_REVIEW)
    harness.add_task(TaskStatus.READY, depends_on=(blocker.task_id,))

    assert WhenQuiescent().should_stop(harness.store) is not None


def test_blockage_is_transitive_through_a_ready_dependency(harness: Harness) -> None:
    """A READY task two hops behind a parked one is parked too."""
    blocker = harness.add_task(TaskStatus.NEEDS_REVIEW)
    middle = harness.add_task(TaskStatus.READY, depends_on=(blocker.task_id,))
    harness.add_task(TaskStatus.READY, depends_on=(middle.task_id,))

    assert WhenQuiescent().should_stop(harness.store) is not None


def test_ready_task_behind_running_work_still_counts_as_advancing(
    harness: Harness,
) -> None:
    running = harness.add_task(TaskStatus.IN_PROGRESS)
    harness.add_task(TaskStatus.READY, depends_on=(running.task_id,))

    assert WhenQuiescent().should_stop(harness.store) is None


def test_ready_task_behind_done_work_counts_as_advancing(harness: Harness) -> None:
    finished = harness.add_task(TaskStatus.DONE)
    harness.add_task(TaskStatus.READY, depends_on=(finished.task_id,))

    assert WhenQuiescent().should_stop(harness.store) is None


def test_ready_task_behind_a_cancelled_dependency_is_parked(harness: Harness) -> None:
    cancelled = harness.add_task(TaskStatus.CANCELLED)
    harness.add_task(TaskStatus.READY, depends_on=(cancelled.task_id,))

    assert WhenQuiescent().should_stop(harness.store) is not None


def test_ready_task_with_an_unknown_dependency_is_parked(harness: Harness) -> None:
    harness.add_task(TaskStatus.READY, depends_on=(UUID(int=7),))

    assert WhenQuiescent().should_stop(harness.store) is not None


def test_quiescent_keeps_running_while_a_session_is_open(harness: Harness) -> None:
    """An open session must never be abandoned, whatever its task says."""
    task = harness.add_task(TaskStatus.NEEDS_REVIEW)
    harness.add_session(task, SessionStatus.ACTIVE)

    assert WhenQuiescent().should_stop(harness.store) is None


def test_quiescent_keeps_running_while_a_session_waits_to_resume(
    harness: Harness,
) -> None:
    task = harness.add_task(TaskStatus.NEEDS_REVIEW)
    harness.add_session(task, SessionStatus.INTERRUPTED)

    assert WhenQuiescent().should_stop(harness.store) is None


def test_quiescent_ignores_a_finished_session(harness: Harness) -> None:
    task = harness.add_task(TaskStatus.NEEDS_REVIEW)
    harness.add_session(task, SessionStatus.COMPLETED)

    assert WhenQuiescent().should_stop(harness.store) is not None


def test_plan_settled_keeps_running_while_its_work_advances(harness: Harness) -> None:
    harness.add_task(TaskStatus.READY)

    assert WhenPlanSettled(harness.plan.plan_id).should_stop(harness.store) is None


def test_plan_settled_stops_and_reports_the_plan_status(harness: Harness) -> None:
    harness.add_task(TaskStatus.NEEDS_REVIEW)

    reason = WhenPlanSettled(harness.plan.plan_id).should_stop(harness.store)

    assert reason is not None
    assert str(harness.plan.plan_id) in reason
    assert PlanStatus.IN_PROGRESS.name in reason


def test_plan_settled_ignores_work_outside_the_plan(harness: Harness) -> None:
    harness.add_task(TaskStatus.NEEDS_REVIEW)
    harness.add_task(TaskStatus.READY, in_plan=False)

    assert WhenPlanSettled(harness.plan.plan_id).should_stop(harness.store) is not None


def test_plan_settled_resolves_dependencies_outside_the_plan(harness: Harness) -> None:
    """A dependency in another plan still decides whether this one can move."""
    outside = harness.add_task(TaskStatus.IN_PROGRESS, in_plan=False)
    harness.add_task(TaskStatus.READY, depends_on=(outside.task_id,))

    assert WhenPlanSettled(harness.plan.plan_id).should_stop(harness.store) is None

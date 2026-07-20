"""Tests for the PlanCoordinator."""

from __future__ import annotations

from pathlib import Path

import pytest

from engineering_manager.domain.project import Project
from engineering_manager.domain.states import PlanStatus, TaskStatus
from engineering_manager.domain.task import Task
from engineering_manager.events import PlanAdded, PlanStatusChanged, TaskStatusChanged
from engineering_manager.exceptions import (
    DomainValidationError,
    OrchestrationError,
    ProjectNotFoundError,
)
from engineering_manager.orchestration.plans import PlanCoordinator
from engineering_manager.store.store import Store
from shared.events.bus import EventBus
from shared.events.event import Event


class Harness:
    """A Store + EventBus + PlanCoordinator wired together for tests."""

    def __init__(self, tmp_path: Path) -> None:
        self.store = Store(tmp_path / "em.db")
        self.bus = EventBus()
        self.seen: list[Event] = []
        for event_type in (PlanAdded, PlanStatusChanged, TaskStatusChanged):
            self.bus.subscribe(event_type, self.seen.append)
        self.coordinator = PlanCoordinator(self.store, bus=self.bus)
        self.store.add_project(
            Project(project_id="zenith", name="Zenith", root_path=Path("."))
        )

    def add_task(self, plan_id, status: TaskStatus = TaskStatus.DRAFT) -> Task:
        task = Task(project_id="zenith", title="Work", plan_id=plan_id, status=status)
        self.store.add_task(task)
        return task

    def close(self) -> None:
        self.store.close()


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    harness = Harness(tmp_path)
    yield harness
    harness.close()


def test_add_plan_persists_and_publishes(harness: Harness) -> None:
    plan = harness.coordinator.add_plan("zenith", "Ship plugins")

    assert harness.store.get_plan(plan.plan_id).goal == "Ship plugins"
    assert [event.name for event in harness.seen] == ["PlanAdded"]
    assert [entry.name for entry in harness.store.list_events()] == ["PlanAdded"]


def test_add_plan_requires_existing_project(harness: Harness) -> None:
    with pytest.raises(ProjectNotFoundError):
        harness.coordinator.add_plan("missing", "Ship plugins")


def test_add_plan_with_blank_goal_raises(harness: Harness) -> None:
    with pytest.raises(DomainValidationError):
        harness.coordinator.add_plan("zenith", "   ")


def test_approve_plan_moves_plan_and_draft_tasks(harness: Harness) -> None:
    plan = harness.coordinator.add_plan("zenith", "Ship plugins")
    draft = harness.add_task(plan.plan_id)
    ready = harness.add_task(plan.plan_id, status=TaskStatus.READY)

    harness.coordinator.approve_plan(plan.plan_id)

    assert harness.store.get_plan(plan.plan_id).status is PlanStatus.IN_PROGRESS
    assert harness.store.get_task(draft.task_id).status is TaskStatus.READY
    assert harness.store.get_task(ready.task_id).status is TaskStatus.READY


def test_approve_plan_publishes_plan_and_task_changes(harness: Harness) -> None:
    plan = harness.coordinator.add_plan("zenith", "Ship plugins")
    harness.add_task(plan.plan_id)

    harness.coordinator.approve_plan(plan.plan_id)

    assert [event.name for event in harness.seen] == [
        "PlanAdded",
        "PlanStatusChanged",
        "TaskStatusChanged",
    ]


def test_approve_empty_plan_raises(harness: Harness) -> None:
    plan = harness.coordinator.add_plan("zenith", "Ship plugins")

    with pytest.raises(OrchestrationError):
        harness.coordinator.approve_plan(plan.plan_id)


def test_approve_plan_twice_raises(harness: Harness) -> None:
    plan = harness.coordinator.add_plan("zenith", "Ship plugins")
    harness.add_task(plan.plan_id)
    harness.coordinator.approve_plan(plan.plan_id)

    with pytest.raises(DomainValidationError):
        harness.coordinator.approve_plan(plan.plan_id)


def test_cancel_plan_cancels_open_tasks(harness: Harness) -> None:
    plan = harness.coordinator.add_plan("zenith", "Ship plugins")
    open_task = harness.add_task(plan.plan_id)
    done_task = harness.add_task(plan.plan_id, status=TaskStatus.DONE)

    harness.coordinator.cancel_plan(plan.plan_id)

    assert harness.store.get_plan(plan.plan_id).status is PlanStatus.CANCELLED
    assert harness.store.get_task(open_task.task_id).status is TaskStatus.CANCELLED
    assert harness.store.get_task(done_task.task_id).status is TaskStatus.DONE


def test_note_task_terminal_completes_plan_when_all_tasks_terminal(
    harness: Harness,
) -> None:
    plan = harness.coordinator.add_plan("zenith", "Ship plugins")
    task = harness.add_task(plan.plan_id)
    harness.coordinator.approve_plan(plan.plan_id)
    stored = harness.store.get_task(task.task_id)
    for status in (TaskStatus.IN_PROGRESS, TaskStatus.NEEDS_REVIEW, TaskStatus.DONE):
        stored.transition_to(status)
    harness.store.update_task(stored)

    completed = harness.coordinator.note_task_terminal(stored)

    assert completed is not None
    assert harness.store.get_plan(plan.plan_id).status is PlanStatus.COMPLETED


def test_note_task_terminal_waits_for_open_tasks(harness: Harness) -> None:
    plan = harness.coordinator.add_plan("zenith", "Ship plugins")
    done = harness.add_task(plan.plan_id, status=TaskStatus.DONE)
    harness.add_task(plan.plan_id, status=TaskStatus.READY)
    plan_stored = harness.store.get_plan(plan.plan_id)
    plan_stored.transition_to(PlanStatus.IN_PROGRESS)
    harness.store.update_plan(plan_stored)

    assert harness.coordinator.note_task_terminal(done) is None
    assert harness.store.get_plan(plan.plan_id).status is PlanStatus.IN_PROGRESS


def test_note_task_terminal_ignores_planless_tasks(harness: Harness) -> None:
    task = Task(project_id="zenith", title="Standalone", status=TaskStatus.DONE)
    harness.store.add_task(task)

    assert harness.coordinator.note_task_terminal(task) is None


def test_note_task_terminal_ignores_draft_plans(harness: Harness) -> None:
    plan = harness.coordinator.add_plan("zenith", "Ship plugins")
    done = harness.add_task(plan.plan_id, status=TaskStatus.DONE)

    assert harness.coordinator.note_task_terminal(done) is None
    assert harness.store.get_plan(plan.plan_id).status is PlanStatus.DRAFT

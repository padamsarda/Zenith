"""Tests for the Task domain entity."""

from __future__ import annotations

import dataclasses
from uuid import UUID, uuid4

import pytest

from engineering_manager.domain.states import TaskStatus
from engineering_manager.domain.task import Task
from engineering_manager.exceptions import DomainValidationError


def test_task_defaults() -> None:
    task = Task(project_id="zenith", title="Write docs")

    assert task.status is TaskStatus.DRAFT
    assert task.priority == 0
    assert task.depends_on == frozenset()
    assert isinstance(task.task_id, UUID)
    assert task.created_at.tzinfo is not None


def test_two_tasks_get_distinct_ids() -> None:
    first = Task(project_id="zenith", title="A")
    second = Task(project_id="zenith", title="B")

    assert first.task_id != second.task_id


def test_task_fields_are_frozen() -> None:
    task = Task(project_id="zenith", title="Write docs")

    with pytest.raises(dataclasses.FrozenInstanceError):
        task.title = "Other"  # type: ignore[misc]


def test_task_status_cannot_be_assigned_directly() -> None:
    task = Task(project_id="zenith", title="Write docs")

    with pytest.raises(dataclasses.FrozenInstanceError):
        task.status = TaskStatus.READY  # type: ignore[misc]


def test_task_walks_the_happy_path() -> None:
    task = Task(project_id="zenith", title="Write docs")

    task.transition_to(TaskStatus.READY)
    task.transition_to(TaskStatus.IN_PROGRESS)
    task.transition_to(TaskStatus.NEEDS_REVIEW)
    task.transition_to(TaskStatus.DONE)

    assert task.status is TaskStatus.DONE


def test_task_invalid_transition_raises_and_preserves_status() -> None:
    task = Task(project_id="zenith", title="Write docs")

    with pytest.raises(DomainValidationError):
        task.transition_to(TaskStatus.DONE)
    assert task.status is TaskStatus.DRAFT


def test_task_dependencies_are_stored_as_given() -> None:
    dependency_ids = frozenset({uuid4(), uuid4()})
    task = Task(project_id="zenith", title="Write docs", depends_on=dependency_ids)

    assert task.depends_on == dependency_ids

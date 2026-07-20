"""Tests for dependency-graph analysis."""

from __future__ import annotations

from uuid import uuid4

import pytest

from engineering_manager.domain.states import TaskStatus
from engineering_manager.domain.task import Task
from engineering_manager.exceptions import DomainValidationError
from engineering_manager.orchestration.graph import (
    Blockage,
    blockages,
    execution_waves,
    would_create_cycle,
)


def make_task(
    title: str,
    *,
    depends_on: frozenset = frozenset(),
    priority: int = 0,
    status: TaskStatus = TaskStatus.READY,
) -> Task:
    return Task(
        project_id="zenith",
        title=title,
        priority=priority,
        depends_on=depends_on,
        status=status,
    )


def by_id(*tasks: Task) -> dict:
    return {task.task_id: task for task in tasks}


def test_would_create_cycle_detects_direct_cycle() -> None:
    first = make_task("first")
    second = make_task("second", depends_on=frozenset({first.task_id}))

    assert would_create_cycle(by_id(first, second), first.task_id, second.task_id)


def test_would_create_cycle_detects_transitive_cycle() -> None:
    first = make_task("first")
    second = make_task("second", depends_on=frozenset({first.task_id}))
    third = make_task("third", depends_on=frozenset({second.task_id}))

    assert would_create_cycle(by_id(first, second, third), first.task_id, third.task_id)


def test_would_create_cycle_allows_independent_edge() -> None:
    first = make_task("first")
    second = make_task("second")

    assert not would_create_cycle(by_id(first, second), second.task_id, first.task_id)


def test_would_create_cycle_allows_diamond() -> None:
    root = make_task("root")
    left = make_task("left", depends_on=frozenset({root.task_id}))
    right = make_task("right", depends_on=frozenset({root.task_id}))

    assert not would_create_cycle(by_id(root, left, right), left.task_id, right.task_id)


def test_execution_waves_orders_dependencies_before_dependents() -> None:
    first = make_task("first")
    second = make_task("second", depends_on=frozenset({first.task_id}))
    third = make_task("third", depends_on=frozenset({second.task_id}))

    waves = execution_waves([third, first, second])

    assert [[task.title for task in wave] for wave in waves] == [
        ["first"],
        ["second"],
        ["third"],
    ]


def test_execution_waves_groups_parallel_tasks() -> None:
    root = make_task("root")
    left = make_task("left", depends_on=frozenset({root.task_id}), priority=1)
    right = make_task("right", depends_on=frozenset({root.task_id}), priority=5)

    waves = execution_waves([left, right, root])

    assert [[task.title for task in wave] for wave in waves] == [
        ["root"],
        ["right", "left"],
    ]


def test_execution_waves_treats_external_dependencies_as_satisfied() -> None:
    outside = uuid4()
    task = make_task("task", depends_on=frozenset({outside}))

    waves = execution_waves([task])

    assert [[member.title for member in wave] for wave in waves] == [["task"]]


def test_execution_waves_raises_on_cycle() -> None:
    first_id, second_id = uuid4(), uuid4()
    first = Task(
        project_id="zenith",
        title="first",
        task_id=first_id,
        depends_on=frozenset({second_id}),
    )
    second = Task(
        project_id="zenith",
        title="second",
        task_id=second_id,
        depends_on=frozenset({first_id}),
    )

    with pytest.raises(DomainValidationError):
        execution_waves([first, second])


def test_blockages_reports_unmet_dependencies() -> None:
    dependency = make_task("dependency")
    dependent = make_task("dependent", depends_on=frozenset({dependency.task_id}))

    found = blockages([dependency, dependent])

    assert found == [
        Blockage(task_id=dependent.task_id, unmet=(dependency.task_id,), impossible=())
    ]


def test_blockages_reports_cancelled_dependency_as_impossible() -> None:
    dependency = make_task("dependency", status=TaskStatus.CANCELLED)
    dependent = make_task("dependent", depends_on=frozenset({dependency.task_id}))

    found = blockages([dependency, dependent])

    assert found == [
        Blockage(task_id=dependent.task_id, unmet=(), impossible=(dependency.task_id,))
    ]


def test_blockages_ignores_satisfied_and_terminal_tasks() -> None:
    done_dependency = make_task("done", status=TaskStatus.DONE)
    satisfied = make_task("satisfied", depends_on=frozenset({done_dependency.task_id}))
    cancelled = make_task(
        "cancelled", depends_on=frozenset({uuid4()}), status=TaskStatus.CANCELLED
    )

    assert blockages([done_dependency, satisfied, cancelled]) == []


def test_blockages_reports_missing_dependency_as_impossible() -> None:
    missing = uuid4()
    dependent = make_task("dependent", depends_on=frozenset({missing}))

    found = blockages([dependent])

    assert found == [Blockage(task_id=dependent.task_id, unmet=(), impossible=(missing,))]

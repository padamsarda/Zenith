"""Dependency-graph analysis over tasks.

The task graph is the execution engine's answer to "what order does
work happen in, and what can run in parallel?": dependencies impose
order, everything unordered may run concurrently, and account
availability — not the graph — bounds actual parallelism. This module
keeps that analysis pure: plain functions over `Task` values, no store
access, no mutation, deterministic output for identical input.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from engineering_manager.domain.states import TERMINAL_TASK_STATUSES, TaskStatus
from engineering_manager.domain.task import Task
from engineering_manager.exceptions import DomainValidationError


@dataclass(frozen=True)
class Blockage:
    """Why a task cannot dispatch yet — or ever.

    `unmet` holds dependencies that are not `DONE` but still could be;
    `impossible` holds dependencies that can never be `DONE` (they were
    cancelled), which means the task will never dispatch unless a human
    intervenes.
    """

    task_id: UUID
    unmet: tuple[UUID, ...]
    impossible: tuple[UUID, ...]


def would_create_cycle(
    tasks_by_id: Mapping[UUID, Task], task_id: UUID, dependency_id: UUID
) -> bool:
    """Return True if making `task_id` depend on `dependency_id` creates a cycle.

    A cycle appears exactly when `dependency_id` already depends —
    directly or transitively — on `task_id`. `tasks_by_id` must contain
    every task reachable through dependencies (in practice: all tasks
    of the project).
    """
    stack = [dependency_id]
    visited: set[UUID] = set()
    while stack:
        current = stack.pop()
        if current == task_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        task = tasks_by_id.get(current)
        if task is not None:
            stack.extend(task.depends_on)
    return False


def execution_waves(tasks: Sequence[Task]) -> list[list[Task]]:
    """Group `tasks` into dependency waves: wave N needs only waves < N.

    Tasks within one wave have no ordering constraints between them and
    may execute in parallel. Dependencies on tasks outside `tasks` are
    treated as satisfied, so a plan's waves can be computed from the
    plan's tasks alone. Within a wave, tasks are ordered the way the
    dispatcher would pick them: priority descending, then oldest first.

    Raises:
        DomainValidationError: If the tasks contain a dependency cycle.
            Creation-time and addition-time checks make this impossible
            through the facade; the guard protects against a corrupted
            store.
    """
    members = {task.task_id: task for task in tasks}
    remaining = dict(members)
    satisfied: set[UUID] = set()
    waves: list[list[Task]] = []
    while remaining:
        wave = [
            task
            for task in remaining.values()
            if all(
                dependency in satisfied or dependency not in members
                for dependency in task.depends_on
            )
        ]
        if not wave:
            raise DomainValidationError(
                "Tasks contain a dependency cycle; the store is inconsistent."
            )
        wave.sort(key=lambda task: (-task.priority, task.created_at, str(task.task_id)))
        for task in wave:
            del remaining[task.task_id]
            satisfied.add(task.task_id)
        waves.append(wave)
    return waves


def blockages(tasks: Sequence[Task]) -> list[Blockage]:
    """Report every non-terminal task whose dependencies hold it back.

    `tasks` must include the dependencies of its members (in practice:
    all tasks of a project — dependencies never cross projects). A
    dependency absent from `tasks` is reported as impossible rather
    than guessed at. Output order follows input order.
    """
    by_id = {task.task_id: task for task in tasks}
    found: list[Blockage] = []
    for task in tasks:
        if task.status in TERMINAL_TASK_STATUSES or not task.depends_on:
            continue
        unmet: list[UUID] = []
        impossible: list[UUID] = []
        for dependency_id in task.depends_on:
            dependency = by_id.get(dependency_id)
            if dependency is None or dependency.status is TaskStatus.CANCELLED:
                impossible.append(dependency_id)
            elif dependency.status is not TaskStatus.DONE:
                unmet.append(dependency_id)
        if unmet or impossible:
            found.append(
                Blockage(
                    task_id=task.task_id,
                    unmet=tuple(sorted(unmet, key=str)),
                    impossible=tuple(sorted(impossible, key=str)),
                )
            )
    return found

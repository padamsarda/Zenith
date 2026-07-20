"""Lifecycle state definitions for the Engineering Manager domain."""

from __future__ import annotations

from enum import Enum, auto


class ProjectStatus(Enum):
    """Represents the lifecycle state of a managed Project.

    `ACTIVE <-> PAUSED`, with `ARCHIVED` reachable from either.
    `ARCHIVED` is terminal — see `TERMINAL_PROJECT_STATUSES`.
    """

    ACTIVE = auto()
    PAUSED = auto()
    ARCHIVED = auto()


class PlanStatus(Enum):
    """Represents the lifecycle state of a Plan.

    `DRAFT -> IN_PROGRESS -> COMPLETED`, with `CANCELLED` reachable from
    any non-terminal state. `DRAFT -> IN_PROGRESS` is the bulk form of
    human approval gate one: approving a plan approves its DRAFT tasks.
    `COMPLETED` is reached automatically when every task in the plan is
    terminal. `COMPLETED` and `CANCELLED` are terminal — see
    `TERMINAL_PLAN_STATUSES`.
    """

    DRAFT = auto()
    IN_PROGRESS = auto()
    COMPLETED = auto()
    CANCELLED = auto()


class TaskStatus(Enum):
    """Represents the lifecycle state of a Task.

    `DRAFT -> READY -> IN_PROGRESS -> NEEDS_REVIEW -> DONE`, with
    `FAILED` reachable from `IN_PROGRESS` and `CANCELLED` reachable from
    any non-terminal state. The two human approval gates are
    `DRAFT -> READY` (approve the task for execution) and
    `NEEDS_REVIEW -> DONE` (accept the work). `FAILED`, `NEEDS_REVIEW`,
    and `IN_PROGRESS` can return to `READY` (retry / rework / abandoned
    session). `DONE` and `CANCELLED` are terminal — see
    `TERMINAL_TASK_STATUSES`.
    """

    DRAFT = auto()
    READY = auto()
    IN_PROGRESS = auto()
    NEEDS_REVIEW = auto()
    DONE = auto()
    FAILED = auto()
    CANCELLED = auto()


class SessionStatus(Enum):
    """Represents the lifecycle state of a work Session.

    `ACTIVE <-> INTERRUPTED`, ending in `COMPLETED`, `FAILED`, or
    `ABANDONED` — all terminal, see `TERMINAL_SESSION_STATUSES`.
    `INTERRUPTED` exists because providers impose session limits: an
    interrupted session keeps its provider-side reference so it can be
    resumed later rather than started over.
    """

    ACTIVE = auto()
    INTERRUPTED = auto()
    COMPLETED = auto()
    FAILED = auto()
    ABANDONED = auto()


TERMINAL_PROJECT_STATUSES: frozenset[ProjectStatus] = frozenset({ProjectStatus.ARCHIVED})

TERMINAL_PLAN_STATUSES: frozenset[PlanStatus] = frozenset(
    {PlanStatus.COMPLETED, PlanStatus.CANCELLED}
)

TERMINAL_TASK_STATUSES: frozenset[TaskStatus] = frozenset(
    {TaskStatus.DONE, TaskStatus.CANCELLED}
)

TERMINAL_SESSION_STATUSES: frozenset[SessionStatus] = frozenset(
    {SessionStatus.COMPLETED, SessionStatus.FAILED, SessionStatus.ABANDONED}
)

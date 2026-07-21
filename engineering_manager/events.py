"""Concrete events emitted by the Engineering Manager.

All are `shared.events.event.Event` subclasses emitted by the
`EngineeringManager` facade with `source="engineering_manager"`, and
every one of them is also appended to the store's persistent event log —
the in-process bus serves live subscribers, the log serves audit and
history. Status-change events carry `from`/`to` in the payload rather
than having one event type per transition; subscribers filter on the
payload.
"""

from __future__ import annotations

from dataclasses import dataclass

from shared.events.event import Event


@dataclass(frozen=True)
class ProjectAdded(Event):
    """Emitted when a project is placed under management.

    Payload: `project_id`, `name`.
    """


@dataclass(frozen=True)
class ProjectStatusChanged(Event):
    """Emitted when a project's status changes.

    Payload: `project_id`, `from`, `to`.
    """


@dataclass(frozen=True)
class PlanAdded(Event):
    """Emitted when a goal is recorded as a plan.

    Payload: `plan_id`, `project_id`, `goal`.
    """


@dataclass(frozen=True)
class PlanStatusChanged(Event):
    """Emitted when a plan's status changes — approval, automatic
    completion, or cancellation.

    Payload: `plan_id`, `project_id`, `from`, `to`.
    """


@dataclass(frozen=True)
class PlanDecomposed(Event):
    """Emitted when a planning session finishes decomposing a goal into
    tasks written under a plan.

    Payload: `plan_id`, `project_id`, `task_count`.
    """


@dataclass(frozen=True)
class TaskAdded(Event):
    """Emitted when a task is created.

    Payload: `task_id`, `project_id`, `title`.
    """


@dataclass(frozen=True)
class TaskStatusChanged(Event):
    """Emitted when a task's status changes, whatever the cause —
    approval, dispatch, review, retry, or cancellation.

    Payload: `task_id`, `project_id`, `from`, `to`.
    """


@dataclass(frozen=True)
class TaskDependencyAdded(Event):
    """Emitted when an existing task gains a new dependency — the plan
    graph evolving as work is discovered.

    Payload: `task_id`, `depends_on`, `project_id`.
    """


@dataclass(frozen=True)
class SessionStarted(Event):
    """Emitted when a provider session is started for a task.

    Payload: `session_id`, `task_id`, `project_id`, `provider_id`,
    `account_id`.
    """


@dataclass(frozen=True)
class SessionStatusChanged(Event):
    """Emitted when a session's status changes — interruption, resume,
    completion, failure, or abandonment.

    Payload: `session_id`, `task_id`, `from`, `to`.
    """


@dataclass(frozen=True)
class AttentionRequired(Event):
    """Emitted when execution has hit something only a human can
    resolve: a session awaiting input, or a task whose automatic
    retries are exhausted.

    Payload: `kind` (`"session_awaiting_input"` or
    `"task_retries_exhausted"`), the relevant `task_id` / `session_id`,
    and `detail`.
    """


@dataclass(frozen=True)
class AccountAdded(Event):
    """Emitted when a provider account is registered as an execution
    resource.

    Payload: `provider_id`, `account_id`.
    """


@dataclass(frozen=True)
class AccountRemoved(Event):
    """Emitted when a provider account is removed from the pool.

    Payload: `provider_id`, `account_id`.
    """

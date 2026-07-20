"""Task: a unit of engineering work within a managed project."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from engineering_manager.domain.states import TaskStatus
from engineering_manager.domain.validation import (
    validate_dependency_addition,
    validate_task_status_transition,
)
from shared.utils.time_utils import utc_now
from shared.utils.uuid_utils import generate_id


@dataclass(frozen=True)
class Task:
    """A single unit of engineering work the manager can dispatch.

    `depends_on` holds the IDs of tasks that must be `DONE` before this
    one is eligible for dispatch. `priority` breaks ties among eligible
    tasks — higher numbers are dispatched first. `plan_id`, when set,
    ties the task to the `Plan` whose goal it serves; a standalone task
    has none. Every field is fixed at creation except `status` (which
    may only change through `transition_to`) and `depends_on` (which may
    only grow, through `add_dependency`, while the task is still
    schedulable). Construction does not validate; that happens at the
    framework boundary, in
    `engineering_manager.domain.validation.validate_task`.
    """

    project_id: str
    title: str
    description: str | None = None
    priority: int = 0
    depends_on: frozenset[UUID] = field(default_factory=frozenset)
    plan_id: UUID | None = None
    task_id: UUID = field(default_factory=generate_id)
    created_at: datetime = field(default_factory=utc_now)
    status: TaskStatus = TaskStatus.DRAFT

    def transition_to(self, new_status: TaskStatus) -> None:
        """Move this task to `new_status`.

        Raises:
            DomainValidationError: If the transition from the current
                status to `new_status` is not permitted.
        """
        validate_task_status_transition(self.status, new_status)
        object.__setattr__(self, "status", new_status)

    def add_dependency(self, dependency_id: UUID) -> None:
        """Require `dependency_id` to be DONE before this task may run.

        This is how the plan graph evolves when new information is
        discovered: insert a new task, then make existing work depend on
        it. Whether the dependency exists, shares this task's project,
        and introduces no cycle is checked by the facade before calling.

        Raises:
            DomainValidationError: If the ID is malformed, is this task
                itself, is already a dependency, or the task is no
                longer in a status where predecessors may change.
        """
        validate_dependency_addition(self, dependency_id)
        object.__setattr__(self, "depends_on", self.depends_on | {dependency_id})

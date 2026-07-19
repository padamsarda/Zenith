"""Task: a unit of engineering work within a managed project."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from engineering_manager.domain.states import TaskStatus
from engineering_manager.domain.validation import validate_task_status_transition
from shared.utils.time_utils import utc_now
from shared.utils.uuid_utils import generate_id


@dataclass(frozen=True)
class Task:
    """A single unit of engineering work the manager can dispatch.

    `depends_on` holds the IDs of tasks that must be `DONE` before this
    one is eligible for dispatch. `priority` breaks ties among eligible
    tasks — higher numbers are dispatched first. Every field is fixed at
    creation except `status`, which may only change through
    `transition_to`. Construction does not validate; that happens at the
    framework boundary, in
    `engineering_manager.domain.validation.validate_task`.
    """

    project_id: str
    title: str
    description: str | None = None
    priority: int = 0
    depends_on: frozenset[UUID] = field(default_factory=frozenset)
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

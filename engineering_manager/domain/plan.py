"""Plan: a high-level engineering goal decomposed into a task graph."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from engineering_manager.domain.states import PlanStatus
from engineering_manager.domain.validation import validate_plan_status_transition
from shared.utils.time_utils import utc_now
from shared.utils.uuid_utils import generate_id


@dataclass(frozen=True)
class Plan:
    """A goal-level unit of work: one objective, executed as many tasks.

    A plan is how a high-level engineering goal becomes executable work:
    the goal is stated once here, decomposed into tasks that reference
    it via `Task.plan_id`, and approved as a whole — `DRAFT ->
    IN_PROGRESS` is the bulk form of human approval gate one. Tasks may
    be added to an `IN_PROGRESS` plan as new work is discovered; the
    plan completes only when every one of its tasks is terminal. Every
    field is fixed at creation except `status`, which may only change
    through `transition_to`. Construction does not validate; that
    happens at the framework boundary, in
    `engineering_manager.domain.validation.validate_plan`.
    """

    project_id: str
    goal: str
    description: str | None = None
    plan_id: UUID = field(default_factory=generate_id)
    created_at: datetime = field(default_factory=utc_now)
    status: PlanStatus = PlanStatus.DRAFT

    def transition_to(self, new_status: PlanStatus) -> None:
        """Move this plan to `new_status`.

        Raises:
            DomainValidationError: If the transition from the current
                status to `new_status` is not permitted.
        """
        validate_plan_status_transition(self.status, new_status)
        object.__setattr__(self, "status", new_status)

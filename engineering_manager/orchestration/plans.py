"""PlanCoordinator: drives a plan and its tasks through their lifecycle.

A plan is how a high-level goal becomes executable work: the goal is
recorded once, decomposed into tasks, and approved as a whole —
`approve_plan` is the bulk form of human approval gate one, moving the
plan to IN_PROGRESS and every DRAFT task in it to READY. From there the
tasks execute individually; the coordinator's remaining job is closing
the loop, completing the plan automatically once its last task reaches
a terminal status. Like the dispatcher, every state change is persisted
and announced on both the event log and the bus.
"""

from __future__ import annotations

import logging
from uuid import UUID

from engineering_manager.domain.plan import Plan
from engineering_manager.domain.states import (
    TERMINAL_TASK_STATUSES,
    PlanStatus,
    TaskStatus,
)
from engineering_manager.domain.task import Task
from engineering_manager.domain.validation import validate_plan
from engineering_manager.events import PlanAdded, PlanStatusChanged, TaskStatusChanged
from engineering_manager.exceptions import OrchestrationError
from engineering_manager.store.store import Store
from shared.events.bus import EventBus
from shared.events.event import Event

DEFAULT_LOGGER_NAME = "zenith.em"
SOURCE = "engineering_manager"


class PlanCoordinator:
    """Owns plan lifecycle operations on behalf of the facade."""

    def __init__(
        self,
        store: Store,
        *,
        bus: EventBus | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._store = store
        self._bus = bus or EventBus()
        self._logger = logger or logging.getLogger(DEFAULT_LOGGER_NAME)

    def add_plan(self, project_id: str, goal: str, description: str | None = None) -> Plan:
        """Record a high-level goal as a plan in DRAFT.

        Raises:
            ProjectNotFoundError: If `project_id` is not managed.
            DomainValidationError: If the fields are invalid.
        """
        self._store.get_project(project_id)
        plan = Plan(project_id=project_id, goal=goal, description=description)
        validate_plan(plan)
        self._store.add_plan(plan)
        self._publish(
            PlanAdded(
                source=SOURCE,
                payload={
                    "plan_id": str(plan.plan_id),
                    "project_id": project_id,
                    "goal": goal,
                },
            )
        )
        return plan

    def approve_plan(self, plan_id: UUID) -> Plan:
        """Approve a DRAFT plan: gate one for the plan and its DRAFT tasks.

        Raises:
            PlanNotFoundError: If `plan_id` is not in the store.
            OrchestrationError: If the plan has no tasks — a goal must
                be decomposed before it can execute.
            DomainValidationError: If the plan is not DRAFT.
        """
        plan = self._store.get_plan(plan_id)
        tasks = self._store.list_tasks(plan_id=plan_id)
        if not tasks:
            raise OrchestrationError(
                f"Plan {plan_id} has no tasks; decompose the goal into tasks "
                "before approving."
            )
        self._transition_plan(plan, PlanStatus.IN_PROGRESS)
        for task in tasks:
            if task.status is TaskStatus.DRAFT:
                self._transition_task(task, TaskStatus.READY)
        self._logger.info(
            "Plan %s approved with %d task(s).", plan_id, len(tasks)
        )
        return plan

    def accept_plan(self, plan_id: UUID) -> Plan:
        """Accept every reviewed task in a plan: gate two, in bulk.

        The mirror of `approve_plan`. Gate one always had a bulk form —
        a human approves a decomposition as a whole — but gate two did
        not, so closing a plan meant accepting each task individually by
        UUID and a plan could realistically never reach COMPLETED. This
        does not weaken the gate: a human still decides, and only tasks
        actually in NEEDS_REVIEW move. Tasks still executing, failed, or
        awaiting approval are left exactly where they are.

        Accepting nothing is not an error — a plan whose work is already
        accepted is simply settled, and the caller can tell from the
        returned plan's status.

        Raises:
            PlanNotFoundError: If `plan_id` is not in the store.
            DomainValidationError: If a task cannot leave NEEDS_REVIEW.
        """
        plan = self._store.get_plan(plan_id)
        reviewed = [
            task
            for task in self._store.list_tasks(plan_id=plan_id)
            if task.status is TaskStatus.NEEDS_REVIEW
        ]
        for task in reviewed:
            self._transition_task(task, TaskStatus.DONE)
        self._logger.info("Plan %s accepted %d reviewed task(s).", plan_id, len(reviewed))
        self._complete_if_settled(plan)
        return plan

    def cancel_plan(self, plan_id: UUID) -> Plan:
        """Cancel a plan and every one of its non-terminal tasks.

        Raises:
            PlanNotFoundError: If `plan_id` is not in the store.
            DomainValidationError: If the plan is already terminal.
        """
        plan = self._store.get_plan(plan_id)
        for task in self._store.list_tasks(plan_id=plan_id):
            if task.status not in TERMINAL_TASK_STATUSES:
                self._transition_task(task, TaskStatus.CANCELLED)
        self._transition_plan(plan, PlanStatus.CANCELLED)
        self._logger.info("Plan %s cancelled.", plan_id)
        return plan

    def note_task_terminal(self, task: Task) -> Plan | None:
        """Complete `task`'s plan if that task was the last one open.

        Called by the facade whenever a task reaches a terminal status.
        Returns the completed plan, or None when there was nothing to
        complete.
        """
        if task.plan_id is None:
            return None
        return self._complete_if_settled(self._store.get_plan(task.plan_id))

    def _complete_if_settled(self, plan: Plan) -> Plan | None:
        """Complete `plan` if it is running and every one of its tasks is terminal.

        Returns the completed plan, or None when there was nothing to
        complete.
        """
        if plan.status is not PlanStatus.IN_PROGRESS:
            return None
        tasks = self._store.list_tasks(plan_id=plan.plan_id)
        if not all(member.status in TERMINAL_TASK_STATUSES for member in tasks):
            return None
        self._transition_plan(plan, PlanStatus.COMPLETED)
        self._logger.info("Plan %s completed; all %d task(s) terminal.", plan.plan_id, len(tasks))
        return plan

    def _transition_plan(self, plan: Plan, new_status: PlanStatus) -> None:
        """Transition `plan`, persist it, and publish the change."""
        previous = plan.status
        plan.transition_to(new_status)
        self._store.update_plan(plan)
        self._publish(
            PlanStatusChanged(
                source=SOURCE,
                payload={
                    "plan_id": str(plan.plan_id),
                    "project_id": plan.project_id,
                    "from": previous.name,
                    "to": plan.status.name,
                },
            )
        )

    def _transition_task(self, task: Task, new_status: TaskStatus) -> None:
        """Transition `task`, persist it, and publish the change."""
        previous = task.status
        task.transition_to(new_status)
        self._store.update_task(task)
        self._publish(
            TaskStatusChanged(
                source=SOURCE,
                payload={
                    "task_id": str(task.task_id),
                    "project_id": task.project_id,
                    "from": previous.name,
                    "to": task.status.name,
                },
            )
        )

    def _publish(self, event: Event) -> None:
        """Append `event` to the persistent log, then emit it on the bus."""
        self._store.append_event(event)
        self._bus.emit(event)

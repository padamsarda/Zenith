"""Presenting a workflow run to the terminal.

Split from `cli_workflow.py` the way `claude_code_output.py` is split
from `claude_code.py`: driving the lifecycle and describing it are
different jobs, and only this half changes when the wording, ordering,
or format of what a human sees changes. Everything here reads state and
prints; nothing decides anything.
"""

from __future__ import annotations

from uuid import UUID

from engineering_manager.domain.plan import Plan
from engineering_manager.domain.states import TaskStatus
from engineering_manager.manager import EngineeringManager
from engineering_manager.orchestration.engine import RunReport
from engineering_manager.orchestration.graph import execution_waves

# Statuses that mean a plan's work wants a human, once the engine has
# stopped advancing it.
GATE_STATUSES: tuple[TaskStatus, ...] = (
    TaskStatus.NEEDS_REVIEW,
    TaskStatus.FAILED,
    TaskStatus.DRAFT,
)

STATUS_WIDTH = 12


def print_waves(manager: EngineeringManager, plan_id: UUID) -> None:
    """Print a plan's task graph as the waves it will execute in."""
    for number, wave in enumerate(execution_waves(manager.plan_tasks(plan_id)), start=1):
        print(f"  Wave {number}:")
        for task in wave:
            print(f"    [{task.status.name:{STATUS_WIDTH}}] p{task.priority}  {task.title}")
    print()


def print_progress(manager: EngineeringManager, plan_id: UUID, heading: str) -> None:
    """Print where every task in the plan stands."""
    tasks = manager.plan_tasks(plan_id)
    done = sum(1 for task in tasks if task.status is TaskStatus.DONE)
    print(f"\n{heading}: {done}/{len(tasks)} task(s) done.")
    for task in tasks:
        print(f"  [{task.status.name:{STATUS_WIDTH}}] {task.title}")


def print_outcome(manager: EngineeringManager, plan: Plan, report: RunReport) -> None:
    """Say how the run ended and what, if anything, is waiting on a human.

    The plan is re-read rather than reported from `report`: the last
    round's acceptance may have completed it *after* the engine decided
    to stop, so the reason the loop ended is older than the truth.
    """
    current = manager.get_plan(plan.plan_id)
    print()
    if report.interrupted_by_user:
        print(f"Interrupted after {report.ticks} tick(s); plan is {current.status.name}.")
        print(f"Resume with: workflow --resume {plan.plan_id}")
    elif report.settled:
        print(f"Settled after {report.ticks} tick(s); plan is {current.status.name}.")
    else:
        print(f"Stopped after the {report.ticks}-tick budget, with work still running.")
        print(f"Resume with: workflow --resume {plan.plan_id}")
    for status in GATE_STATUSES:
        waiting = [
            task for task in manager.plan_tasks(plan.plan_id) if task.status is status
        ]
        if waiting:
            print(f"{len(waiting)} task(s) in {status.name} need you.")

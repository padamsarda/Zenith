"""The `workflow` command: one goal, start to finish, in one invocation.

Every step of the engineering lifecycle already existed as a facade
method — `plan_from_goal`, `approve_plan`, `run`, `accept_plan`,
`project_report`. What did not exist was the lifecycle itself. A human
had to know the order, register an account nobody told them about, copy
UUIDs between six commands, guess a tick count that meant "until it's
done", and then accept each finished task individually. The steps were
sound; the journey between them was not.

This module adds no orchestration of its own. It calls the same facade
methods in the order the lifecycle already implied, stopping at the two
human gates ADR 0006 defines rather than around them: the plan is shown
and confirmed before anything executes, and finished work is shown and
confirmed before it is accepted. `--yes` and `--accept` answer those
prompts in advance for unattended use, which is consent, not absence of
a gate.

Interruption is not a special path. State is durable, so `workflow
--resume <plan-id>` re-enters an existing plan at whatever point it
reached and runs the same loop — the same property ADR 0008 relies on
for crash recovery, surfaced as a command.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from engineering_manager.cli_workflow_output import (
    print_outcome,
    print_progress,
    print_waves,
)
from engineering_manager.domain.plan import Plan
from engineering_manager.domain.states import TERMINAL_PLAN_STATUSES, PlanStatus, TaskStatus
from engineering_manager.exceptions import AccountNotFoundError
from engineering_manager.manager import EngineeringManager
from engineering_manager.orchestration.engine import RunReport
from engineering_manager.orchestration.stop import WhenPlanSettled
from engineering_manager.providers.base import Provider
from shared.utils.time_utils import utc_now

REPORT_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"


def run_workflow(
    manager: EngineeringManager,
    args: argparse.Namespace,
    build_provider: Callable[[], Provider],
) -> None:
    """Drive one goal from decomposition through execution to a report.

    `build_provider` is passed in rather than chosen here so this module
    stays independent of which integrations exist — the CLI knows about
    `ClaudeCodeProvider`, the lifecycle does not.

    Raises:
        EngineeringManagerError: If any step fails; the plan and every
            task written before the failure survive, so the run can be
            resumed rather than restarted.
    """
    manager.register_provider(build_provider())
    plan = _resume(manager, args) if args.resume else _plan(manager, args)
    if not _gate_one(manager, plan, args):
        print(f"Left plan {plan.plan_id} in DRAFT. Approve it later with:")
        print(f"  plan approve {plan.plan_id}")
        return
    report = _drive(manager, plan, args)
    print_progress(manager, plan.plan_id, "Final state")
    print_outcome(manager, plan, report)
    _write_report(manager, plan, args)


def _drive(manager: EngineeringManager, plan: Plan, args: argparse.Namespace) -> RunReport:
    """Alternate execution with human gate two until the plan can go no further.

    A dependency chain cannot finish in a single pass. Gate two is what
    turns NEEDS_REVIEW into DONE, and a task's dependents are not
    eligible to dispatch until it *is* DONE — so running to quiescence
    and only then accepting would stall every plan deeper than one wave,
    with the engine spinning on an interval and nothing eligible to run.

    The fix is where the gate happens, not whether it happens: accept
    where it unblocks work, then execute again. The human still decides
    each round (or pre-authorizes every round with `--accept`), which is
    the same gate ADR 0006 defines, applied at the point it matters.
    """
    remaining = args.max_ticks
    ticks = 0
    while True:
        report = _execute(manager, plan, remaining, args)
        ticks += report.ticks
        if remaining is not None:
            remaining -= report.ticks
        if report.interrupted_by_user:
            return replace(report, ticks=ticks)
        print_progress(manager, plan.plan_id, "Progress")
        accepted = _gate_two(manager, plan, args)
        exhausted = remaining is not None and remaining <= 0
        settled = manager.get_plan(plan.plan_id).status in TERMINAL_PLAN_STATUSES
        if accepted == 0 or settled or exhausted:
            return replace(report, ticks=ticks)


def _plan(manager: EngineeringManager, args: argparse.Namespace) -> Plan:
    """Decompose the goal into a reviewable plan."""
    ensure_account(manager, args.provider, args.account)
    print(f"Decomposing goal with {args.provider}/{args.account}...")
    plan = manager.plan_from_goal(
        args.project_id,
        args.goal,
        provider_id=args.provider,
        account_id=args.account,
        description=args.description,
        model=args.model,
    )
    print(f"\nPlan {plan.plan_id}: {plan.goal}")
    print_waves(manager, plan.plan_id)
    return plan


def _resume(manager: EngineeringManager, args: argparse.Namespace) -> Plan:
    """Re-enter an existing plan wherever it left off."""
    plan = manager.get_plan(args.resume)
    ensure_account(manager, args.provider, args.account)
    print(f"Resuming plan {plan.plan_id} [{plan.status.name}]: {plan.goal}")
    print_waves(manager, plan.plan_id)
    return plan


def ensure_account(manager: EngineeringManager, provider_id: str, account_id: str) -> None:
    """Register the account if it is not already an execution resource.

    An account is only a name for a resource the provider already knows
    how to reach; making a human discover a separate `account add` step
    — undocumented, and silently fatal to dispatch when skipped — was
    friction with nothing behind it.

    Shared with `plan from-goal`, which also names an account: a command
    that accepts `--account X` and then leaves X unregistered sets up the
    exact failure ADR 0021 removed from `workflow`, one command over.
    """
    try:
        manager.store.get_account(provider_id, account_id)
    except AccountNotFoundError:
        manager.add_account(provider_id, account_id)
        print(f"Registered account {provider_id}/{account_id}.")


def _gate_one(manager: EngineeringManager, plan: Plan, args: argparse.Namespace) -> bool:
    """Human gate one: approve the decomposition before anything runs."""
    if plan.status is not PlanStatus.DRAFT:
        return True
    if not _confirm("Approve this plan and start execution? [y/N] ", args.yes):
        return False
    manager.approve_plan(plan.plan_id)
    print(f"Plan {plan.plan_id} approved.\n")
    return True


def _execute(
    manager: EngineeringManager,
    plan: Plan,
    max_ticks: int | None,
    args: argparse.Namespace,
) -> RunReport:
    """Run the engine until this plan settles, then report how it ended."""
    print(
        f"Executing (tick every {args.interval}s). "
        "Press Ctrl+C to stop; resume later with "
        f"`workflow --resume {plan.plan_id}`."
    )
    return manager.run(
        interval_seconds=args.interval,
        max_ticks=max_ticks,
        until=WhenPlanSettled(plan.plan_id),
    )


def _gate_two(manager: EngineeringManager, plan: Plan, args: argparse.Namespace) -> int:
    """Human gate two: accept the finished work, in bulk.

    Returns the number of tasks accepted — zero means the run has
    nothing left to unblock, which is what ends the drive loop.
    """
    reviewed = [
        task
        for task in manager.plan_tasks(plan.plan_id)
        if task.status is TaskStatus.NEEDS_REVIEW
    ]
    if not reviewed:
        return 0
    if not _confirm(f"Accept {len(reviewed)} completed task(s) as done? [y/N] ", args.accept):
        print(f"Left {len(reviewed)} task(s) awaiting review. Accept them with:")
        print(f"  plan accept {plan.plan_id}")
        return 0
    manager.accept_plan(plan.plan_id)
    print(f"Accepted {len(reviewed)} task(s).")
    return len(reviewed)


def _confirm(prompt: str, preapproved: bool) -> bool:
    """Ask for confirmation, unless a flag already answered it.

    A non-interactive stdin declines rather than assuming consent: an
    unattended caller that meant to approve says so with the flag.
    """
    if preapproved:
        return True
    if not sys.stdin.isatty():
        return False
    return input(prompt).strip().lower() in ("y", "yes")


def _write_report(
    manager: EngineeringManager, plan: Plan, args: argparse.Namespace
) -> None:
    """Write the engineering report for the plan's project as an artifact.

    A report only rendered to a terminal is gone the moment the window
    closes, which is the wrong property for the record of an unattended
    run. Writing one per run leaves a durable, timestamped trail beside
    the database that produced it.
    """
    directory: Path = args.artifacts
    directory.mkdir(parents=True, exist_ok=True)
    stamp = _timestamp(utc_now())
    path = directory / f"{plan.project_id}-{stamp}.md"
    path.write_text(manager.project_report(plan.project_id), encoding="utf-8")
    print(f"\nWrote engineering report to {path}.")


def _timestamp(moment: datetime) -> str:
    """Format `moment` for use in an artifact filename."""
    return moment.strftime(REPORT_TIMESTAMP_FORMAT)


def default_artifacts_directory(db_path: Path) -> Path:
    """Where run artifacts land when the caller does not choose."""
    return db_path.parent / "artifacts"

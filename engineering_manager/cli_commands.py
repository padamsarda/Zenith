"""Command handlers for the Engineering Manager CLI.

Split out from `cli.py` so building the argument parser and executing a
parsed command are separate responsibilities: `cli.build_parser`
produces the `argparse.Namespace` this module's `dispatch` acts on.
"""

from __future__ import annotations

import argparse
from uuid import UUID

from engineering_manager.domain.states import TaskStatus
from engineering_manager.manager import EngineeringManager
from engineering_manager.orchestration.graph import execution_waves
from engineering_manager.providers.claude_code import ClaudeCodeProvider


def dispatch(manager: EngineeringManager, args: argparse.Namespace) -> None:
    """Execute the parsed command against `manager`."""
    if args.command == "init":
        print(f"Database ready at {args.db}.")
    elif args.command == "project":
        _run_project(manager, args)
    elif args.command == "plan":
        _run_plan(manager, args)
    elif args.command == "task":
        _run_task(manager, args)
    elif args.command == "account":
        _run_account(manager, args)
    elif args.command == "status":
        _print_status(manager)
    elif args.command == "log":
        for entry in manager.list_events(limit=args.limit):
            timestamp = entry.timestamp.isoformat(timespec="seconds")
            print(f"[{timestamp}] {entry.name}: {entry.payload}")
    elif args.command == "run":
        _run_engine(manager, args)


def _run_project(manager: EngineeringManager, args: argparse.Namespace) -> None:
    """Execute a `project` subcommand."""
    if args.subcommand == "add":
        project = manager.add_project(
            args.project_id, args.name, args.path.resolve(), description=args.description
        )
        print(f"Added project '{project.project_id}' at {project.root_path}.")
    elif args.subcommand == "list":
        for project in manager.list_projects():
            print(f"{project.project_id}  {project.status.name}  {project.name}")


def _run_plan(manager: EngineeringManager, args: argparse.Namespace) -> None:
    """Execute a `plan` subcommand."""
    if args.subcommand == "add":
        plan = manager.add_plan(args.project_id, args.goal, description=args.description)
        print(f"Added plan {plan.plan_id} '{plan.goal}' (DRAFT).")
    elif args.subcommand == "list":
        for plan in manager.list_plans(project_id=args.project):
            print(f"{plan.plan_id}  {plan.status.name:12}  {plan.goal}")
    elif args.subcommand == "show":
        _print_plan(manager, args.plan_id)
    else:
        action = {"approve": manager.approve_plan, "cancel": manager.cancel_plan}[
            args.subcommand
        ]
        plan = action(args.plan_id)
        print(f"Plan {plan.plan_id} is now {plan.status.name}.")


def _print_plan(manager: EngineeringManager, plan_id: UUID) -> None:
    """Print a plan's goal and its task graph as execution waves."""
    plan = manager.get_plan(plan_id)
    print(f"Plan {plan.plan_id} [{plan.status.name}]: {plan.goal}")
    if plan.description:
        print(f"  {plan.description}")
    for number, wave in enumerate(execution_waves(manager.plan_tasks(plan_id)), start=1):
        print(f"Wave {number} (may run in parallel):")
        for task in wave:
            print(f"  {task.task_id}  {task.status.name:12}  p{task.priority}  {task.title}")


def _run_task(manager: EngineeringManager, args: argparse.Namespace) -> None:
    """Execute a `task` subcommand."""
    if args.subcommand == "add":
        task = manager.add_task(
            args.project_id,
            args.title,
            description=args.description,
            priority=args.priority,
            depends_on=args.depends_on,
            plan_id=args.plan,
        )
        print(f"Added task {task.task_id} '{task.title}' (DRAFT).")
    elif args.subcommand == "depend":
        task = manager.add_task_dependency(args.task_id, args.depends_on_id)
        print(f"Task {task.task_id} now depends on {args.depends_on_id}.")
    elif args.subcommand == "list":
        status = TaskStatus[args.status] if args.status else None
        for task in manager.list_tasks(project_id=args.project, status=status):
            print(f"{task.task_id}  {task.status.name:12}  p{task.priority}  {task.title}")
    else:
        action = {
            "approve": manager.approve_task,
            "accept": manager.accept_task,
            "rework": manager.rework_task,
            "retry": manager.retry_task,
            "cancel": manager.cancel_task,
        }[args.subcommand]
        task = action(args.task_id)
        print(f"Task {task.task_id} is now {task.status.name}.")


def _run_account(manager: EngineeringManager, args: argparse.Namespace) -> None:
    """Execute an `account` subcommand."""
    if args.subcommand == "add":
        account = manager.add_account(args.provider_id, args.account_id, label=args.label)
        print(f"Added account {account.provider_id}/{account.account_id}.")
    elif args.subcommand == "list":
        for account in manager.list_accounts():
            label = f"  ({account.label})" if account.label else ""
            print(f"{account.provider_id}/{account.account_id}{label}")


def _run_engine(manager: EngineeringManager, args: argparse.Namespace) -> None:
    """Register the Claude Code provider and run the execution engine.

    Accounts must already be registered (`account add claude-code <id>`)
    for any task to actually dispatch; without one, the engine simply
    idles, ticking with nothing eligible to run.
    """
    manager.register_provider(ClaudeCodeProvider(command=(args.claude_command,)))
    print(f"Running the execution engine every {args.interval}s. Press Ctrl+C to stop.")
    manager.run(interval_seconds=args.interval, max_ticks=args.max_ticks)


def _print_status(manager: EngineeringManager) -> None:
    """Print a one-screen summary of the store."""
    projects = manager.list_projects()
    print(f"Projects: {len(projects)}")
    for project in projects:
        tasks = manager.list_tasks(project_id=project.project_id)
        counts: dict[str, int] = {}
        for task in tasks:
            counts[task.status.name] = counts.get(task.status.name, 0) + 1
        summary = ", ".join(f"{count} {name}" for name, count in sorted(counts.items()))
        print(f"  {project.project_id} [{project.status.name}]: {summary or 'no tasks'}")
    open_sessions = [session for session in manager.list_sessions() if session.ended_at is None]
    print(f"Open sessions: {len(open_sessions)}")
    for session in open_sessions:
        print(
            f"  {session.session_id}  {session.status.name}  "
            f"{session.provider_id}/{session.account_id}  task {session.task_id}"
        )

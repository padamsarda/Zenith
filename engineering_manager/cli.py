"""Command-line interface for the Engineering Manager.

A thin layer over the `EngineeringManager` facade for the bookkeeping a
human does between the approval gates: managing projects, tasks, and
accounts, and inspecting state. Dispatching is not exposed here yet —
it requires a registered `Provider`, and real provider integrations are
the top item on the roadmap (`docs/roadmap.md`); until then, dispatch is
driven programmatically.

Usage: `python -m engineering_manager [--db PATH] <command> ...`
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import UUID

from engineering_manager.domain.states import TaskStatus
from engineering_manager.exceptions import EngineeringManagerError
from engineering_manager.manager import EngineeringManager
from engineering_manager.orchestration.graph import execution_waves
from engineering_manager.store.store import Store

DEFAULT_DB_PATH = Path.home() / ".zenith" / "engineering_manager.db"


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the CLI."""
    parser = argparse.ArgumentParser(
        prog="engineering_manager",
        description="Local-first orchestration of AI-performed engineering work.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Path to the database (default: {DEFAULT_DB_PATH}).",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("init", help="Create or upgrade the database.")

    project = commands.add_parser("project", help="Manage projects.")
    project_commands = project.add_subparsers(dest="subcommand", required=True)
    project_add = project_commands.add_parser("add", help="Place a repository under management.")
    project_add.add_argument("project_id")
    project_add.add_argument("name")
    project_add.add_argument("--path", type=Path, default=Path("."), help="Repository root.")
    project_add.add_argument("--description")
    project_commands.add_parser("list", help="List managed projects.")

    plan = commands.add_parser("plan", help="Manage plans (goal-level work).")
    plan_commands = plan.add_subparsers(dest="subcommand", required=True)
    plan_add = plan_commands.add_parser("add", help="Record a goal as a plan (in DRAFT).")
    plan_add.add_argument("project_id")
    plan_add.add_argument("goal")
    plan_add.add_argument("--description")
    plan_list = plan_commands.add_parser("list", help="List plans.")
    plan_list.add_argument("--project")
    plan_show = plan_commands.add_parser("show", help="Show a plan's task graph.")
    plan_show.add_argument("plan_id", type=UUID)
    for name, help_text in (
        ("approve", "Approve a plan and its DRAFT tasks (gate one, in bulk)."),
        ("cancel", "Cancel a plan and its non-terminal tasks."),
    ):
        subcommand = plan_commands.add_parser(name, help=help_text)
        subcommand.add_argument("plan_id", type=UUID)

    task = commands.add_parser("task", help="Manage tasks.")
    task_commands = task.add_subparsers(dest="subcommand", required=True)
    task_add = task_commands.add_parser("add", help="Create a task (in DRAFT).")
    task_add.add_argument("project_id")
    task_add.add_argument("title")
    task_add.add_argument("--description")
    task_add.add_argument("--priority", type=int, default=0)
    task_add.add_argument("--plan", type=UUID, help="The plan this task belongs to.")
    task_add.add_argument(
        "--depends-on",
        type=UUID,
        action="append",
        default=[],
        metavar="TASK_ID",
        help="A task that must be DONE first; repeatable.",
    )
    task_list = task_commands.add_parser("list", help="List tasks.")
    task_list.add_argument("--project")
    task_list.add_argument("--status", choices=[status.name for status in TaskStatus])
    task_depend = task_commands.add_parser(
        "depend", help="Make an existing task depend on another."
    )
    task_depend.add_argument("task_id", type=UUID)
    task_depend.add_argument("depends_on_id", type=UUID)
    for name, help_text in (
        ("approve", "Approve a DRAFT task for execution (gate one)."),
        ("accept", "Accept reviewed work as DONE (gate two)."),
        ("rework", "Send reviewed work back to READY."),
        ("retry", "Return a FAILED task to READY."),
        ("cancel", "Cancel a task permanently."),
    ):
        subcommand = task_commands.add_parser(name, help=help_text)
        subcommand.add_argument("task_id", type=UUID)

    account = commands.add_parser("account", help="Manage provider accounts.")
    account_commands = account.add_subparsers(dest="subcommand", required=True)
    account_add = account_commands.add_parser("add", help="Register an execution resource.")
    account_add.add_argument("provider_id")
    account_add.add_argument("account_id")
    account_add.add_argument("--label")
    account_commands.add_parser("list", help="List accounts.")

    commands.add_parser("status", help="Summarize projects, tasks, and sessions.")

    log = commands.add_parser("log", help="Show the event log, newest first.")
    log.add_argument("--limit", type=int, default=20)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI; return a process exit code."""
    args = build_parser().parse_args(argv)
    manager = EngineeringManager(Store(args.db))
    try:
        _run(manager, args)
    except EngineeringManagerError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        manager.close()
    return 0


def _run(manager: EngineeringManager, args: argparse.Namespace) -> None:
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
    open_sessions = [
        session
        for session in manager.list_sessions()
        if session.ended_at is None
    ]
    print(f"Open sessions: {len(open_sessions)}")
    for session in open_sessions:
        print(
            f"  {session.session_id}  {session.status.name}  "
            f"{session.provider_id}/{session.account_id}  task {session.task_id}"
        )

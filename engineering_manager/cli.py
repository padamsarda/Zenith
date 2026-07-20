"""Command-line interface for the Engineering Manager.

A thin layer over the `EngineeringManager` facade for the bookkeeping a
human does between the approval gates: managing projects, tasks, and
accounts, and inspecting state — plus `run`, which registers the Claude
Code provider (`engineering_manager/providers/claude_code.py`, ADR 0014)
and drives the execution engine. Argument parsing lives here; the
command handlers themselves are in `cli_commands.py`.

Usage: `python -m engineering_manager [--db PATH] <command> ...`
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import UUID

from engineering_manager.cli_commands import dispatch
from engineering_manager.domain.states import TaskStatus
from engineering_manager.exceptions import EngineeringManagerError
from engineering_manager.manager import EngineeringManager
from engineering_manager.store.store import Store

DEFAULT_TICK_INTERVAL_SECONDS = 30.0
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

    run = commands.add_parser(
        "run", help="Register the Claude Code provider and run the execution engine."
    )
    run.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_TICK_INTERVAL_SECONDS,
        help=f"Seconds between ticks (default: {DEFAULT_TICK_INTERVAL_SECONDS}).",
    )
    run.add_argument(
        "--max-ticks",
        type=int,
        default=None,
        help="Stop after this many ticks (default: run until interrupted).",
    )
    run.add_argument(
        "--claude-command",
        default="claude",
        help="Executable used to invoke Claude Code (default: claude).",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI; return a process exit code."""
    args = build_parser().parse_args(argv)
    manager = EngineeringManager(Store(args.db))
    try:
        dispatch(manager, args)
    except EngineeringManagerError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        manager.close()
    return 0

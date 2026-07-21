"""The Engineering Manager's command-line grammar.

Split from `cli.py` so that defining the arguments and running the
process are separate responsibilities: this module owns the grammar,
`cli.main` owns the entry point, and `cli_commands.dispatch` owns what
each parsed command does.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from uuid import UUID

from engineering_manager.domain.states import TaskStatus
from engineering_manager.providers.claude_code import (
    DEFAULT_PERMISSION_MODE,
    PERMISSION_MODES,
    DEFAULT_PROVIDER_ID,
)
from engineering_manager.providers.in_memory import DEFAULT_PROVIDER_ID as SIMULATED_PROVIDER_ID

DEFAULT_TICK_INTERVAL_SECONDS = 30.0
DEFAULT_DB_PATH = Path.home() / ".zenith" / "engineering_manager.db"
DEFAULT_ACCOUNT_ID = "default"


def _add_provider_choice(parser: argparse.ArgumentParser) -> None:
    """Add the flag choosing which provider executes the work."""
    parser.add_argument(
        "--provider",
        default=DEFAULT_PROVIDER_ID,
        choices=(DEFAULT_PROVIDER_ID, SIMULATED_PROVIDER_ID),
        help=(
            f"Execution provider (default: {DEFAULT_PROVIDER_ID}). "
            f"'{SIMULATED_PROVIDER_ID}' simulates sessions with no external "
            "process, for rehearsing the lifecycle."
        ),
    )


def _add_claude_command(parser: argparse.ArgumentParser) -> None:
    """Add the flag naming the Claude Code executable."""
    parser.add_argument(
        "--claude-command",
        default="claude",
        help="Executable used to invoke Claude Code (default: claude).",
    )


def _add_permission_mode(parser: argparse.ArgumentParser) -> None:
    """Add the flag granting a Claude Code session authority to act (ADR 0022)."""
    parser.add_argument(
        "--permission-mode",
        default=DEFAULT_PERMISSION_MODE,
        choices=PERMISSION_MODES,
        help=(
            "How much authority a Claude Code session has over the repository "
            f"(default: {DEFAULT_PERMISSION_MODE}). A --print session cannot "
            "answer permission prompts, so the default denies every edit and "
            "the session fails saying so; 'acceptEdits' is what lets it "
            "actually perform engineering work."
        ),
    )


def _add_change_tracking(parser: argparse.ArgumentParser) -> None:
    """Add the flag recording what each session changed (ADR 0023)."""
    parser.add_argument(
        "--track-changes",
        action="store_true",
        help=(
            "Stamp the git revision before and after each session, and report "
            "what each finished task changed. Without this the report can only "
            "repeat the summary a session wrote about itself."
        ),
    )


def _add_planning_timeout(parser: argparse.ArgumentParser) -> None:
    """Add the bound on a synchronous planning session."""
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=600.0,
        help="How long to wait for the planning session to finish (default: 600).",
    )


def _add_verification(parser: argparse.ArgumentParser) -> None:
    """Add the verification gate flags (ADR 0019)."""
    parser.add_argument(
        "--verify-command",
        help=(
            "Command run in a task's project directory before trusting a "
            "session's claimed completion (e.g. \"python -m pytest\"); a "
            "nonzero exit fails the session so it re-enters the retry loop "
            "instead of reaching NEEDS_REVIEW. Omit to trust providers as-is."
        ),
    )
    parser.add_argument(
        "--verify-timeout",
        type=float,
        default=600.0,
        help="Seconds allowed for --verify-command (default: 600).",
    )


def _add_tick_pacing(parser: argparse.ArgumentParser, max_ticks_help: str) -> None:
    """Add the flags controlling how the engine loop is paced and bounded."""
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_TICK_INTERVAL_SECONDS,
        help=f"Seconds between ticks (default: {DEFAULT_TICK_INTERVAL_SECONDS}).",
    )
    parser.add_argument("--max-ticks", type=int, default=None, help=max_ticks_help)


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
    project_relocate = project_commands.add_parser(
        "relocate", help="Point a project at a different working directory."
    )
    project_relocate.add_argument("project_id")
    project_relocate.add_argument(
        "--path",
        type=Path,
        required=True,
        help=(
            "New repository root. Sessions dispatch here, so this is how a "
            "project is aimed at a git worktree or a moved checkout without "
            "losing its plans, tasks, sessions, or event log."
        ),
    )
    project_report = project_commands.add_parser(
        "report", help="Render a Markdown engineering report for a project."
    )
    project_report.add_argument("project_id")
    project_report.add_argument(
        "--out", type=Path, help="Write the report to this file instead of stdout."
    )
    _add_change_tracking(project_report)

    plan = commands.add_parser("plan", help="Manage plans (goal-level work).")
    plan_commands = plan.add_subparsers(dest="subcommand", required=True)
    plan_add = plan_commands.add_parser("add", help="Record a goal as a plan (in DRAFT).")
    plan_add.add_argument("project_id")
    plan_add.add_argument("goal")
    plan_add.add_argument("--description")
    plan_from_goal = plan_commands.add_parser(
        "from-goal",
        help="Ask a provider to decompose a goal into a reviewable plan (still DRAFT).",
    )
    plan_from_goal.add_argument("project_id")
    plan_from_goal.add_argument("goal")
    plan_from_goal.add_argument("--description")
    plan_from_goal.add_argument("--provider", default="claude-code")
    plan_from_goal.add_argument("--account", required=True)
    plan_from_goal.add_argument("--model")
    _add_claude_command(plan_from_goal)
    _add_planning_timeout(plan_from_goal)
    plan_list = plan_commands.add_parser("list", help="List plans.")
    plan_list.add_argument("--project")
    plan_show = plan_commands.add_parser("show", help="Show a plan's task graph.")
    plan_show.add_argument("plan_id", type=UUID)
    plan_show.add_argument(
        "--detail",
        action="store_true",
        help=(
            "Include each task's description — what the session will actually "
            "be told to do. Read this before approving (gate one)."
        ),
    )
    for name, help_text in (
        ("approve", "Approve a plan and its DRAFT tasks (gate one, in bulk)."),
        ("accept", "Accept a plan's reviewed tasks as DONE (gate two, in bulk)."),
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
    task_show = task_commands.add_parser(
        "show", help="Show one task in full, with its session history."
    )
    task_show.add_argument("task_id", type=UUID)
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
    _add_tick_pacing(run, "Stop after this many ticks (default: run until interrupted).")
    _add_provider_choice(run)
    _add_claude_command(run)
    _add_permission_mode(run)
    _add_change_tracking(run)
    _add_verification(run)
    run.add_argument(
        "--until",
        choices=("forever", "quiescent"),
        default="forever",
        help=(
            "When to stop: 'forever' ticks until interrupted (default); "
            "'quiescent' stops once nothing can advance without a human."
        ),
    )
    run.add_argument(
        "--project",
        help="Scope --until quiescent to one project.",
    )

    workflow = commands.add_parser(
        "workflow",
        help="Run one goal end to end: plan, approve, execute, verify, report.",
    )
    workflow.add_argument("project_id")
    workflow.add_argument(
        "goal", nargs="?", help="The engineering objective (omit with --resume)."
    )
    workflow.add_argument(
        "--resume",
        type=UUID,
        metavar="PLAN_ID",
        help="Re-enter an existing plan instead of decomposing a new goal.",
    )
    workflow.add_argument("--description", help="Extra context for the planner.")
    _add_provider_choice(workflow)
    workflow.add_argument(
        "--account",
        default=DEFAULT_ACCOUNT_ID,
        help=f"Provider account; registered if new (default: {DEFAULT_ACCOUNT_ID}).",
    )
    workflow.add_argument("--model")
    workflow.add_argument(
        "--yes",
        action="store_true",
        help="Approve the plan without prompting (human gate one).",
    )
    workflow.add_argument(
        "--accept",
        action="store_true",
        help="Accept completed work without prompting (human gate two).",
    )
    _add_tick_pacing(
        workflow, "Safety bound on ticks (default: run until the plan settles)."
    )
    workflow.add_argument(
        "--artifacts",
        type=Path,
        help="Directory for engineering reports (default: alongside the database).",
    )
    _add_claude_command(workflow)
    _add_permission_mode(workflow)
    _add_change_tracking(workflow)
    _add_planning_timeout(workflow)
    _add_verification(workflow)

    return parser

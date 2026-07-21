"""The CLI commands that actually run the execution engine.

`run` is the low-level operator loop; `workflow` is the whole lifecycle
(`cli_workflow.py`). Both need the same three things assembled from
parsed arguments — a provider, an optional verification gate, and a
terminal that shows progress — so that assembly lives here rather than
being duplicated or pushed down into the orchestration layer, which
should never know what a command-line flag is.
"""

from __future__ import annotations

import argparse
import logging
import shlex
import sys

from engineering_manager.cli_workflow import default_artifacts_directory, run_workflow
from engineering_manager.exceptions import OrchestrationError
from engineering_manager.manager import EngineeringManager
from engineering_manager.orchestration.planning import (
    DEFAULT_POLL_INTERVAL_SECONDS,
    PlanningSessionRunner,
)
from engineering_manager.orchestration.revisions import GitRevisionProbe
from engineering_manager.orchestration.stop import RunForever, StopCondition, WhenQuiescent
from engineering_manager.orchestration.verification import CommandVerificationPolicy
from engineering_manager.providers.base import Provider
from engineering_manager.providers.claude_code import ClaudeCodeProvider
from engineering_manager.providers.in_memory import (
    DEFAULT_PROVIDER_ID as SIMULATED_PROVIDER_ID,
)
from engineering_manager.providers.in_memory import InMemoryProvider

# One check per tick is enough for a simulated session to finish on the
# tick after it starts, so a demo run moves at the tick interval.
SIMULATED_CHECKS_TO_FINISH = 1
LOG_FORMAT = "%(asctime)s  %(message)s"
LOG_TIME_FORMAT = "%H:%M:%S"


def run_engine(manager: EngineeringManager, args: argparse.Namespace) -> None:
    """Register the Claude Code provider and run the execution engine.

    Accounts must already be registered (`account add claude-code <id>`)
    for any task to actually dispatch; without one, the engine simply
    idles, ticking with nothing eligible to run. `workflow` handles that
    registration itself — this command stays the low-level operator loop.
    """
    _configure_logging()
    provider = _build_provider(args)
    manager.register_provider(provider)
    _require_accounts(manager, provider.provider_id)
    _apply_change_tracking(manager, args)
    _apply_verification(manager, args)
    print(f"Running the execution engine every {args.interval}s. Press Ctrl+C to stop.")
    report = manager.run(
        interval_seconds=args.interval,
        max_ticks=args.max_ticks,
        until=_stop_condition(args),
    )
    if report.settled:
        print(f"Stopped after {report.ticks} tick(s): {report.stopped_because}")


def run_workflow_command(manager: EngineeringManager, args: argparse.Namespace) -> None:
    """Drive one goal from decomposition through execution to a report.

    Raises:
        OrchestrationError: If neither a goal nor `--resume` was given.
    """
    if not args.goal and not args.resume:
        raise OrchestrationError(
            "Give a goal to plan, or --resume <plan-id> to continue an existing one."
        )
    _configure_logging()
    if args.artifacts is None:
        args.artifacts = default_artifacts_directory(args.db)
    manager.set_planning_runner(
        PlanningSessionRunner(
            manager.providers,
            max_polls=max(1, int(args.timeout_seconds / DEFAULT_POLL_INTERVAL_SECONDS)),
        )
    )
    _apply_change_tracking(manager, args)
    _apply_verification(manager, args)
    run_workflow(manager, args, lambda: _build_provider(args))


def _require_accounts(manager: EngineeringManager, provider_id: str) -> None:
    """Refuse to start a run that could never dispatch anything.

    With no account on the chosen provider, every tick reaches dispatch,
    finds nothing it may use, and logs the same warning forever — and
    `--until quiescent` will not stop it, because READY work genuinely
    does remain; only the means to run it is missing. Failing at startup
    turns an unbounded silent idle into one actionable line.

    Raises:
        OrchestrationError: If no account is registered on `provider_id`.
    """
    if manager.list_accounts(provider_id=provider_id):
        return
    raise OrchestrationError(
        f"No account is registered on provider '{provider_id}', so no task "
        "could ever be dispatched. Register one with: "
        f"account add {provider_id} <account-id>"
    )


def _build_provider(args: argparse.Namespace) -> Provider:
    """Construct the provider the run will execute against."""
    if args.provider == SIMULATED_PROVIDER_ID:
        return InMemoryProvider(finish_after_checks=SIMULATED_CHECKS_TO_FINISH)
    return ClaudeCodeProvider(
        command=(args.claude_command,), permission_mode=args.permission_mode
    )


def _apply_change_tracking(manager: EngineeringManager, args: argparse.Namespace) -> None:
    """Install the git revision probe when change tracking was requested."""
    if not args.track_changes:
        return
    manager.set_revision_probe(GitRevisionProbe())
    print("Recording what each session changes, via git.")


def _apply_verification(manager: EngineeringManager, args: argparse.Namespace) -> None:
    """Install the command verification gate when one was requested."""
    if not args.verify_command:
        return
    manager.set_verification_policy(
        CommandVerificationPolicy(
            tuple(shlex.split(args.verify_command)),
            timeout_seconds=args.verify_timeout,
        )
    )
    print(f"Verifying completions with: {args.verify_command}")


def _stop_condition(args: argparse.Namespace) -> StopCondition:
    """Map `run --until` onto a stop condition."""
    if args.until == "quiescent":
        return WhenQuiescent(project_id=args.project)
    return RunForever()


def _configure_logging() -> None:
    """Send the engine's own progress narration to the terminal.

    The engine has always logged what each tick moved, but nothing ever
    configured a handler for it, so an unattended run showed a blank
    screen for hours. Only the commands that actually run the engine
    configure logging — the read-only ones stay quiet.
    """
    logging.basicConfig(
        level=logging.INFO, format=LOG_FORMAT, datefmt=LOG_TIME_FORMAT, stream=sys.stderr
    )

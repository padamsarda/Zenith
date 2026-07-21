"""AI-performed planning: turn a goal into a reviewable task decomposition.

ADR 0009 anticipated this closing the loop "with no new mechanism": a
planning session is an ordinary `Provider` session (ADR 0005) whose
instructions ask for a task breakdown instead of engineering work, run
to completion synchronously and bounded (unlike the hours-long sessions
`ExecutionEngine` drives). `PlanningSessionRunner` is the provider-facing
half; `planning_decomposition.py` is the pure-parsing half that turns its
raw output into `TaskDraft`s. `EngineeringManager.plan_from_goal` writes
those drafts through the existing facade methods (`add_plan`, `add_task`,
`add_task_dependency`), so the plan lands in `DRAFT` exactly as a
human-authored one would — `approve_plan` is still the gate, so a bad or
adversarial decomposition cannot dispatch itself.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from engineering_manager.domain.project import Project
from engineering_manager.domain.task import Task
from engineering_manager.exceptions import OrchestrationError, ProviderSessionError
from engineering_manager.orchestration.planning_decomposition import build_planning_instructions
from engineering_manager.providers.base import (
    Provider,
    ProviderSessionState,
    SessionHandle,
    SessionSpec,
)
from engineering_manager.providers.registry import ProviderRegistry
from shared.utils.uuid_utils import generate_id

DEFAULT_LOGGER_NAME = "zenith.em"
DEFAULT_POLL_INTERVAL_SECONDS = 3.0
DEFAULT_MAX_POLLS = 200


class PlanningSessionRunner:
    """Runs one bounded, synchronous provider session and returns its output.

    Distinct from `Dispatcher`/`ExecutionEngine`: those drive long-running
    engineering sessions across many ticks with retry and interruption
    handling. A planning session is a single request-response exchange a
    human is actively waiting on (from the CLI, or a future API), so it
    polls itself to completion instead of being driven by the tick loop
    — `LIMIT_REACHED`/`AWAITING_INPUT` are reported as failures here
    rather than interruptions to recover from later.
    """

    def __init__(
        self,
        providers: ProviderRegistry,
        *,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        max_polls: int = DEFAULT_MAX_POLLS,
        sleep: Callable[[float], None] = time.sleep,
        logger: logging.Logger | None = None,
    ) -> None:
        self._providers = providers
        self._poll_interval_seconds = poll_interval_seconds
        self._max_polls = max_polls
        self._sleep = sleep
        self._logger = logger or logging.getLogger(DEFAULT_LOGGER_NAME)

    def run(
        self,
        *,
        provider_id: str,
        account_id: str,
        project: Project,
        goal: str,
        description: str | None = None,
        model: str | None = None,
    ) -> str:
        """Run a planning session to completion and return its raw output.

        Raises:
            ProviderNotFoundError: If `provider_id` is not registered.
            ProviderSessionError: If the provider cannot start the session.
            OrchestrationError: If the session fails, needs a human
                (`LIMIT_REACHED`/`AWAITING_INPUT`), or does not finish
                within `max_polls`.
        """
        provider = self._providers.get(provider_id)
        # SessionSpec.task is required by the contract but unused by
        # every shipped Provider; a transient, never-persisted Task
        # satisfies the shape without a new mechanism (ADR 0005).
        transient_task = Task(project_id=project.project_id, title=f"Plan: {goal}")
        spec = SessionSpec(
            session_id=generate_id(),
            project=project,
            task=transient_task,
            account_id=account_id,
            model=model,
            instructions=build_planning_instructions(goal, description),
            metadata={"purpose": "planning"},
        )
        handle = provider.start_session(spec)
        self._logger.info("Started planning session for goal %r.", goal)
        finished = False
        try:
            for _ in range(self._max_polls):
                status = provider.check_session(handle)
                if status.state is ProviderSessionState.FINISHED:
                    finished = True
                    if not status.detail or not status.detail.strip():
                        raise OrchestrationError("Planning session finished with no output.")
                    return status.detail
                if status.state is ProviderSessionState.FAILED:
                    finished = True
                    raise OrchestrationError(
                        f"Planning session failed: {status.detail or '(no detail)'}"
                    )
                if status.state in (
                    ProviderSessionState.LIMIT_REACHED,
                    ProviderSessionState.AWAITING_INPUT,
                ):
                    finished = True
                    raise OrchestrationError(
                        f"Planning session needs a human ({status.state.name}); "
                        "resolve it with the provider directly, then plan again."
                    )
                self._sleep(self._poll_interval_seconds)
            raise OrchestrationError(
                f"Planning session for goal {goal!r} did not finish within "
                f"{self._max_polls} poll(s)."
            )
        finally:
            if not finished:
                self._best_effort_stop(provider, handle)

    def _best_effort_stop(self, provider: Provider, handle: SessionHandle) -> None:
        """Stop a still-running session on the way out after a timeout."""
        try:
            provider.stop_session(handle)
        except ProviderSessionError as exc:
            self._logger.warning("Could not stop abandoned planning session: %s", exc)

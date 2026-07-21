"""Tests for PlanningSessionRunner."""

from __future__ import annotations

from pathlib import Path

import pytest

from engineering_manager.domain.project import Project
from engineering_manager.exceptions import (
    OrchestrationError,
    ProviderNotFoundError,
    ProviderSessionError,
)
from engineering_manager.orchestration.planning import PlanningSessionRunner
from engineering_manager.providers.base import ProviderSessionState, ProviderSessionStatus
from engineering_manager.providers.in_memory import InMemoryProvider
from engineering_manager.providers.registry import ProviderRegistry


@pytest.fixture
def project() -> Project:
    return Project(project_id="zenith", name="Zenith", root_path=Path("."))


@pytest.fixture
def providers() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(InMemoryProvider())
    return registry


def test_run_returns_output_once_finished(providers: ProviderRegistry, project: Project) -> None:
    provider = providers.get("in-memory")
    runner = PlanningSessionRunner(providers, sleep=lambda seconds: None)

    # Finish the session on the runner's very next poll: patch check_session
    # via scripting after start, since InMemoryProvider begins RUNNING.
    original_start = provider.start_session

    def start_and_finish(spec):
        handle = original_start(spec)
        provider.script_status(
            handle, ProviderSessionStatus(state=ProviderSessionState.FINISHED, detail="[]")
        )
        return handle

    provider.start_session = start_and_finish  # type: ignore[method-assign]

    output = runner.run(
        provider_id="in-memory", account_id="a", project=project, goal="Ship it"
    )

    assert output == "[]"


def test_run_polls_until_finished(providers: ProviderRegistry, project: Project) -> None:
    provider = providers.get("in-memory")
    polls: list[int] = []
    runner = PlanningSessionRunner(providers, sleep=lambda seconds: polls.append(1))

    call_count = {"n": 0}

    def check_then_finish(handle):
        call_count["n"] += 1
        if call_count["n"] < 3:
            return ProviderSessionStatus(state=ProviderSessionState.RUNNING)
        return ProviderSessionStatus(state=ProviderSessionState.FINISHED, detail='[{"title": "A"}]')

    provider.check_session = check_then_finish  # type: ignore[method-assign]

    output = runner.run(provider_id="in-memory", account_id="a", project=project, goal="Ship it")

    assert output == '[{"title": "A"}]'
    assert call_count["n"] == 3
    assert len(polls) == 2  # slept between poll 1->2 and 2->3, not after finishing


def test_run_raises_on_unregistered_provider(
    providers: ProviderRegistry, project: Project
) -> None:
    runner = PlanningSessionRunner(providers, sleep=lambda seconds: None)

    with pytest.raises(ProviderNotFoundError):
        runner.run(provider_id="nope", account_id="a", project=project, goal="Ship it")


def test_run_raises_on_failed_session(providers: ProviderRegistry, project: Project) -> None:
    provider = providers.get("in-memory")
    original_start = provider.start_session

    def start_and_fail(spec):
        handle = original_start(spec)
        provider.script_status(
            handle, ProviderSessionStatus(state=ProviderSessionState.FAILED, detail="crashed")
        )
        return handle

    provider.start_session = start_and_fail  # type: ignore[method-assign]
    runner = PlanningSessionRunner(providers, sleep=lambda seconds: None)

    with pytest.raises(OrchestrationError, match="crashed"):
        runner.run(provider_id="in-memory", account_id="a", project=project, goal="Ship it")


@pytest.mark.parametrize(
    "state", [ProviderSessionState.LIMIT_REACHED, ProviderSessionState.AWAITING_INPUT]
)
def test_run_raises_when_session_needs_a_human(
    providers: ProviderRegistry, project: Project, state: ProviderSessionState
) -> None:
    provider = providers.get("in-memory")
    original_start = provider.start_session

    def start_and_interrupt(spec):
        handle = original_start(spec)
        provider.script_status(handle, ProviderSessionStatus(state=state))
        return handle

    provider.start_session = start_and_interrupt  # type: ignore[method-assign]
    runner = PlanningSessionRunner(providers, sleep=lambda seconds: None)

    with pytest.raises(OrchestrationError, match=state.name):
        runner.run(provider_id="in-memory", account_id="a", project=project, goal="Ship it")


def test_run_raises_on_empty_finished_output(
    providers: ProviderRegistry, project: Project
) -> None:
    provider = providers.get("in-memory")
    original_start = provider.start_session

    def start_and_finish_empty(spec):
        handle = original_start(spec)
        provider.script_status(
            handle, ProviderSessionStatus(state=ProviderSessionState.FINISHED, detail=None)
        )
        return handle

    provider.start_session = start_and_finish_empty  # type: ignore[method-assign]
    runner = PlanningSessionRunner(providers, sleep=lambda seconds: None)

    with pytest.raises(OrchestrationError, match="no output"):
        runner.run(provider_id="in-memory", account_id="a", project=project, goal="Ship it")


def test_run_times_out_and_stops_the_session(
    providers: ProviderRegistry, project: Project
) -> None:
    provider = providers.get("in-memory")
    stopped: list[object] = []
    original_stop = provider.stop_session

    def tracking_stop(handle):
        stopped.append(handle)
        original_stop(handle)

    provider.stop_session = tracking_stop  # type: ignore[method-assign]
    runner = PlanningSessionRunner(
        providers, max_polls=3, sleep=lambda seconds: None
    )

    with pytest.raises(OrchestrationError, match="did not finish"):
        runner.run(provider_id="in-memory", account_id="a", project=project, goal="Ship it")

    assert len(stopped) == 1


def test_run_raises_if_provider_cannot_start(project: Project) -> None:
    class RefusingProvider(InMemoryProvider):
        def start_session(self, spec):
            raise ProviderSessionError("no capacity")

    providers = ProviderRegistry()
    providers.register(RefusingProvider())
    runner = PlanningSessionRunner(providers, sleep=lambda seconds: None)

    with pytest.raises(ProviderSessionError):
        runner.run(provider_id="in-memory", account_id="a", project=project, goal="Ship it")

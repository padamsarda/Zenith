"""Tests for the InMemoryProvider reference implementation."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from engineering_manager.domain.project import Project
from engineering_manager.domain.task import Task
from engineering_manager.exceptions import ProviderSessionError
from engineering_manager.orchestration.planning_decomposition import parse_decomposition
from engineering_manager.providers.base import (
    ProviderSessionState,
    ProviderSessionStatus,
    SessionHandle,
    SessionSpec,
)
from engineering_manager.providers.in_memory import InMemoryProvider


def make_spec(tmp_path: Path) -> SessionSpec:
    project = Project(project_id="zenith", name="Zenith", root_path=tmp_path)
    task = Task(project_id="zenith", title="Write docs")
    return SessionSpec(
        session_id=uuid4(), project=project, task=task, account_id="personal"
    )


def test_start_session_returns_handle_with_own_provider_id(tmp_path: Path) -> None:
    provider = InMemoryProvider()

    handle = provider.start_session(make_spec(tmp_path))

    assert handle.provider_id == "in-memory"
    assert handle.external_ref


def test_started_session_reports_running(tmp_path: Path) -> None:
    provider = InMemoryProvider()
    handle = provider.start_session(make_spec(tmp_path))

    status = provider.check_session(handle)

    assert status.state is ProviderSessionState.RUNNING


def test_two_sessions_get_distinct_refs(tmp_path: Path) -> None:
    provider = InMemoryProvider()

    first = provider.start_session(make_spec(tmp_path))
    second = provider.start_session(make_spec(tmp_path))

    assert first.external_ref != second.external_ref


def test_started_specs_are_recorded_in_order(tmp_path: Path) -> None:
    provider = InMemoryProvider()
    first_spec = make_spec(tmp_path)
    second_spec = make_spec(tmp_path)

    provider.start_session(first_spec)
    provider.start_session(second_spec)

    assert provider.started_specs == [first_spec, second_spec]


def test_script_status_controls_check_session(tmp_path: Path) -> None:
    provider = InMemoryProvider()
    handle = provider.start_session(make_spec(tmp_path))
    scripted = ProviderSessionStatus(
        state=ProviderSessionState.LIMIT_REACHED, detail="session limit"
    )

    provider.script_status(handle, scripted)

    assert provider.check_session(handle) == scripted


def test_resume_session_issues_fresh_ref(tmp_path: Path) -> None:
    provider = InMemoryProvider()
    handle = provider.start_session(make_spec(tmp_path))

    resumed = provider.resume_session(handle)

    assert resumed.external_ref != handle.external_ref
    assert provider.check_session(resumed).state is ProviderSessionState.RUNNING


def test_old_handle_is_invalid_after_resume(tmp_path: Path) -> None:
    provider = InMemoryProvider()
    handle = provider.start_session(make_spec(tmp_path))
    provider.resume_session(handle)

    with pytest.raises(ProviderSessionError):
        provider.check_session(handle)


def test_stop_session_marks_finished(tmp_path: Path) -> None:
    provider = InMemoryProvider()
    handle = provider.start_session(make_spec(tmp_path))

    provider.stop_session(handle)

    assert provider.check_session(handle).state is ProviderSessionState.FINISHED


@pytest.mark.parametrize("method", ["check_session", "resume_session", "stop_session"])
def test_unknown_handle_raises(method: str) -> None:
    provider = InMemoryProvider()
    unknown = SessionHandle(provider_id="in-memory", external_ref="missing")

    with pytest.raises(ProviderSessionError):
        getattr(provider, method)(unknown)


def test_script_status_on_unknown_handle_raises() -> None:
    provider = InMemoryProvider()
    unknown = SessionHandle(provider_id="in-memory", external_ref="missing")

    with pytest.raises(ProviderSessionError):
        provider.script_status(
            unknown, ProviderSessionStatus(state=ProviderSessionState.FINISHED)
        )


def test_sessions_do_not_self_finish_by_default(tmp_path: Path) -> None:
    provider = InMemoryProvider()
    handle = provider.start_session(make_spec(tmp_path))

    for _ in range(5):
        assert provider.check_session(handle).state is ProviderSessionState.RUNNING


def test_session_finishes_after_the_configured_number_of_checks(
    tmp_path: Path,
) -> None:
    provider = InMemoryProvider(finish_after_checks=2)
    handle = provider.start_session(make_spec(tmp_path))

    assert provider.check_session(handle).state is ProviderSessionState.RUNNING
    assert provider.check_session(handle).state is ProviderSessionState.FINISHED


def test_self_finished_session_stays_finished(tmp_path: Path) -> None:
    provider = InMemoryProvider(finish_after_checks=1)
    handle = provider.start_session(make_spec(tmp_path))

    provider.check_session(handle)

    assert provider.check_session(handle).state is ProviderSessionState.FINISHED


def test_self_finishing_reports_the_task_it_worked_on(tmp_path: Path) -> None:
    provider = InMemoryProvider(finish_after_checks=1)
    handle = provider.start_session(make_spec(tmp_path))

    detail = provider.check_session(handle).detail

    assert detail is not None
    assert "Write docs" in detail


def test_a_scripted_status_overrides_self_finishing(tmp_path: Path) -> None:
    provider = InMemoryProvider(finish_after_checks=1)
    handle = provider.start_session(make_spec(tmp_path))
    provider.script_status(
        handle, ProviderSessionStatus(state=ProviderSessionState.FAILED, detail="Nope.")
    )

    assert provider.check_session(handle).state is ProviderSessionState.FAILED


def test_planning_session_self_finishes_with_a_parsable_decomposition(
    tmp_path: Path,
) -> None:
    """The simulated workflow depends on planning output the parser accepts."""
    provider = InMemoryProvider(finish_after_checks=1)
    project = Project(project_id="zenith", name="Zenith", root_path=tmp_path)
    spec = SessionSpec(
        session_id=uuid4(),
        project=project,
        task=Task(project_id="zenith", title="Plan: Ship it"),
        account_id="personal",
        metadata={"purpose": "planning"},
    )
    handle = provider.start_session(spec)

    detail = provider.check_session(handle).detail

    assert detail is not None
    drafts = parse_decomposition(detail)
    assert len(drafts) == 3
    assert all("Ship it" in draft.title for draft in drafts)
    assert drafts[-1].depends_on == (1,)


def test_resumed_session_starts_its_check_count_over(tmp_path: Path) -> None:
    provider = InMemoryProvider(finish_after_checks=2)
    handle = provider.start_session(make_spec(tmp_path))
    provider.check_session(handle)

    resumed = provider.resume_session(handle)

    assert provider.check_session(resumed).state is ProviderSessionState.RUNNING
    assert provider.check_session(resumed).state is ProviderSessionState.FINISHED

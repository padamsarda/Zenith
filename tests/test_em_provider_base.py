"""Tests for the Provider contract's data types."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from uuid import uuid4

import pytest

from engineering_manager.domain.project import Project
from engineering_manager.domain.task import Task
from engineering_manager.providers.base import (
    Provider,
    ProviderSessionState,
    ProviderSessionStatus,
    SessionHandle,
    SessionSpec,
)


def make_spec(tmp_path: Path) -> SessionSpec:
    project = Project(project_id="zenith", name="Zenith", root_path=tmp_path)
    task = Task(project_id="zenith", title="Write docs")
    return SessionSpec(
        session_id=uuid4(), project=project, task=task, account_id="personal"
    )


def test_provider_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        Provider()  # type: ignore[abstract]


def test_session_spec_defaults(tmp_path: Path) -> None:
    spec = make_spec(tmp_path)

    assert spec.model is None
    assert spec.instructions is None
    assert spec.metadata == {}


def test_session_spec_is_frozen(tmp_path: Path) -> None:
    spec = make_spec(tmp_path)

    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.account_id = "other"  # type: ignore[misc]


def test_session_handle_is_frozen_and_comparable() -> None:
    handle = SessionHandle(provider_id="in-memory", external_ref="ref-1")

    assert handle == SessionHandle(provider_id="in-memory", external_ref="ref-1")
    with pytest.raises(dataclasses.FrozenInstanceError):
        handle.external_ref = "ref-2"  # type: ignore[misc]


def test_provider_session_status_defaults() -> None:
    status = ProviderSessionStatus(state=ProviderSessionState.RUNNING)

    assert status.detail is None
    assert status.resume_at is None
    assert status.usage is None


def test_provider_session_state_members() -> None:
    assert {state.name for state in ProviderSessionState} == {
        "RUNNING",
        "AWAITING_INPUT",
        "LIMIT_REACHED",
        "FINISHED",
        "FAILED",
    }

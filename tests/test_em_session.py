"""Tests for the Session domain entity."""

from __future__ import annotations

import dataclasses
from uuid import UUID, uuid4

import pytest

from engineering_manager.domain.session import Session
from engineering_manager.domain.states import SessionStatus
from engineering_manager.exceptions import DomainValidationError


def make_session() -> Session:
    return Session(
        task_id=uuid4(), project_id="zenith", provider_id="claude", account_id="personal"
    )


def test_session_defaults() -> None:
    session = make_session()

    assert session.status is SessionStatus.ACTIVE
    assert session.external_ref is None
    assert session.ended_at is None
    assert session.summary is None
    assert isinstance(session.session_id, UUID)
    assert session.started_at.tzinfo is not None


def test_session_fields_are_frozen() -> None:
    session = make_session()

    with pytest.raises(dataclasses.FrozenInstanceError):
        session.provider_id = "other"  # type: ignore[misc]


def test_session_status_cannot_be_assigned_directly() -> None:
    session = make_session()

    with pytest.raises(dataclasses.FrozenInstanceError):
        session.status = SessionStatus.COMPLETED  # type: ignore[misc]


def test_session_interrupt_and_resume() -> None:
    session = make_session()

    session.transition_to(SessionStatus.INTERRUPTED)
    session.transition_to(SessionStatus.ACTIVE)

    assert session.status is SessionStatus.ACTIVE


def test_session_invalid_transition_raises_and_preserves_status() -> None:
    session = make_session()
    session.transition_to(SessionStatus.COMPLETED)

    with pytest.raises(DomainValidationError):
        session.transition_to(SessionStatus.ACTIVE)
    assert session.status is SessionStatus.COMPLETED


def test_update_external_ref_records_reference() -> None:
    session = make_session()

    session.update_external_ref("conversation-42")
    assert session.external_ref == "conversation-42"

    session.update_external_ref("conversation-43")
    assert session.external_ref == "conversation-43"


def test_update_external_ref_rejects_non_string() -> None:
    session = make_session()

    with pytest.raises(DomainValidationError):
        session.update_external_ref(42)  # type: ignore[arg-type]


def test_close_requires_terminal_status() -> None:
    session = make_session()

    with pytest.raises(DomainValidationError):
        session.close()
    assert session.ended_at is None


def test_close_stamps_ended_at_and_summary() -> None:
    session = make_session()
    session.transition_to(SessionStatus.COMPLETED)

    session.close(summary="Implemented the store.")

    assert session.ended_at is not None
    assert session.ended_at.tzinfo is not None
    assert session.summary == "Implemented the store."


def test_close_twice_raises() -> None:
    session = make_session()
    session.transition_to(SessionStatus.FAILED)
    session.close()

    with pytest.raises(DomainValidationError):
        session.close()


def test_update_external_ref_after_close_raises() -> None:
    session = make_session()
    session.transition_to(SessionStatus.COMPLETED)
    session.close()

    with pytest.raises(DomainValidationError):
        session.update_external_ref("late-ref")


def test_close_without_summary_keeps_existing_summary() -> None:
    session = Session(
        task_id=uuid4(),
        project_id="zenith",
        provider_id="claude",
        account_id="personal",
        summary="preset",
    )
    session.transition_to(SessionStatus.ABANDONED)

    session.close()

    assert session.summary == "preset"

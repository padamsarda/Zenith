"""Tests for the AssistantRequest dataclass."""

from __future__ import annotations

import dataclasses

import pytest

from runtime.assistant.request import AssistantRequest
from runtime.assistant.status import RequestStatus
from runtime.exceptions import RequestValidationError
from shared.utils.uuid_utils import generate_id


def make_request() -> AssistantRequest:
    return AssistantRequest(conversation_id=generate_id(), text="hello")


def test_new_request_is_received() -> None:
    assert make_request().status is RequestStatus.RECEIVED


def test_requests_get_unique_ids() -> None:
    assert make_request().request_id != make_request().request_id


def test_created_at_is_timezone_aware() -> None:
    assert make_request().created_at.tzinfo is not None


def test_metadata_defaults_to_empty_dict() -> None:
    assert make_request().metadata == {}


def test_requests_do_not_share_default_metadata() -> None:
    first = make_request()
    second = make_request()
    first.metadata["key"] = "value"

    assert second.metadata == {}


def test_text_cannot_be_assigned_directly() -> None:
    request = make_request()

    with pytest.raises(dataclasses.FrozenInstanceError):
        request.text = "changed"  # type: ignore[misc]


def test_status_cannot_be_assigned_directly() -> None:
    request = make_request()

    with pytest.raises(dataclasses.FrozenInstanceError):
        request.status = RequestStatus.RUNNING  # type: ignore[misc]


def test_transition_to_walks_the_happy_path() -> None:
    request = make_request()
    request.transition_to(RequestStatus.RUNNING)
    request.transition_to(RequestStatus.COMPLETED)

    assert request.status is RequestStatus.COMPLETED


def test_received_can_fail_directly() -> None:
    request = make_request()
    request.transition_to(RequestStatus.FAILED)

    assert request.status is RequestStatus.FAILED


def test_invalid_transition_raises_and_preserves_status() -> None:
    request = make_request()
    request.transition_to(RequestStatus.RUNNING)
    request.transition_to(RequestStatus.COMPLETED)

    with pytest.raises(RequestValidationError):
        request.transition_to(RequestStatus.RUNNING)
    assert request.status is RequestStatus.COMPLETED


def test_received_cannot_complete_directly() -> None:
    request = make_request()

    with pytest.raises(RequestValidationError):
        request.transition_to(RequestStatus.COMPLETED)

"""Tests for the assistant pipeline validation guard functions."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.assistant.request import AssistantRequest
from runtime.assistant.status import RequestStatus
from runtime.assistant.validation import (
    validate_request,
    validate_request_metadata,
    validate_request_text,
    validate_status_transition,
    validate_turn,
)
from runtime.exceptions import RequestValidationError
from runtime.providers.base import AssistantTurn, ToolCall
from shared.utils.uuid_utils import generate_id


# --- validate_status_transition -----------------------------------------


@pytest.mark.parametrize(
    ("current", "new"),
    [
        (RequestStatus.RECEIVED, RequestStatus.RUNNING),
        (RequestStatus.RECEIVED, RequestStatus.FAILED),
        (RequestStatus.RECEIVED, RequestStatus.CANCELLED),
        (RequestStatus.RUNNING, RequestStatus.COMPLETED),
        (RequestStatus.RUNNING, RequestStatus.FAILED),
        (RequestStatus.RUNNING, RequestStatus.CANCELLED),
    ],
)
def test_valid_transitions_pass(current: RequestStatus, new: RequestStatus) -> None:
    validate_status_transition(current, new)


@pytest.mark.parametrize(
    ("current", "new"),
    [
        (RequestStatus.RECEIVED, RequestStatus.COMPLETED),
        (RequestStatus.RUNNING, RequestStatus.RECEIVED),
        (RequestStatus.COMPLETED, RequestStatus.RUNNING),
        (RequestStatus.FAILED, RequestStatus.RUNNING),
        (RequestStatus.CANCELLED, RequestStatus.RUNNING),
        (RequestStatus.RECEIVED, RequestStatus.RECEIVED),
    ],
)
def test_invalid_transitions_raise(current: RequestStatus, new: RequestStatus) -> None:
    with pytest.raises(RequestValidationError):
        validate_status_transition(current, new)


# --- validate_request_text ----------------------------------------------


def test_plain_text_is_valid() -> None:
    validate_request_text("hello")


def test_padded_text_is_valid() -> None:
    validate_request_text("hello\n")


@pytest.mark.parametrize("bad_text", ["", "   ", None, 42])
def test_invalid_text_raises(bad_text: Any) -> None:
    with pytest.raises(RequestValidationError):
        validate_request_text(bad_text)


# --- validate_request_metadata ------------------------------------------


def test_string_keyed_metadata_is_valid() -> None:
    validate_request_metadata({"provider": "echo"})


def test_non_dict_metadata_raises() -> None:
    with pytest.raises(RequestValidationError):
        validate_request_metadata("bad")  # type: ignore[arg-type]


def test_non_string_metadata_key_raises() -> None:
    with pytest.raises(RequestValidationError):
        validate_request_metadata({1: "value"})  # type: ignore[dict-item]


# --- validate_request ---------------------------------------------------


def test_valid_request_passes() -> None:
    validate_request(AssistantRequest(conversation_id=generate_id(), text="hello"))


def test_request_with_blank_text_raises() -> None:
    request = AssistantRequest(conversation_id=generate_id(), text="  ")

    with pytest.raises(RequestValidationError):
        validate_request(request)


# --- validate_turn ------------------------------------------------------


def test_text_only_turn_is_valid() -> None:
    validate_turn(AssistantTurn(text="hello"))


def test_tool_calls_only_turn_is_valid() -> None:
    validate_turn(AssistantTurn(tool_calls=(ToolCall(tool_id="clock"),)))


def test_text_and_tool_calls_turn_is_valid() -> None:
    validate_turn(AssistantTurn(text="checking", tool_calls=(ToolCall(tool_id="clock"),)))


def test_empty_turn_raises() -> None:
    with pytest.raises(RequestValidationError):
        validate_turn(AssistantTurn())


def test_blank_text_turn_raises() -> None:
    with pytest.raises(RequestValidationError):
        validate_turn(AssistantTurn(text="  "))


def test_non_tool_call_entry_raises() -> None:
    turn = AssistantTurn(tool_calls=("clock",))  # type: ignore[arg-type]

    with pytest.raises(RequestValidationError):
        validate_turn(turn)

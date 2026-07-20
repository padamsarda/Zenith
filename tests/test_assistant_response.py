"""Tests for the AssistantResponse dataclass."""

from __future__ import annotations

import dataclasses

import pytest

from runtime.assistant.response import AssistantResponse
from shared.utils.uuid_utils import generate_id


def make_response(*, success: bool = True) -> AssistantResponse:
    return AssistantResponse(
        success=success,
        text="hello",
        request_id=generate_id(),
        conversation_id=generate_id(),
        duration_seconds=0.5,
    )


def test_response_defaults() -> None:
    response = make_response()

    assert response.turns == 0
    assert response.exception is None


def test_response_is_frozen() -> None:
    response = make_response()

    with pytest.raises(dataclasses.FrozenInstanceError):
        response.text = "changed"  # type: ignore[misc]


def test_failed_response_carries_the_exception() -> None:
    error = ValueError("boom")
    response = AssistantResponse(
        success=False,
        text="boom",
        request_id=generate_id(),
        conversation_id=generate_id(),
        duration_seconds=0.1,
        exception=error,
    )

    assert response.success is False
    assert response.exception is error

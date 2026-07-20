"""Validation helpers for the assistant pipeline.

Mirrors `runtime.commands.validation`: small, explicit guard functions
that raise on failure rather than returning a boolean, used at the
boundaries of the pipeline (request entry, status transitions, provider
turns).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from runtime.assistant.status import RequestStatus
from runtime.exceptions import RequestValidationError
from runtime.providers.base import ToolCall

if TYPE_CHECKING:
    from runtime.assistant.request import AssistantRequest
    from runtime.providers.base import AssistantTurn

_VALID_TRANSITIONS: dict[RequestStatus, frozenset[RequestStatus]] = {
    RequestStatus.RECEIVED: frozenset(
        {RequestStatus.RUNNING, RequestStatus.FAILED, RequestStatus.CANCELLED}
    ),
    RequestStatus.RUNNING: frozenset(
        {RequestStatus.COMPLETED, RequestStatus.FAILED, RequestStatus.CANCELLED}
    ),
    RequestStatus.COMPLETED: frozenset(),
    RequestStatus.FAILED: frozenset(),
    RequestStatus.CANCELLED: frozenset(),
}


def validate_status_transition(current: RequestStatus, new: RequestStatus) -> None:
    """Raise RequestValidationError if `current` -> `new` is not allowed.

    `COMPLETED`, `FAILED`, and `CANCELLED` are terminal and accept no
    further transitions.
    """
    if new not in _VALID_TRANSITIONS[current]:
        raise RequestValidationError(
            f"Invalid request status transition: {current.name} -> {new.name}"
        )


def validate_request_text(text: Any) -> None:
    """Raise RequestValidationError if `text` is not usable request text.

    Text must be a non-empty string once stripped; leading/trailing
    whitespace is allowed, as with message content.
    """
    if not isinstance(text, str) or not text.strip():
        raise RequestValidationError(f"Request text must be non-empty, got {text!r}")


def validate_request_metadata(metadata: dict[str, Any]) -> None:
    """Raise RequestValidationError if `metadata` is not a string-keyed dict."""
    if not isinstance(metadata, dict):
        raise RequestValidationError(
            f"Request metadata must be a dict, got {type(metadata).__name__}"
        )
    for key in metadata:
        if not isinstance(key, str):
            raise RequestValidationError(f"Request metadata keys must be strings, got {key!r}")


def validate_request(request: AssistantRequest) -> None:
    """Raise RequestValidationError if `request` fails structural validation.

    Checks the request's text and metadata.
    """
    validate_request_text(request.text)
    validate_request_metadata(request.metadata)


def validate_turn(turn: AssistantTurn) -> None:
    """Raise RequestValidationError if `turn` is not a usable provider turn.

    A turn must carry text (non-empty once stripped), tool calls, or
    both; every tool call must be a `ToolCall`.
    """
    if turn.text is not None and (not isinstance(turn.text, str) or not turn.text.strip()):
        raise RequestValidationError(f"Turn text must be non-empty when present, got {turn.text!r}")
    for call in turn.tool_calls:
        if not isinstance(call, ToolCall):
            raise RequestValidationError(f"Turn tool calls must be ToolCall instances, got {call!r}")
    if turn.text is None and not turn.tool_calls:
        raise RequestValidationError("A turn must carry text, tool calls, or both.")

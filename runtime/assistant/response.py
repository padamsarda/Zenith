"""AssistantResponse: the outcome of serving one assistant request."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class AssistantResponse:
    """The outcome of one request through the assistant pipeline.

    `AssistantEngine.handle` always returns an `AssistantResponse` —
    whether the request completed, failed validation, was rejected by a
    hook, or hit a provider failure — never `None`, mirroring
    `CommandResult`. On success `text` is the assistant's reply; on
    failure it is a human-readable explanation and `exception` carries
    the cause when one exists.
    """

    success: bool
    text: str
    request_id: UUID
    conversation_id: UUID
    duration_seconds: float
    turns: int = 0
    exception: BaseException | None = None

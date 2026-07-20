"""Assistant request lifecycle state definitions."""

from __future__ import annotations

from enum import Enum, auto


class RequestStatus(Enum):
    """Represents the lifecycle state of an AssistantRequest.

    `RECEIVED -> RUNNING -> COMPLETED`, with `FAILED` reachable from
    either non-terminal status (validation and lookup failures happen
    before RUNNING) and `CANCELLED` reserved for a future cancellation
    mechanism, mirroring `CommandStatus.QUEUED`.
    """

    RECEIVED = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


TERMINAL_STATUSES: frozenset[RequestStatus] = frozenset(
    {RequestStatus.COMPLETED, RequestStatus.FAILED, RequestStatus.CANCELLED}
)

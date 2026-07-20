"""Message: one immutable entry in a conversation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any
from uuid import UUID

from shared.utils.time_utils import utc_now
from shared.utils.uuid_utils import generate_id


class MessageRole(Enum):
    """Who (or what) a message is from.

    `TOOL` marks the recorded outcome of a tool invocation — appended by
    the assistant engine after a tool runs, so the provider can see what
    its requested calls produced on the next turn.
    """

    USER = auto()
    ASSISTANT = auto()
    SYSTEM = auto()
    TOOL = auto()


@dataclass(frozen=True)
class Message:
    """A single immutable message within a conversation.

    Construction does not validate `role`, `content`, or `metadata`;
    that happens at the framework boundary, in
    `runtime.conversation.validation.validate_message`, mirroring how
    `Command` is validated separately from construction.
    """

    role: MessageRole
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    message_id: UUID = field(default_factory=generate_id)
    created_at: datetime = field(default_factory=utc_now)

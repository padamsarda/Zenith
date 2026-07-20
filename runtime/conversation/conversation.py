"""Conversation: an append-only sequence of messages with a lifecycle."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from runtime.conversation.message import Message
from runtime.conversation.state import ConversationState
from runtime.conversation.validation import (
    validate_conversation_active,
    validate_message,
    validate_state_transition,
)
from shared.utils.time_utils import utc_now
from shared.utils.uuid_utils import generate_id


class Conversation:
    """One conversation between a user and the assistant.

    Identity, creation time, and title are fixed at construction.
    Messages are append-only — nothing ever edits or removes one — and
    `state` only changes through `transition_to`, mirroring how
    `Command` and `Plugin` guard their lifecycles. `messages` returns a
    snapshot tuple, so no caller can mutate history from outside.
    """

    def __init__(
        self,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._conversation_id: UUID = generate_id()
        self._created_at: datetime = utc_now()
        self._title: str | None = title
        self._metadata: dict[str, Any] = metadata or {}
        self._state: ConversationState = ConversationState.ACTIVE
        self._messages: list[Message] = []

    @property
    def conversation_id(self) -> UUID:
        """Unique identifier, auto-generated at construction."""
        return self._conversation_id

    @property
    def created_at(self) -> datetime:
        """UTC timestamp of construction."""
        return self._created_at

    @property
    def title(self) -> str | None:
        """Optional human-readable title."""
        return self._title

    @property
    def metadata(self) -> dict[str, Any]:
        """Extra data attached at construction."""
        return self._metadata

    @property
    def state(self) -> ConversationState:
        """Current lifecycle state."""
        return self._state

    @property
    def messages(self) -> tuple[Message, ...]:
        """A snapshot of the conversation's messages, oldest first."""
        return tuple(self._messages)

    def transition_to(self, new_state: ConversationState) -> None:
        """Move this conversation to `new_state`.

        Raises:
            ConversationValidationError: If the transition from the
                current state to `new_state` is not permitted.
        """
        validate_state_transition(self._state, new_state)
        self._state = new_state

    def append(self, message: Message) -> None:
        """Append `message` to the conversation.

        Raises:
            ConversationValidationError: If the conversation is not
                ACTIVE, or `message` fails structural validation.
        """
        validate_conversation_active(self)
        validate_message(message)
        self._messages.append(message)

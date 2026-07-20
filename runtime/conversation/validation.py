"""Validation helpers for the conversation model.

Mirrors `runtime.commands.validation`: small, explicit guard functions
that raise on failure rather than returning a boolean, used at the
boundaries of the conversation model (appending messages, state
transitions).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from runtime.conversation.message import MessageRole
from runtime.conversation.state import ConversationState
from runtime.exceptions import ConversationValidationError

if TYPE_CHECKING:
    from runtime.conversation.conversation import Conversation
    from runtime.conversation.message import Message

_VALID_TRANSITIONS: dict[ConversationState, frozenset[ConversationState]] = {
    ConversationState.ACTIVE: frozenset({ConversationState.ARCHIVED}),
    ConversationState.ARCHIVED: frozenset(),
}


def validate_state_transition(current: ConversationState, new: ConversationState) -> None:
    """Raise ConversationValidationError if `current` -> `new` is not allowed.

    The only valid transition is `ACTIVE -> ARCHIVED`; `ARCHIVED` is
    terminal and accepts no further transitions.
    """
    if new not in _VALID_TRANSITIONS[current]:
        raise ConversationValidationError(
            f"Invalid conversation state transition: {current.name} -> {new.name}"
        )


def validate_message_content(content: Any) -> None:
    """Raise ConversationValidationError if `content` is not usable message text.

    Content must be a non-empty string once stripped. Unlike short
    identifiers, leading/trailing whitespace is allowed — message text
    is prose, and multi-line content legitimately ends in a newline.
    """
    if not isinstance(content, str) or not content.strip():
        raise ConversationValidationError(f"Message content must be non-empty text, got {content!r}")


def validate_message_metadata(metadata: dict[str, Any]) -> None:
    """Raise ConversationValidationError if `metadata` is not a string-keyed dict."""
    if not isinstance(metadata, dict):
        raise ConversationValidationError(
            f"Message metadata must be a dict, got {type(metadata).__name__}"
        )
    for key in metadata:
        if not isinstance(key, str):
            raise ConversationValidationError(
                f"Message metadata keys must be strings, got {key!r}"
            )


def validate_message(message: Message) -> None:
    """Raise ConversationValidationError if `message` fails structural validation.

    Checks the message's role, content, and metadata.
    """
    if not isinstance(message.role, MessageRole):
        raise ConversationValidationError(f"Message role must be a MessageRole, got {message.role!r}")
    validate_message_content(message.content)
    validate_message_metadata(message.metadata)


def validate_conversation_active(conversation: Conversation) -> None:
    """Raise ConversationValidationError if `conversation` cannot accept messages."""
    if conversation.state is not ConversationState.ACTIVE:
        raise ConversationValidationError(
            f"Conversation {conversation.conversation_id} is {conversation.state.name}, "
            "not ACTIVE, and cannot accept messages."
        )

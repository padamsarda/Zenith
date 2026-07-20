"""Conversation lifecycle state definitions."""

from __future__ import annotations

from enum import Enum, auto


class ConversationState(Enum):
    """Represents the lifecycle state of a Conversation.

    `ACTIVE -> ARCHIVED`; `ARCHIVED` is terminal — see `TERMINAL_STATES`.
    An archived conversation keeps its messages for reading but accepts
    no new ones. Requests fail, not conversations: a failed request
    leaves its conversation `ACTIVE` and usable.
    """

    ACTIVE = auto()
    ARCHIVED = auto()


TERMINAL_STATES: frozenset[ConversationState] = frozenset({ConversationState.ARCHIVED})

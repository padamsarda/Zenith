"""Concrete events emitted by the conversation store."""

from __future__ import annotations

from dataclasses import dataclass

from shared.events.event import Event


@dataclass(frozen=True)
class ConversationStarted(Event):
    """Emitted when the ConversationStore creates a new conversation."""


@dataclass(frozen=True)
class ConversationArchived(Event):
    """Emitted when a conversation is archived."""


@dataclass(frozen=True)
class MessageAppended(Event):
    """Emitted when a message is appended to a conversation through the store."""

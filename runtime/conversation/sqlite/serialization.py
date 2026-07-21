"""Conversion between conversation domain objects and database rows.

Kept separate from `store.py` so the domain stays persistence-agnostic
and the SQL stays serialization-agnostic — the same split
`engineering_manager/store/serialization.py` uses (ADR 0004).
Conventions match it too: enums are stored by `.name`, datetimes as
ISO-8601 strings, UUIDs as their canonical string form, and `dict`
metadata as JSON objects.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any
from uuid import UUID

from runtime.conversation.conversation import Conversation
from runtime.conversation.message import Message, MessageRole
from runtime.conversation.state import ConversationState


def conversation_to_row(conversation: Conversation) -> dict[str, Any]:
    """Convert a Conversation to a `conversations` row dict (no messages)."""
    return {
        "conversation_id": str(conversation.conversation_id),
        "title": conversation.title,
        "metadata": json.dumps(conversation.metadata),
        "status": conversation.state.name,
        "created_at": conversation.created_at.isoformat(),
    }


def conversation_from_row(row: sqlite3.Row, messages: list[Message]) -> Conversation:
    """Rebuild a Conversation from a `conversations` row and its already-loaded messages."""
    return Conversation.restore(
        conversation_id=UUID(row["conversation_id"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        title=row["title"],
        metadata=json.loads(row["metadata"]),
        state=ConversationState[row["status"]],
        messages=messages,
    )


def message_to_row(conversation_id: UUID, message: Message) -> dict[str, Any]:
    """Convert a Message to a `messages` row dict."""
    return {
        "message_id": str(message.message_id),
        "conversation_id": str(conversation_id),
        "role": message.role.name,
        "content": message.content,
        "metadata": json.dumps(message.metadata),
        "created_at": message.created_at.isoformat(),
    }


def message_from_row(row: sqlite3.Row) -> Message:
    """Rebuild a Message from a `messages` row."""
    return Message(
        message_id=UUID(row["message_id"]),
        role=MessageRole[row["role"]],
        content=row["content"],
        metadata=json.loads(row["metadata"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )

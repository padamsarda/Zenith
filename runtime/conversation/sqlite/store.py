"""SQLiteConversationStore: durable ConversationStore backed by SQLite."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from runtime.conversation.conversation import Conversation
from runtime.conversation.events import (
    ConversationArchived,
    ConversationStarted,
    MessageAppended,
)
from runtime.conversation.sqlite.database import open_database
from runtime.conversation.sqlite.serialization import (
    conversation_from_row,
    conversation_to_row,
    message_from_row,
    message_to_row,
)
from runtime.conversation.state import ConversationState
from runtime.conversation.store import SOURCE, ConversationStore
from runtime.exceptions import ConversationNotFoundError, ConversationStoreError

if TYPE_CHECKING:
    from runtime.context import ApplicationContext
    from runtime.conversation.message import Message


class SQLiteConversationStore(ConversationStore):
    """Conversation history that survives a process restart.

    Validation and lifecycle rules stay exactly where they already live
    — on `Conversation` and `Message` — this store only translates
    between rows and those same domain objects (ADR 0004's principle:
    "the domain layer knows nothing about persistence"). `append` and
    `archive` reconstruct the conversation via `get`, run the ordinary
    `Conversation.append`/`transition_to` on it (so a durable and an
    in-memory store reject exactly the same appends and transitions),
    and persist only the new row if that succeeds.

    Not wired in by default — an integrator assigns an instance onto
    `ApplicationContext.conversations`, the same way `ClaudeProvider`
    (ADR 0015) or a `runtime.tools` tool is registered, so a fresh
    `python main.py` gains no filesystem access it wasn't given.
    """

    def __init__(self, path: Path) -> None:
        """Open (creating and migrating if needed) the store at `path`."""
        self._connection = open_database(path)

    def close(self) -> None:
        """Close the underlying database connection."""
        self._connection.close()

    def create(
        self,
        application_context: ApplicationContext,
        *,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Conversation:
        conversation = Conversation(title=title, metadata=metadata)
        self._insert("conversations", conversation_to_row(conversation))
        application_context.events.emit(
            ConversationStarted(
                source=SOURCE,
                payload={
                    "conversation_id": str(conversation.conversation_id),
                    "title": conversation.title,
                },
            )
        )
        return conversation

    def get(self, conversation_id: UUID) -> Conversation:
        row = self._connection.execute(
            "SELECT * FROM conversations WHERE conversation_id = ?", (str(conversation_id),)
        ).fetchone()
        if row is None:
            raise ConversationNotFoundError(f"Conversation {conversation_id} is not in the store.")
        return self._hydrate(row)

    def has(self, conversation_id: UUID) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM conversations WHERE conversation_id = ?", (str(conversation_id),)
        ).fetchone()
        return row is not None

    def list(self) -> list[Conversation]:
        rows = self._connection.execute(
            "SELECT * FROM conversations ORDER BY created_at, rowid"
        ).fetchall()
        return [self._hydrate(row) for row in rows]

    def append(
        self,
        conversation_id: UUID,
        message: Message,
        application_context: ApplicationContext,
    ) -> None:
        conversation = self.get(conversation_id)
        conversation.append(message)
        self._insert("messages", message_to_row(conversation_id, message))
        application_context.events.emit(
            MessageAppended(
                source=SOURCE,
                payload={
                    "conversation_id": str(conversation_id),
                    "message_id": str(message.message_id),
                    "role": message.role.name,
                },
            )
        )

    def archive(self, conversation_id: UUID, application_context: ApplicationContext) -> None:
        conversation = self.get(conversation_id)
        conversation.transition_to(ConversationState.ARCHIVED)
        try:
            with self._connection:
                self._connection.execute(
                    "UPDATE conversations SET status = ? WHERE conversation_id = ?",
                    (ConversationState.ARCHIVED.name, str(conversation_id)),
                )
        except sqlite3.Error as exc:
            raise ConversationStoreError(f"Could not archive conversation: {exc}") from exc
        application_context.events.emit(
            ConversationArchived(
                source=SOURCE,
                payload={"conversation_id": str(conversation_id)},
            )
        )

    def _hydrate(self, row: sqlite3.Row) -> Conversation:
        """Build a Conversation from a `conversations` row and its messages."""
        message_rows = self._connection.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY rowid",
            (row["conversation_id"],),
        ).fetchall()
        return conversation_from_row(row, [message_from_row(r) for r in message_rows])

    def _insert(self, table: str, row: dict[str, object]) -> None:
        """INSERT `row` into `table`, translating any failure.

        Raises:
            ConversationStoreError: On any integrity or database failure.
        """
        columns = ", ".join(row)
        placeholders = ", ".join(f":{column}" for column in row)
        try:
            with self._connection:
                self._connection.execute(
                    f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", row
                )
        except sqlite3.Error as exc:
            raise ConversationStoreError(f"Could not insert into {table}: {exc}") from exc

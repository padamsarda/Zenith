"""SQLite connection management and schema migrations for conversation history.

The schema is versioned through SQLite's `user_version` pragma, the
exact mechanism `engineering_manager/store/database.py` uses (ADR 0004):
each entry in `MIGRATIONS` is one version step, applied in order inside
a transaction. A database at version N gets migrations N+1..latest
applied the next time it is opened, so old databases upgrade
automatically and new schema changes are always additive migration
scripts — never edits to an existing entry.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from runtime.exceptions import ConversationStoreError

# One SQL script per schema version, index 0 == version 1. Append only.
MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE conversations (
        conversation_id TEXT PRIMARY KEY,
        title           TEXT,
        metadata        TEXT NOT NULL DEFAULT '{}',
        status          TEXT NOT NULL,
        created_at      TEXT NOT NULL
    );

    CREATE TABLE messages (
        message_id      TEXT PRIMARY KEY,
        conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
        role            TEXT NOT NULL,
        content         TEXT NOT NULL,
        metadata        TEXT NOT NULL DEFAULT '{}',
        created_at      TEXT NOT NULL
    );
    CREATE INDEX idx_messages_conversation ON messages(conversation_id);
    """,
)

SCHEMA_VERSION = len(MIGRATIONS)


def open_database(path: Path) -> sqlite3.Connection:
    """Open (creating and migrating as needed) the database at `path`.

    Parent directories are created if missing. The returned connection
    has foreign-key enforcement on, WAL journaling for local-first
    durability, and `sqlite3.Row` rows.

    Raises:
        ConversationStoreError: If the database is newer than this code
            understands, or a migration fails.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA foreign_keys = ON")
    _migrate(connection)
    return connection


def _migrate(connection: sqlite3.Connection) -> None:
    """Bring `connection`'s schema up to `SCHEMA_VERSION`.

    Raises:
        ConversationStoreError: If the database is ahead of this code,
            or a migration script fails (the failed step is rolled back).
    """
    current = connection.execute("PRAGMA user_version").fetchone()[0]
    if current > SCHEMA_VERSION:
        raise ConversationStoreError(
            f"Conversation database schema is version {current}, newer than "
            f"the supported version {SCHEMA_VERSION}. Update Zenith."
        )

    for version in range(current + 1, SCHEMA_VERSION + 1):
        script = MIGRATIONS[version - 1]
        try:
            with connection:
                connection.executescript(script)
                # PRAGMA cannot be parameterized; `version` is an int from range().
                connection.execute(f"PRAGMA user_version = {version}")
        except sqlite3.Error as exc:
            raise ConversationStoreError(
                f"Migration to schema version {version} failed: {exc}"
            ) from exc

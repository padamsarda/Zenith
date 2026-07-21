"""SQLite connection management and schema migrations for memory.

Versioned through `user_version` exactly like the conversation store
(ADR 0018) and the Engineering Manager's store (ADR 0004): each entry in
`MIGRATIONS` is one version step, applied in order, append-only forever.

The one thing this schema does that the others do not is carry an FTS5
virtual table. FTS5 ships compiled into the SQLite that CPython bundles,
so full-text search with BM25 ranking costs no dependency — which is why
it, rather than a vector index, is this design's relevance mechanism
(ADR 0027).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from runtime.exceptions import MemoryStoreError

# One SQL script per schema version, index 0 == version 1. Append only.
MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE memories (
        memory_id        TEXT PRIMARY KEY,
        content          TEXT NOT NULL,
        kind             TEXT NOT NULL,
        importance       INTEGER NOT NULL,
        pinned           INTEGER NOT NULL DEFAULT 0,
        tags             TEXT NOT NULL DEFAULT '[]',
        source           TEXT NOT NULL DEFAULT 'assistant',
        metadata         TEXT NOT NULL DEFAULT '{}',
        occurred_at      TEXT NOT NULL,
        created_at       TEXT NOT NULL,
        last_accessed_at TEXT NOT NULL,
        access_count     INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX idx_memories_occurred ON memories(occurred_at);

    -- `content=` makes this an external-content index: the text lives in
    -- `memories`, and FTS5 stores only what it needs to search, rather
    -- than a second full copy of every memory.
    CREATE VIRTUAL TABLE memories_fts USING fts5(
        content,
        content='memories',
        content_rowid='rowid'
    );

    -- FTS5 external-content tables are not updated automatically; these
    -- triggers are the documented way to keep the index consistent with
    -- the table it indexes.
    CREATE TRIGGER memories_ai AFTER INSERT ON memories BEGIN
        INSERT INTO memories_fts(rowid, content) VALUES (new.rowid, new.content);
    END;
    CREATE TRIGGER memories_ad AFTER DELETE ON memories BEGIN
        INSERT INTO memories_fts(memories_fts, rowid, content)
        VALUES ('delete', old.rowid, old.content);
    END;
    CREATE TRIGGER memories_au AFTER UPDATE ON memories BEGIN
        INSERT INTO memories_fts(memories_fts, rowid, content)
        VALUES ('delete', old.rowid, old.content);
        INSERT INTO memories_fts(rowid, content) VALUES (new.rowid, new.content);
    END;
    """,
)

SCHEMA_VERSION = len(MIGRATIONS)


def open_database(path: Path) -> sqlite3.Connection:
    """Open (creating and migrating as needed) the memory database at `path`.

    Raises:
        MemoryStoreError: If the database is newer than this code
            understands, a migration fails, or SQLite was built without
            FTS5.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA foreign_keys = ON")
    _require_fts5(connection)
    _migrate(connection)
    return connection


def _require_fts5(connection: sqlite3.Connection) -> None:
    """Fail loudly, at open time, if this SQLite build lacks FTS5.

    Checked here rather than discovered as a confusing "no such module"
    error partway through a migration — and worth an explicit message,
    since a build without FTS5 is rare but not impossible.
    """
    try:
        connection.execute("CREATE VIRTUAL TABLE temp.fts5_probe USING fts5(x)")
        connection.execute("DROP TABLE temp.fts5_probe")
    except sqlite3.Error as exc:
        raise MemoryStoreError(
            "This SQLite build has no FTS5 module, which the memory store "
            f"requires for full-text search: {exc}"
        ) from exc


def _migrate(connection: sqlite3.Connection) -> None:
    """Bring `connection`'s schema up to `SCHEMA_VERSION`.

    Raises:
        MemoryStoreError: If the database is ahead of this code, or a
            migration script fails (the failed step is rolled back).
    """
    current = connection.execute("PRAGMA user_version").fetchone()[0]
    if current > SCHEMA_VERSION:
        raise MemoryStoreError(
            f"Memory database schema is version {current}, newer than the "
            f"supported version {SCHEMA_VERSION}. Update Zenith."
        )

    for version in range(current + 1, SCHEMA_VERSION + 1):
        script = MIGRATIONS[version - 1]
        try:
            with connection:
                connection.executescript(script)
                # PRAGMA cannot be parameterized; `version` is an int from range().
                connection.execute(f"PRAGMA user_version = {version}")
        except sqlite3.Error as exc:
            raise MemoryStoreError(
                f"Migration to schema version {version} failed: {exc}"
            ) from exc

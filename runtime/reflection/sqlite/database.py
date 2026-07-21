"""SQLite connection management and schema migrations for reflections.

Versioned through `user_version` like every other store here (ADR 0004,
0018, 0027): each entry in `MIGRATIONS` is one version step, append-only
forever.

Provenance gets its own table rather than a JSON column on `reflections`.
It is a genuine many-to-many relation — one insight draws on many
memories, one memory informs many insights — and the question the layer
exists to answer ("which insights came from this memory?") is a query
against it. Encoding it as JSON would make that question require a full
scan and string matching (ADR 0029).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from runtime.exceptions import ReflectionStoreError

# One SQL script per schema version, index 0 == version 1. Append only.
MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE reflections (
        reflection_id TEXT PRIMARY KEY,
        content       TEXT NOT NULL,
        kind          TEXT NOT NULL,
        generation    INTEGER NOT NULL DEFAULT 1,
        supersedes    TEXT,
        model         TEXT,
        metadata      TEXT NOT NULL DEFAULT '{}',
        created_at    TEXT NOT NULL
    );
    CREATE INDEX idx_reflections_kind ON reflections(kind, created_at);

    -- Provenance. No foreign key to a memories table: reflections live
    -- in their own database and must not depend on a memory row still
    -- existing. A pruned or forgotten memory leaves its ID behind here
    -- as an honest record of what the insight was drawn from at the
    -- time, rather than silently rewriting history.
    CREATE TABLE reflection_sources (
        reflection_id TEXT NOT NULL REFERENCES reflections(reflection_id) ON DELETE CASCADE,
        memory_id     TEXT NOT NULL,
        position      INTEGER NOT NULL,
        PRIMARY KEY (reflection_id, memory_id)
    );
    CREATE INDEX idx_reflection_sources_memory ON reflection_sources(memory_id);
    """,
)

SCHEMA_VERSION = len(MIGRATIONS)


def open_database(path: Path) -> sqlite3.Connection:
    """Open (creating and migrating as needed) the reflection database at `path`.

    Raises:
        ReflectionStoreError: If the database is newer than this code
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
        ReflectionStoreError: If the database is ahead of this code, or a
            migration script fails (the failed step is rolled back).
    """
    current = connection.execute("PRAGMA user_version").fetchone()[0]
    if current > SCHEMA_VERSION:
        raise ReflectionStoreError(
            f"Reflection database schema is version {current}, newer than the "
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
            raise ReflectionStoreError(
                f"Migration to schema version {version} failed: {exc}"
            ) from exc

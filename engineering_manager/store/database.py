"""SQLite connection management and schema migrations.

The schema is versioned through SQLite's `user_version` pragma: each
entry in `MIGRATIONS` is one version step, applied in order inside a
transaction. A database at version N gets migrations N+1..latest applied
the next time it is opened, so old databases upgrade automatically and
new schema changes are always additive migration scripts — never edits
to an existing entry.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from engineering_manager.exceptions import StoreError

# One SQL script per schema version, index 0 == version 1. Append only.
MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE projects (
        project_id  TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        root_path   TEXT NOT NULL,
        description TEXT,
        status      TEXT NOT NULL,
        created_at  TEXT NOT NULL
    );

    CREATE TABLE tasks (
        task_id     TEXT PRIMARY KEY,
        project_id  TEXT NOT NULL REFERENCES projects(project_id),
        title       TEXT NOT NULL,
        description TEXT,
        priority    INTEGER NOT NULL DEFAULT 0,
        depends_on  TEXT NOT NULL DEFAULT '[]',
        status      TEXT NOT NULL,
        created_at  TEXT NOT NULL
    );
    CREATE INDEX idx_tasks_project ON tasks(project_id);
    CREATE INDEX idx_tasks_status ON tasks(status);

    CREATE TABLE sessions (
        session_id   TEXT PRIMARY KEY,
        task_id      TEXT NOT NULL REFERENCES tasks(task_id),
        project_id   TEXT NOT NULL REFERENCES projects(project_id),
        provider_id  TEXT NOT NULL,
        account_id   TEXT NOT NULL,
        model        TEXT,
        external_ref TEXT,
        summary      TEXT,
        status       TEXT NOT NULL,
        started_at   TEXT NOT NULL,
        ended_at     TEXT
    );
    CREATE INDEX idx_sessions_task ON sessions(task_id);
    CREATE INDEX idx_sessions_status ON sessions(status);

    CREATE TABLE accounts (
        provider_id TEXT NOT NULL,
        account_id  TEXT NOT NULL,
        label       TEXT,
        PRIMARY KEY (provider_id, account_id)
    );

    CREATE TABLE event_log (
        event_id  TEXT PRIMARY KEY,
        name      TEXT NOT NULL,
        source    TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        payload   TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX idx_event_log_timestamp ON event_log(timestamp);
    """,
)

SCHEMA_VERSION = len(MIGRATIONS)


def open_database(path: Path) -> sqlite3.Connection:
    """Open (creating and migrating as needed) the database at `path`.

    Parent directories are created if missing. The returned connection
    has foreign-key enforcement on, WAL journaling for local-first
    durability, and `sqlite3.Row` rows.

    Raises:
        StoreError: If the database is newer than this code understands,
            or a migration fails.
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
        StoreError: If the database is ahead of this code, or a
            migration script fails (the failed step is rolled back).
    """
    current = connection.execute("PRAGMA user_version").fetchone()[0]
    if current > SCHEMA_VERSION:
        raise StoreError(
            f"Database schema is version {current}, newer than the supported "
            f"version {SCHEMA_VERSION}. Update the Engineering Manager."
        )

    for version in range(current + 1, SCHEMA_VERSION + 1):
        script = MIGRATIONS[version - 1]
        try:
            with connection:
                connection.executescript(script)
                # PRAGMA cannot be parameterized; `version` is an int from range().
                connection.execute(f"PRAGMA user_version = {version}")
        except sqlite3.Error as exc:
            raise StoreError(f"Migration to schema version {version} failed: {exc}") from exc

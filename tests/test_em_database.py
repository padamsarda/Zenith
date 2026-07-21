"""Tests for SQLite connection management and schema migrations."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from engineering_manager.exceptions import StoreError
from engineering_manager.store.database import MIGRATIONS, SCHEMA_VERSION, open_database


def test_open_database_creates_file_and_parents(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "dir" / "em.db"

    connection = open_database(path)
    connection.close()

    assert path.exists()


def test_open_database_applies_all_migrations(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "em.db")

    version = connection.execute("PRAGMA user_version").fetchone()[0]
    connection.close()

    assert version == SCHEMA_VERSION == len(MIGRATIONS)


def test_open_database_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "em.db"

    open_database(path).close()
    connection = open_database(path)
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    connection.close()

    assert version == SCHEMA_VERSION


def test_open_database_creates_expected_tables(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "em.db")

    names = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    connection.close()

    assert {"projects", "plans", "tasks", "sessions", "accounts", "event_log"} <= names


def test_version_one_database_upgrades_in_place(tmp_path: Path) -> None:
    """A database created before the execution engine gains the new
    schema — and keeps its data — the next time it is opened."""
    path = tmp_path / "em.db"
    connection = sqlite3.connect(path)
    connection.executescript(MIGRATIONS[0])
    connection.execute("PRAGMA user_version = 1")
    connection.execute(
        "INSERT INTO projects (project_id, name, root_path, status, created_at) "
        "VALUES ('zenith', 'Zenith', '.', 'ACTIVE', '2026-01-01T00:00:00+00:00')"
    )
    connection.commit()
    connection.close()

    upgraded = open_database(path)
    version = upgraded.execute("PRAGMA user_version").fetchone()[0]
    task_columns = {
        row["name"] for row in upgraded.execute("PRAGMA table_info(tasks)").fetchall()
    }
    session_columns = {
        row["name"] for row in upgraded.execute("PRAGMA table_info(sessions)").fetchall()
    }
    project = upgraded.execute("SELECT * FROM projects").fetchone()
    upgraded.close()

    assert version == SCHEMA_VERSION
    assert "plan_id" in task_columns
    assert "resume_at" in session_columns
    assert {"starting_revision", "ending_revision"} <= session_columns
    assert project["project_id"] == "zenith"


def test_version_two_database_gains_revision_columns_and_keeps_sessions(
    tmp_path: Path,
) -> None:
    """A database created before revision evidence gains the new columns
    — nullable, so sessions recorded without them still read back."""
    path = tmp_path / "em.db"
    connection = sqlite3.connect(path)
    connection.executescript(MIGRATIONS[0])
    connection.executescript(MIGRATIONS[1])
    connection.execute("PRAGMA user_version = 2")
    connection.execute(
        "INSERT INTO projects (project_id, name, root_path, status, created_at) "
        "VALUES ('zenith', 'Zenith', '.', 'ACTIVE', '2026-01-01T00:00:00+00:00')"
    )
    connection.execute(
        "INSERT INTO tasks (task_id, project_id, title, status, created_at) "
        "VALUES ('t1', 'zenith', 'Write docs', 'DONE', '2026-01-01T00:00:00+00:00')"
    )
    connection.execute(
        "INSERT INTO sessions (session_id, task_id, project_id, provider_id, "
        "account_id, status, started_at) "
        "VALUES ('s1', 't1', 'zenith', 'in-memory', 'personal', 'COMPLETED', "
        "'2026-01-01T00:00:00+00:00')"
    )
    connection.commit()
    connection.close()

    upgraded = open_database(path)
    version = upgraded.execute("PRAGMA user_version").fetchone()[0]
    session = upgraded.execute("SELECT * FROM sessions").fetchone()
    upgraded.close()

    assert version == SCHEMA_VERSION
    assert session["session_id"] == "s1"
    assert session["starting_revision"] is None
    assert session["ending_revision"] is None


def test_open_database_enforces_foreign_keys(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "em.db")

    enabled = connection.execute("PRAGMA foreign_keys").fetchone()[0]
    connection.close()

    assert enabled == 1


def test_open_database_rejects_newer_schema(tmp_path: Path) -> None:
    path = tmp_path / "em.db"
    connection = open_database(path)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    connection.close()

    with pytest.raises(StoreError):
        open_database(path)

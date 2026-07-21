"""Tests for SQLite connection management and schema migrations (conversations)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from runtime.conversation.sqlite.database import MIGRATIONS, SCHEMA_VERSION, open_database
from runtime.exceptions import ConversationStoreError


def test_open_database_creates_file_and_parents(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "dir" / "conversations.db"

    connection = open_database(path)
    connection.close()

    assert path.exists()


def test_open_database_applies_all_migrations(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "conversations.db")

    version = connection.execute("PRAGMA user_version").fetchone()[0]
    connection.close()

    assert version == SCHEMA_VERSION == len(MIGRATIONS)


def test_open_database_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "conversations.db"

    open_database(path).close()
    connection = open_database(path)
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    connection.close()

    assert version == SCHEMA_VERSION


def test_open_database_creates_expected_tables(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "conversations.db")

    names = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    connection.close()

    assert {"conversations", "messages"} <= names


def test_open_database_enforces_foreign_keys(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "conversations.db")

    enabled = connection.execute("PRAGMA foreign_keys").fetchone()[0]
    connection.close()

    assert enabled == 1


def test_open_database_uses_row_factory(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "conversations.db")

    row_factory = connection.row_factory
    connection.close()

    assert row_factory is sqlite3.Row


def test_open_database_rejects_newer_schema(tmp_path: Path) -> None:
    path = tmp_path / "conversations.db"
    connection = open_database(path)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    connection.close()

    with pytest.raises(ConversationStoreError):
        open_database(path)

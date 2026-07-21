"""SQLiteReflectionStore: the durable ReflectionStore."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from runtime.exceptions import ReflectionNotFoundError, ReflectionStoreError
from runtime.reflection.events import ReflectionCreated, ReflectionDeleted
from runtime.reflection.reflection import Reflection, ReflectionKind
from runtime.reflection.sqlite.database import open_database
from runtime.reflection.store import SOURCE, ReflectionStore
from runtime.reflection.validation import validate_reflection

if TYPE_CHECKING:
    from runtime.context import ApplicationContext

_COLUMNS = "reflection_id, content, kind, generation, supersedes, model, metadata, created_at"


class SQLiteReflectionStore(ReflectionStore):
    """Stores reflections and their provenance in SQLite.

    Not auto-wired: an integrator assigns an instance onto
    `context.reflections`, as `main.py` does. Kept in its own database
    file rather than beside memories, so that deleting or rebuilding the
    derived layer can never risk the raw one (ADR 0029).
    """

    def __init__(self, path: Path) -> None:
        """Open (creating and migrating as needed) the database at `path`.

        Raises:
            ReflectionStoreError: If the database cannot be opened or migrated.
        """
        self._connection = open_database(path)

    def close(self) -> None:
        """Close the underlying connection."""
        self._connection.close()

    def add(self, reflection: Reflection, application_context: ApplicationContext) -> Reflection:
        validate_reflection(reflection)
        try:
            with self._connection:
                self._connection.execute(
                    f"INSERT INTO reflections ({_COLUMNS}) "
                    "VALUES (:reflection_id, :content, :kind, :generation, :supersedes, "
                    ":model, :metadata, :created_at)",
                    {
                        "reflection_id": str(reflection.reflection_id),
                        "content": reflection.content,
                        "kind": reflection.kind.name,
                        "generation": reflection.generation,
                        "supersedes": (
                            str(reflection.supersedes) if reflection.supersedes else None
                        ),
                        "model": reflection.model,
                        "metadata": json.dumps(reflection.metadata),
                        "created_at": reflection.created_at.isoformat(),
                    },
                )
                self._connection.executemany(
                    "INSERT INTO reflection_sources (reflection_id, memory_id, position) "
                    "VALUES (?, ?, ?)",
                    [
                        (str(reflection.reflection_id), str(memory_id), position)
                        for position, memory_id in enumerate(reflection.source_memory_ids)
                    ],
                )
        except sqlite3.Error as exc:
            raise ReflectionStoreError(f"Failed to store reflection: {exc}") from exc

        application_context.events.emit(
            ReflectionCreated(
                source=SOURCE,
                payload={
                    "reflection_id": str(reflection.reflection_id),
                    "kind": reflection.kind.name,
                    "generation": reflection.generation,
                    "sources": reflection.source_count,
                },
            )
        )
        return reflection

    def get(self, reflection_id: UUID) -> Reflection:
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM reflections WHERE reflection_id = ?", (str(reflection_id),)
        ).fetchone()
        if row is None:
            raise ReflectionNotFoundError(f"Reflection '{reflection_id}' is not stored.")
        return self._build(row)

    def delete(self, reflection_id: UUID, application_context: ApplicationContext) -> None:
        self.get(reflection_id)
        try:
            with self._connection:
                # Provenance rows go with it via ON DELETE CASCADE.
                self._connection.execute(
                    "DELETE FROM reflections WHERE reflection_id = ?", (str(reflection_id),)
                )
        except sqlite3.Error as exc:
            raise ReflectionStoreError(f"Failed to delete reflection: {exc}") from exc

        application_context.events.emit(
            ReflectionDeleted(source=SOURCE, payload={"reflection_id": str(reflection_id)})
        )

    def list(
        self, *, kind: ReflectionKind | None = None, limit: int | None = None
    ) -> list[Reflection]:
        sql = f"SELECT {_COLUMNS} FROM reflections"
        parameters: list[object] = []
        if kind is not None:
            sql += " WHERE kind = ?"
            parameters.append(kind.name)
        sql += " ORDER BY created_at DESC"
        if limit is not None:
            sql += " LIMIT ?"
            parameters.append(limit)
        return [self._build(row) for row in self._connection.execute(sql, parameters).fetchall()]

    def latest(self, kind: ReflectionKind) -> Reflection | None:
        found = self.list(kind=kind, limit=1)
        return found[0] if found else None

    def _build(self, row: sqlite3.Row) -> Reflection:
        """Reconstruct a `Reflection`, including its provenance, from a row."""
        sources = self._connection.execute(
            "SELECT memory_id FROM reflection_sources WHERE reflection_id = ? ORDER BY position",
            (row["reflection_id"],),
        ).fetchall()
        return Reflection(
            content=row["content"],
            kind=ReflectionKind[row["kind"]],
            source_memory_ids=tuple(UUID(source["memory_id"]) for source in sources),
            generation=row["generation"],
            supersedes=UUID(row["supersedes"]) if row["supersedes"] else None,
            model=row["model"],
            metadata=json.loads(row["metadata"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            reflection_id=UUID(row["reflection_id"]),
        )

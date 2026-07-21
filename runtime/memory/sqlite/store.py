"""SQLiteMemoryStore: the durable MemoryStore, searched with FTS5/BM25."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from runtime.exceptions import MemoryNotFoundError, MemoryStoreError
from runtime.memory.events import MemoryForgotten, MemoryRemembered
from runtime.memory.matching import normalize_scores, tokenize
from runtime.memory.retrieval import MemoryCandidate
from runtime.memory.sqlite.database import open_database
from runtime.memory.sqlite.serialization import memory_from_row, memory_to_row
from runtime.memory.store import SOURCE, MemoryStore
from runtime.memory.validation import validate_memory
from shared.utils.time_utils import utc_now

if TYPE_CHECKING:
    from runtime.context import ApplicationContext
    from runtime.memory.memory import Memory
    from runtime.memory.temporal import TimeWindow

_COLUMNS = (
    "memory_id, content, kind, importance, pinned, tags, source, metadata, "
    "occurred_at, created_at, last_accessed_at, access_count"
)


class SQLiteMemoryStore(MemoryStore):
    """Stores memories in SQLite, ranked by FTS5's built-in BM25.

    The durable counterpart to `InMemoryMemoryStore`, structured exactly
    like `SQLiteConversationStore` (ADR 0018). Not auto-wired: an
    integrator assigns an instance onto `context.memory`, the same way
    every other real backend in this runtime is registered.

    Relevance comes from SQLite's own BM25 implementation rather than
    embeddings — good at names, identifiers, and exact terms, weaker at
    synonyms, and free of any dependency or second credential. ADR 0027
    records that tradeoff and the seam a future embedding backend would
    slot into.
    """

    def __init__(self, path: Path) -> None:
        """Open (creating and migrating as needed) the database at `path`.

        Raises:
            MemoryStoreError: If the database cannot be opened, migrated,
                or lacks FTS5.
        """
        self._connection = open_database(path)

    def close(self) -> None:
        """Close the underlying connection."""
        self._connection.close()

    def remember(self, memory: Memory, application_context: ApplicationContext) -> Memory:
        validate_memory(memory)
        row = memory_to_row(memory)
        placeholders = ", ".join(f":{column}" for column in row)
        try:
            with self._connection:
                self._connection.execute(
                    f"INSERT INTO memories ({', '.join(row)}) VALUES ({placeholders})", row
                )
        except sqlite3.Error as exc:
            raise MemoryStoreError(f"Failed to store memory: {exc}") from exc

        application_context.events.emit(
            MemoryRemembered(
                source=SOURCE,
                payload={
                    "memory_id": str(memory.memory_id),
                    "kind": memory.kind.name,
                    "importance": memory.importance,
                    "pinned": memory.pinned,
                },
            )
        )
        return memory

    def get(self, memory_id: UUID) -> Memory:
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM memories WHERE memory_id = ?", (str(memory_id),)
        ).fetchone()
        if row is None:
            raise MemoryNotFoundError(f"Memory '{memory_id}' is not stored.")
        return memory_from_row(row)

    def has(self, memory_id: UUID) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM memories WHERE memory_id = ?", (str(memory_id),)
        ).fetchone()
        return row is not None

    def forget(self, memory_id: UUID, application_context: ApplicationContext) -> None:
        self.get(memory_id)
        try:
            with self._connection:
                self._connection.execute(
                    "DELETE FROM memories WHERE memory_id = ?", (str(memory_id),)
                )
        except sqlite3.Error as exc:
            raise MemoryStoreError(f"Failed to forget memory: {exc}") from exc

        application_context.events.emit(
            MemoryForgotten(source=SOURCE, payload={"memory_id": str(memory_id)})
        )

    def search(
        self,
        query: str,
        *,
        window: TimeWindow | None = None,
        limit: int = 50,
    ) -> tuple[MemoryCandidate, ...]:
        tokens = tokenize(query)
        if not tokens:
            return self._window_only(window, limit)

        # Each token is quoted so FTS5 treats it as a literal string
        # rather than syntax — an unquoted token containing an operator
        # ("AND", "*", or a bare quote) is a query-syntax error, and user
        # text routinely contains those.
        match_expression = " OR ".join(f'"{token}"' for token in tokens)
        sql = (
            f"SELECT m.rowid, {', '.join(f'm.{c.strip()}' for c in _COLUMNS.split(','))}, "
            "bm25(memories_fts) AS rank_score "
            "FROM memories_fts JOIN memories m ON m.rowid = memories_fts.rowid "
            "WHERE memories_fts MATCH ?"
        )
        parameters: list[object] = [match_expression]
        if window is not None:
            sql += " AND m.occurred_at >= ? AND m.occurred_at < ?"
            parameters.extend([window.start.isoformat(), window.end.isoformat()])
        sql += " ORDER BY rank_score LIMIT ?"
        parameters.append(limit)

        try:
            rows = self._connection.execute(sql, parameters).fetchall()
        except sqlite3.Error as exc:
            raise MemoryStoreError(f"Memory search failed: {exc}") from exc
        if not rows:
            return ()

        # BM25 returns a negative score, more negative meaning a better
        # match; negate so larger is better, then min-max normalize into
        # the [0, 1] the retrieval policy expects from every backend.
        raw = [-float(row["rank_score"]) for row in rows]
        return tuple(
            MemoryCandidate(memory=memory_from_row(row), relevance=relevance)
            for row, relevance in zip(rows, normalize_scores(raw))
        )

    def _window_only(self, window: TimeWindow | None, limit: int) -> tuple[MemoryCandidate, ...]:
        """Candidates for an empty query: time filter only, zero relevance.

        Relevance of 0.0 across the board leaves the retrieval policy to
        rank on recency and importance alone, which is exactly right for
        a question that names a time but no subject.
        """
        sql = f"SELECT {_COLUMNS} FROM memories"
        parameters: list[object] = []
        if window is not None:
            sql += " WHERE occurred_at >= ? AND occurred_at < ?"
            parameters.extend([window.start.isoformat(), window.end.isoformat()])
        sql += " ORDER BY occurred_at DESC LIMIT ?"
        parameters.append(limit)

        rows = self._connection.execute(sql, parameters).fetchall()
        return tuple(
            MemoryCandidate(memory=memory_from_row(row), relevance=0.0) for row in rows
        )

    def touch(self, memories: tuple[Memory, ...], application_context: ApplicationContext) -> None:
        if not memories:
            return
        moment = utc_now().isoformat()
        try:
            with self._connection:
                self._connection.executemany(
                    "UPDATE memories SET last_accessed_at = ?, access_count = access_count + 1 "
                    "WHERE memory_id = ?",
                    [(moment, str(memory.memory_id)) for memory in memories],
                )
        except sqlite3.Error:
            # A recall observes work that already happened; failing to
            # record the access must never fail the request it came from
            # (the same rule ADR 0023 gives the Engineering Manager's
            # revision probe).
            pass

    def list(self) -> list[Memory]:
        rows = self._connection.execute(
            f"SELECT {_COLUMNS} FROM memories ORDER BY created_at DESC"
        ).fetchall()
        return [memory_from_row(row) for row in rows]

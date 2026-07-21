"""Converting Memory objects to and from SQLite rows."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any
from uuid import UUID

from runtime.memory.memory import Memory, MemoryKind


def memory_to_row(memory: Memory) -> dict[str, Any]:
    """Render `memory` as a column mapping for the `memories` table."""
    return {
        "memory_id": str(memory.memory_id),
        "content": memory.content,
        "kind": memory.kind.name,
        "importance": memory.importance,
        "pinned": int(memory.pinned),
        "tags": json.dumps(list(memory.tags)),
        "source": memory.source,
        "metadata": json.dumps(memory.metadata),
        "occurred_at": memory.occurred_at.isoformat(),
        "created_at": memory.created_at.isoformat(),
        "last_accessed_at": memory.last_accessed_at.isoformat(),
        "access_count": memory.access_count,
    }


def memory_from_row(row: sqlite3.Row) -> Memory:
    """Reconstruct a `Memory` from a `memories` row."""
    return Memory(
        content=row["content"],
        kind=MemoryKind[row["kind"]],
        importance=row["importance"],
        pinned=bool(row["pinned"]),
        tags=tuple(json.loads(row["tags"])),
        source=row["source"],
        metadata=json.loads(row["metadata"]),
        occurred_at=datetime.fromisoformat(row["occurred_at"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        last_accessed_at=datetime.fromisoformat(row["last_accessed_at"]),
        access_count=row["access_count"],
        memory_id=UUID(row["memory_id"]),
    )

"""Memory: one durable thing Zeni knows, and the kinds it distinguishes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any
from uuid import UUID

from shared.utils.time_utils import utc_now
from shared.utils.uuid_utils import generate_id

MIN_IMPORTANCE = 1
MAX_IMPORTANCE = 10
DEFAULT_IMPORTANCE = 5


class MemoryKind(Enum):
    """What sort of thing a memory holds.

    Retrieval treats these identically today; they exist so a caller can
    filter ("what are my preferences?") and so importance heuristics can
    differ by kind without re-parsing content.
    """

    FACT = auto()
    """Something true about the user or their world."""

    PREFERENCE = auto()
    """How the user likes things done."""

    DECISION = auto()
    """Something concluded, with reasoning worth preserving."""

    EVENT = auto()
    """Something that happened at a particular time."""

    TASK = auto()
    """Unfinished work to be picked back up."""


@dataclass(frozen=True)
class Memory:
    """One durable thing Zeni knows.

    Deliberately **bi-temporal**, the property that makes "what did we
    decide yesterday" answerable: `occurred_at` is when the remembered
    thing happened, `created_at` is when it was written down. They differ
    whenever something is recorded after the fact, and conflating them
    silently mis-answers every relative-time question — the single
    highest-impact finding from the long-term-memory benchmarks this
    design draws on (ADR 0027).

    `last_accessed_at` and `access_count` are updated by the store on
    recall, so recency reflects genuine use rather than only creation.
    They are the one part of a memory that changes; everything else is
    immutable, and a correction is a new memory superseding an old one.
    """

    content: str
    kind: MemoryKind = MemoryKind.FACT
    importance: int = DEFAULT_IMPORTANCE
    pinned: bool = False
    tags: tuple[str, ...] = ()
    source: str = "assistant"
    metadata: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=utc_now)
    created_at: datetime = field(default_factory=utc_now)
    last_accessed_at: datetime = field(default_factory=utc_now)
    access_count: int = 0
    memory_id: UUID = field(default_factory=generate_id)

    def accessed(self, at: datetime | None = None) -> Memory:
        """Return a copy marked as recalled at `at` (defaults to now)."""
        moment = at or utc_now()
        return Memory(
            content=self.content,
            kind=self.kind,
            importance=self.importance,
            pinned=self.pinned,
            tags=self.tags,
            source=self.source,
            metadata=dict(self.metadata),
            occurred_at=self.occurred_at,
            created_at=self.created_at,
            last_accessed_at=moment,
            access_count=self.access_count + 1,
            memory_id=self.memory_id,
        )

    def __str__(self) -> str:
        return self.content

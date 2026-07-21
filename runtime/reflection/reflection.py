"""Reflection: an insight derived from memories, and the memories it came from."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any
from uuid import UUID

from shared.utils.time_utils import utc_now
from shared.utils.uuid_utils import generate_id

FIRST_GENERATION = 1


class ReflectionKind(Enum):
    """Which of the three reflection levels produced this (ADR 0029)."""

    SESSION = auto()
    """A summary of one conversation, written when it ended."""

    DEEP = auto()
    """A periodic synthesis across accumulated memories and time."""

    ON_DEMAND = auto()
    """A fresh analysis produced because the user asked a question."""


@dataclass(frozen=True)
class Reflection:
    """One derived insight, and a record of exactly what produced it.

    A reflection is a **separate layer above memories, never a
    replacement for them** (ADR 0029). Raw memories stay immutable and
    untouched: reflection only ever reads them and writes something new
    alongside. That is what makes a wrong reflection a recoverable
    mistake — delete it and the evidence it was drawn from is still
    there, unaltered.

    `source_memory_ids` is the provenance requirement made concrete:
    every insight carries the IDs of the memories it was derived from,
    so "why does Zeni think this about me" is always answerable by
    looking them up rather than trusting the sentence.

    `generation` and `supersedes` make the series traceable. A new DEEP
    reflection does not overwrite the last one; it is stored as the next
    generation, pointing back at the one it replaces, so the whole
    history of how Zeni's understanding evolved stays readable.
    """

    content: str
    kind: ReflectionKind = ReflectionKind.SESSION
    source_memory_ids: tuple[UUID, ...] = ()
    generation: int = FIRST_GENERATION
    supersedes: UUID | None = None
    model: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    reflection_id: UUID = field(default_factory=generate_id)

    @property
    def source_count(self) -> int:
        """How many memories this insight was drawn from."""
        return len(self.source_memory_ids)

    def __str__(self) -> str:
        return self.content

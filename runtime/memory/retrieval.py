"""How candidate memories are scored and ranked for recall.

Implements the composite retrieval score established by Stanford's
Generative Agents work and since adopted (in varying forms) by most
production memory systems: a memory's usefulness right now is a weighted
sum of how *recently* it mattered, how *important* it is, and how
*relevant* it is to what was just asked. None of the three alone is
sufficient — recency alone forgets what matters, importance alone
ignores the question, relevance alone surfaces stale trivia (ADR 0027).

The relevance term is supplied by the `MemoryStore`, since how text is
matched is backend-specific (SQLite FTS5's BM25, a token overlap, a
vector similarity later); everything in this module is backend-agnostic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from runtime.memory.memory import MAX_IMPORTANCE, Memory

DEFAULT_HALF_LIFE_HOURS = 72.0
DEFAULT_RECENCY_WEIGHT = 1.0
DEFAULT_IMPORTANCE_WEIGHT = 1.0
DEFAULT_RELEVANCE_WEIGHT = 2.0

# A pinned memory's recency never decays below this. Explicitly telling
# an assistant "remember this" is a strong, deliberate signal, and a
# months-old pinned fact whose recency term had decayed to ~0 would need
# an overwhelming relevance match just to re-surface — exactly the
# failure a user reads as "it forgot what I told it to remember".
PINNED_RECENCY_FLOOR = 0.6


@dataclass(frozen=True)
class ScoredMemory:
    """One candidate memory with its component scores and final ranking score.

    The components are kept rather than collapsed into `score` alone so a
    caller can explain *why* something was recalled — which is the
    difference between a memory system that can be debugged and one that
    can only be trusted.
    """

    memory: Memory
    score: float
    recency: float
    importance: float
    relevance: float


@dataclass(frozen=True)
class MemoryCandidate:
    """A memory a store matched, with that store's own relevance score.

    `relevance` is expected in `[0.0, 1.0]`, already normalized by the
    store against the rest of the candidate set.
    """

    memory: Memory
    relevance: float


class MemoryRetrievalPolicy(ABC):
    """Ranks candidate memories for a request.

    The memory subsystem's policy seam, the same shape as
    `PermissionPolicy` here and `AssignmentPolicy`/`RetryPolicy` in the
    Engineering Manager: swapping the class changes what gets recalled
    without touching the store, the assembler, or the pipeline.
    """

    @abstractmethod
    def rank(
        self, candidates: tuple[MemoryCandidate, ...], now: datetime, limit: int
    ) -> tuple[ScoredMemory, ...]:
        """Return the best `limit` candidates, highest score first."""


class RecencyImportanceRelevancePolicy(MemoryRetrievalPolicy):
    """The composite recency + importance + relevance score.

    Recency decays exponentially from `last_accessed_at` with a
    configurable half-life, so a memory that keeps being useful stays
    fresh while one that never comes up fades — the behavior that makes
    "what was I working on" answer with current work rather than
    everything ever recorded.
    """

    def __init__(
        self,
        *,
        half_life_hours: float = DEFAULT_HALF_LIFE_HOURS,
        recency_weight: float = DEFAULT_RECENCY_WEIGHT,
        importance_weight: float = DEFAULT_IMPORTANCE_WEIGHT,
        relevance_weight: float = DEFAULT_RELEVANCE_WEIGHT,
    ) -> None:
        """Create the policy.

        Args:
            half_life_hours: How long until an untouched memory's recency
                term halves. The default (72h) keeps roughly the last few
                days strongly weighted without erasing last month.
            recency_weight: Weight of the recency term.
            importance_weight: Weight of the importance term.
            relevance_weight: Weight of the relevance term. Defaults
                highest: what was actually asked should outrank what is
                merely recent or merely important.
        """
        self._half_life_hours = half_life_hours
        self._recency_weight = recency_weight
        self._importance_weight = importance_weight
        self._relevance_weight = relevance_weight

    def rank(
        self, candidates: tuple[MemoryCandidate, ...], now: datetime, limit: int
    ) -> tuple[ScoredMemory, ...]:
        """Score every candidate and return the top `limit`, best first."""
        scored = [self._score(candidate, now) for candidate in candidates]
        scored.sort(key=lambda item: (item.score, item.memory.created_at), reverse=True)
        return tuple(scored[:limit]) if limit > 0 else ()

    def _score(self, candidate: MemoryCandidate, now: datetime) -> ScoredMemory:
        """Combine one candidate's three component scores into a final score."""
        recency = self._recency(candidate.memory, now)
        importance = candidate.memory.importance / MAX_IMPORTANCE
        relevance = candidate.relevance
        score = (
            self._recency_weight * recency
            + self._importance_weight * importance
            + self._relevance_weight * relevance
        )
        return ScoredMemory(
            memory=candidate.memory,
            score=score,
            recency=recency,
            importance=importance,
            relevance=relevance,
        )

    def _recency(self, memory: Memory, now: datetime) -> float:
        """Exponentially decayed recency in `[0, 1]`, floored for pinned memories."""
        age_hours = max((now - memory.last_accessed_at).total_seconds() / 3600.0, 0.0)
        decayed = 0.5 ** (age_hours / self._half_life_hours)
        if memory.pinned:
            return max(decayed, PINNED_RECENCY_FLOOR)
        return decayed

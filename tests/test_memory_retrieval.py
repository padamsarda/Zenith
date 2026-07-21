"""Tests for memory retrieval scoring."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from runtime.memory.memory import Memory
from runtime.memory.retrieval import (
    PINNED_RECENCY_FLOOR,
    MemoryCandidate,
    RecencyImportanceRelevancePolicy,
)

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)


def candidate(
    content: str = "a memory",
    *,
    relevance: float = 0.5,
    importance: int = 5,
    age_hours: float = 0.0,
    pinned: bool = False,
) -> MemoryCandidate:
    accessed = NOW - timedelta(hours=age_hours)
    return MemoryCandidate(
        memory=Memory(
            content=content,
            importance=importance,
            pinned=pinned,
            occurred_at=accessed,
            created_at=accessed,
            last_accessed_at=accessed,
        ),
        relevance=relevance,
    )


# --- recency ----------------------------------------------------------------


def test_recency_is_one_for_a_just_accessed_memory() -> None:
    policy = RecencyImportanceRelevancePolicy()

    ranked = policy.rank((candidate(age_hours=0.0),), NOW, 1)

    assert ranked[0].recency == 1.0


def test_recency_halves_after_one_half_life() -> None:
    policy = RecencyImportanceRelevancePolicy(half_life_hours=24.0)

    ranked = policy.rank((candidate(age_hours=24.0),), NOW, 1)

    assert ranked[0].recency == 0.5


def test_recency_keeps_decaying() -> None:
    policy = RecencyImportanceRelevancePolicy(half_life_hours=24.0)

    ranked = policy.rank((candidate(age_hours=48.0),), NOW, 1)

    assert ranked[0].recency == 0.25


def test_pinned_memory_recency_never_falls_below_the_floor() -> None:
    policy = RecencyImportanceRelevancePolicy(half_life_hours=1.0)

    ranked = policy.rank((candidate(age_hours=10000.0, pinned=True),), NOW, 1)

    assert ranked[0].recency == PINNED_RECENCY_FLOOR


def test_unpinned_memory_decays_far_below_the_floor() -> None:
    policy = RecencyImportanceRelevancePolicy(half_life_hours=1.0)

    ranked = policy.rank((candidate(age_hours=1000.0),), NOW, 1)

    assert ranked[0].recency < PINNED_RECENCY_FLOOR


# --- ranking ----------------------------------------------------------------


def test_more_relevant_memory_outranks_more_recent_one() -> None:
    # Relevance is weighted highest on purpose: what was asked should
    # beat what merely happened lately.
    policy = RecencyImportanceRelevancePolicy()
    relevant_but_old = candidate("relevant", relevance=1.0, age_hours=200.0)
    recent_but_irrelevant = candidate("recent", relevance=0.0, age_hours=0.0)

    ranked = policy.rank((recent_but_irrelevant, relevant_but_old), NOW, 2)

    assert ranked[0].memory.content == "relevant"


def test_importance_breaks_a_tie() -> None:
    policy = RecencyImportanceRelevancePolicy()
    important = candidate("important", importance=10)
    trivial = candidate("trivial", importance=1)

    ranked = policy.rank((trivial, important), NOW, 2)

    assert ranked[0].memory.content == "important"


def test_pinned_old_memory_still_surfaces_against_a_fresh_one() -> None:
    # The behavior a user reads as "it remembered what I told it to".
    policy = RecencyImportanceRelevancePolicy()
    pinned_old = candidate("pinned", relevance=0.8, importance=10, age_hours=5000.0, pinned=True)
    fresh_noise = candidate("noise", relevance=0.2, importance=3, age_hours=0.0)

    ranked = policy.rank((fresh_noise, pinned_old), NOW, 2)

    assert ranked[0].memory.content == "pinned"


def test_rank_respects_the_limit() -> None:
    policy = RecencyImportanceRelevancePolicy()
    candidates = tuple(candidate(f"m{index}") for index in range(10))

    assert len(policy.rank(candidates, NOW, 3)) == 3


def test_zero_limit_returns_nothing() -> None:
    policy = RecencyImportanceRelevancePolicy()

    assert policy.rank((candidate(),), NOW, 0) == ()


def test_no_candidates_returns_nothing() -> None:
    policy = RecencyImportanceRelevancePolicy()

    assert policy.rank((), NOW, 5) == ()


def test_components_are_reported_for_explainability() -> None:
    policy = RecencyImportanceRelevancePolicy()

    scored = policy.rank((candidate(relevance=0.5, importance=10),), NOW, 1)[0]

    assert scored.relevance == 0.5
    assert scored.importance == 1.0
    assert scored.recency == 1.0
    assert scored.score == scored.recency + scored.importance + 2.0 * scored.relevance


def test_weights_change_the_ordering() -> None:
    relevant = candidate("relevant", relevance=1.0, importance=1, age_hours=0.0)
    important = candidate("important", relevance=0.0, importance=10, age_hours=0.0)

    relevance_first = RecencyImportanceRelevancePolicy().rank((important, relevant), NOW, 2)
    importance_first = RecencyImportanceRelevancePolicy(
        relevance_weight=0.1, importance_weight=5.0
    ).rank((important, relevant), NOW, 2)

    assert relevance_first[0].memory.content == "relevant"
    assert importance_first[0].memory.content == "important"


def test_future_timestamp_does_not_exceed_full_recency() -> None:
    # Clock skew must not produce a recency above 1.0 and let a memory
    # outrank everything by arithmetic accident.
    policy = RecencyImportanceRelevancePolicy()

    ranked = policy.rank((candidate(age_hours=-100.0),), NOW, 1)

    assert ranked[0].recency == 1.0

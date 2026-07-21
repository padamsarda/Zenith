"""Tests for memory consolidation and pruning."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest

from configs.config import Config
from runtime.context import ApplicationContext
from runtime.memory.consolidation import (
    ConsolidationAction,
    LexicalConsolidationPolicy,
    MemoryConsolidator,
)
from runtime.memory.memory import MAX_IMPORTANCE, Memory, MemoryKind
from runtime.memory.store import MemoryStore

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)


def make_context() -> ApplicationContext:
    return ApplicationContext(config=Config(), logger=logging.getLogger("test.consolidation"))


def make_memory(content: str, *, days_ago: float = 0.0, **kwargs) -> Memory:
    moment = NOW - timedelta(days=days_ago)
    return Memory(
        content=content,
        occurred_at=moment,
        created_at=moment,
        last_accessed_at=moment,
        **kwargs,
    )


# --- the policy ----------------------------------------------------------------


def test_nothing_existing_means_add() -> None:
    decision = LexicalConsolidationPolicy().decide(make_memory("anything at all"), ())

    assert decision.action is ConsolidationAction.ADD


def test_unrelated_memory_is_added() -> None:
    existing = (make_memory("The CubeSat battery is an 18650 lithium pack"),)

    decision = LexicalConsolidationPolicy().decide(
        make_memory("I prefer metric units in calculations"), existing
    )

    assert decision.action is ConsolidationAction.ADD


def test_near_identical_restatement_reinforces() -> None:
    existing = (make_memory("The CubeSat battery is an 18650 lithium pack"),)

    decision = LexicalConsolidationPolicy().decide(
        make_memory("The CubeSat battery is an 18650 lithium pack"), existing
    )

    assert decision.action is ConsolidationAction.REINFORCE
    assert decision.existing is existing[0]


def test_similar_but_distinct_facts_are_both_kept() -> None:
    # Two real facts about the same subject must not merge — losing one
    # is far worse than keeping both.
    existing = (make_memory("The CubeSat battery is an 18650 lithium pack"),)

    decision = LexicalConsolidationPolicy().decide(
        make_memory("The CubeSat antenna deploys thirty minutes after launch"), existing
    )

    assert decision.action is ConsolidationAction.ADD


def test_explicit_correction_supersedes() -> None:
    existing = (make_memory("The CubeSat battery is an 18650 lithium pack"),)

    decision = LexicalConsolidationPolicy().decide(
        make_memory("actually the CubeSat battery is LiFePO4 now"), existing
    )

    assert decision.action is ConsolidationAction.SUPERSEDE
    assert decision.existing is existing[0]


def test_correction_of_something_unknown_is_just_added() -> None:
    # "actually" about a topic never discussed supersedes nothing.
    existing = (make_memory("I prefer metric units"),)

    decision = LexicalConsolidationPolicy().decide(
        make_memory("actually the antenna is a dipole"), existing
    )

    assert decision.action is ConsolidationAction.ADD


def test_similarity_alone_never_supersedes() -> None:
    # The load-bearing safety property: without a correction marker, two
    # similar statements both survive.
    existing = (make_memory("The CubeSat battery is an 18650 lithium pack"),)

    decision = LexicalConsolidationPolicy().decide(
        make_memory("The CubeSat battery is a LiFePO4 pack"), existing
    )

    assert decision.action is not ConsolidationAction.SUPERSEDE


def test_best_match_is_chosen_among_several() -> None:
    existing = (
        make_memory("I prefer metric units"),
        make_memory("The CubeSat battery is an 18650 lithium pack"),
        make_memory("The launch window opens in March"),
    )

    decision = LexicalConsolidationPolicy().decide(
        make_memory("The CubeSat battery is an 18650 lithium pack"), existing
    )

    assert decision.existing is existing[1]


# --- the consolidator ----------------------------------------------------------------


def test_store_adds_a_new_memory() -> None:
    context = make_context()

    MemoryConsolidator().store(make_memory("The CubeSat battery is lithium"), context, now=NOW)

    assert len(context.memory.list()) == 1


def test_repeated_statement_does_not_duplicate() -> None:
    context = make_context()
    consolidator = MemoryConsolidator()
    text = "The CubeSat battery is an 18650 lithium pack"

    for _ in range(3):
        consolidator.store(make_memory(text), context, now=NOW)

    assert len(context.memory.list()) == 1


def test_reinforcement_raises_importance() -> None:
    context = make_context()
    consolidator = MemoryConsolidator()
    text = "The CubeSat battery is an 18650 lithium pack"
    consolidator.store(make_memory(text, importance=5), context, now=NOW)

    consolidator.store(make_memory(text, importance=5), context, now=NOW)

    assert context.memory.list()[0].importance == 6


def test_reinforcement_is_capped_at_the_maximum() -> None:
    context = make_context()
    consolidator = MemoryConsolidator()
    text = "The CubeSat battery is an 18650 lithium pack"
    consolidator.store(make_memory(text, importance=MAX_IMPORTANCE), context, now=NOW)

    consolidator.store(make_memory(text), context, now=NOW)

    assert context.memory.list()[0].importance == MAX_IMPORTANCE


def test_reinforcement_refreshes_occurred_at() -> None:
    # Restating a fact makes it current as of now, not only as of the
    # first time it was said.
    context = make_context()
    consolidator = MemoryConsolidator()
    text = "The CubeSat battery is an 18650 lithium pack"
    consolidator.store(make_memory(text, days_ago=30), context, now=NOW)

    consolidator.store(make_memory(text), context, now=NOW)

    assert context.memory.list()[0].occurred_at == NOW


def test_correction_replaces_the_old_memory() -> None:
    context = make_context()
    consolidator = MemoryConsolidator()
    consolidator.store(
        make_memory("The CubeSat battery is an 18650 lithium pack"), context, now=NOW
    )

    consolidator.store(
        make_memory("actually the CubeSat battery is LiFePO4 now"), context, now=NOW
    )

    stored = context.memory.list()
    assert len(stored) == 1
    assert "LiFePO4" in stored[0].content


def test_store_returns_the_decision_taken() -> None:
    context = make_context()
    consolidator = MemoryConsolidator()
    text = "The CubeSat battery is an 18650 lithium pack"
    consolidator.store(make_memory(text), context, now=NOW)

    decision = consolidator.store(make_memory(text), context, now=NOW)

    assert decision.action is ConsolidationAction.REINFORCE


def test_a_failing_policy_falls_back_to_storing_plainly() -> None:
    # An unconsolidated memory is a much smaller problem than a lost one.
    class BrokenPolicy(LexicalConsolidationPolicy):
        def decide(self, candidate, existing):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

    context = make_context()

    MemoryConsolidator(policy=BrokenPolicy()).store(
        make_memory("The CubeSat battery is lithium"), context, now=NOW
    )

    assert len(context.memory.list()) == 1


def test_a_failing_search_falls_back_to_storing_plainly() -> None:
    class HalfBrokenStore(MemoryStore):
        def __init__(self) -> None:
            self.stored: list[Memory] = []

        def remember(self, memory, application_context):  # type: ignore[no-untyped-def]
            self.stored.append(memory)
            return memory

        def search(self, query, *, window=None, limit=50):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

        def get(self, memory_id): ...  # type: ignore[no-untyped-def]
        def has(self, memory_id): ...  # type: ignore[no-untyped-def]
        def update(self, memory, application_context): ...  # type: ignore[no-untyped-def]
        def forget(self, memory_id, application_context): ...  # type: ignore[no-untyped-def]
        def touch(self, memories, application_context): ...  # type: ignore[no-untyped-def]
        def list(self):  # type: ignore[no-untyped-def]
            return list(self.stored)

    context = make_context()
    context.memory = HalfBrokenStore()

    MemoryConsolidator().store(make_memory("The CubeSat battery is lithium"), context, now=NOW)

    assert len(context.memory.list()) == 1


# --- pruning ----------------------------------------------------------------


def prune_fixture(context: ApplicationContext) -> None:
    """Store one memory of each interesting shape for pruning."""
    context.memory.remember(
        make_memory("old unused trivia", days_ago=200, importance=3), context
    )
    context.memory.remember(
        make_memory("old but pinned", days_ago=200, importance=3, pinned=True), context
    )
    context.memory.remember(
        make_memory("old but important", days_ago=200, importance=9), context
    )
    context.memory.remember(
        make_memory("old but used", days_ago=200, importance=3, access_count=4), context
    )
    context.memory.remember(make_memory("recent trivia", days_ago=1, importance=3), context)


def test_prune_removes_only_old_unused_unimportant_unpinned() -> None:
    context = make_context()
    prune_fixture(context)

    pruned = MemoryConsolidator().prune(context, now=NOW)

    assert [memory.content for memory in pruned] == ["old unused trivia"]


def test_prune_keeps_everything_else() -> None:
    context = make_context()
    prune_fixture(context)

    MemoryConsolidator().prune(context, now=NOW)

    remaining = {memory.content for memory in context.memory.list()}
    assert remaining == {"old but pinned", "old but important", "old but used", "recent trivia"}


def test_prune_with_nothing_eligible_removes_nothing() -> None:
    context = make_context()
    context.memory.remember(make_memory("recent and useful", importance=8), context)

    assert MemoryConsolidator().prune(context, now=NOW) == ()


def test_prune_age_threshold_is_respected() -> None:
    context = make_context()
    context.memory.remember(make_memory("thirty days old", days_ago=30, importance=2), context)

    assert MemoryConsolidator().prune(context, older_than_days=90, now=NOW) == ()
    assert len(MemoryConsolidator().prune(context, older_than_days=10, now=NOW)) == 1


def test_prune_importance_threshold_is_respected() -> None:
    context = make_context()
    context.memory.remember(make_memory("old mid-importance", days_ago=200, importance=6), context)

    assert MemoryConsolidator().prune(context, max_importance=4, now=NOW) == ()
    assert len(MemoryConsolidator().prune(context, max_importance=6, now=NOW)) == 1


@pytest.mark.parametrize("kind", list(MemoryKind))
def test_prune_does_not_discriminate_by_kind(kind: MemoryKind) -> None:
    # Kind carries no protection; the four criteria are the whole rule.
    context = make_context()
    context.memory.remember(
        make_memory("old unused trivia", days_ago=200, importance=2, kind=kind), context
    )

    assert len(MemoryConsolidator().prune(context, now=NOW)) == 1

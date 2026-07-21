"""Tests for MemoryStore implementations.

Both backends are driven through the same parametrized cases: the
in-memory store is only a useful test double if it behaves like the
durable one, so any divergence should fail here rather than surface in
production.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from configs.config import Config
from runtime.context import ApplicationContext
from runtime.exceptions import MemoryNotFoundError, MemoryValidationError
from runtime.memory.events import MemoryForgotten, MemoryRemembered, MemoryUpdated
from runtime.memory.in_memory_store import InMemoryMemoryStore
from runtime.memory.memory import Memory, MemoryKind
from runtime.memory.sqlite.store import SQLiteMemoryStore
from runtime.memory.store import MemoryStore
from runtime.memory.temporal import TimeWindow
from shared.events.event import Event

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)


def make_context() -> ApplicationContext:
    return ApplicationContext(config=Config(), logger=logging.getLogger("test.memory"))


@pytest.fixture(params=["in_memory", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[MemoryStore]:
    if request.param == "in_memory":
        yield InMemoryMemoryStore()
        return
    sqlite_store = SQLiteMemoryStore(tmp_path / "memory.db")
    try:
        yield sqlite_store
    finally:
        sqlite_store.close()


def make_memory(content: str = "The CubeSat uses 18650 lithium cells", **kwargs) -> Memory:
    defaults = {"occurred_at": NOW, "created_at": NOW, "last_accessed_at": NOW}
    return Memory(content=content, **{**defaults, **kwargs})


# --- remember / get / has ----------------------------------------------------------------


def test_remember_stores_and_returns(store: MemoryStore) -> None:
    context = make_context()
    memory = make_memory()

    stored = store.remember(memory, context)

    assert stored.memory_id == memory.memory_id
    assert store.has(memory.memory_id)
    assert store.get(memory.memory_id).content == memory.content


def test_remember_emits_event(store: MemoryStore) -> None:
    context = make_context()
    received: list[Event] = []
    context.events.subscribe(MemoryRemembered, received.append)

    store.remember(make_memory(pinned=True), context)

    assert len(received) == 1
    assert received[0].payload["pinned"] is True


def test_remember_rejects_invalid_memory(store: MemoryStore) -> None:
    with pytest.raises(MemoryValidationError):
        store.remember(make_memory(content="   "), make_context())


def test_remember_rejects_out_of_range_importance(store: MemoryStore) -> None:
    with pytest.raises(MemoryValidationError):
        store.remember(make_memory(importance=99), make_context())


def test_get_missing_raises(store: MemoryStore) -> None:
    from shared.utils.uuid_utils import generate_id

    with pytest.raises(MemoryNotFoundError):
        store.get(generate_id())


def test_has_is_false_for_unknown(store: MemoryStore) -> None:
    from shared.utils.uuid_utils import generate_id

    assert store.has(generate_id()) is False


# --- update ----------------------------------------------------------------


def test_update_replaces_the_stored_memory(store: MemoryStore) -> None:
    context = make_context()
    memory = store.remember(make_memory("original", importance=5), context)

    store.update(memory.reinforced(NOW + timedelta(days=1)), context)

    refreshed = store.get(memory.memory_id)
    assert refreshed.importance == 6
    assert refreshed.occurred_at == NOW + timedelta(days=1)


def test_update_emits_event(store: MemoryStore) -> None:
    context = make_context()
    memory = store.remember(make_memory(), context)
    received: list[Event] = []
    context.events.subscribe(MemoryUpdated, received.append)

    store.update(memory.reinforced(), context)

    assert len(received) == 1


def test_update_of_unknown_memory_raises(store: MemoryStore) -> None:
    with pytest.raises(MemoryNotFoundError):
        store.update(make_memory("never stored"), make_context())


def test_update_rejects_an_invalid_memory(store: MemoryStore) -> None:
    context = make_context()
    memory = store.remember(make_memory(), context)
    broken = Memory(
        content="fine",
        importance=99,
        memory_id=memory.memory_id,
        occurred_at=NOW,
        created_at=NOW,
        last_accessed_at=NOW,
    )

    with pytest.raises(MemoryValidationError):
        store.update(broken, context)


def test_updated_content_is_searchable(store: MemoryStore) -> None:
    # The FTS index must follow an update, or search silently returns
    # stale results for the durable backend.
    context = make_context()
    memory = store.remember(make_memory("the antenna is a dipole"), context)
    replaced = Memory(
        content="the antenna is a monopole whip",
        memory_id=memory.memory_id,
        occurred_at=NOW,
        created_at=NOW,
        last_accessed_at=NOW,
    )

    store.update(replaced, context)

    assert store.search("dipole") == ()
    assert len(store.search("monopole whip")) == 1


# --- forget ----------------------------------------------------------------


def test_forget_removes(store: MemoryStore) -> None:
    context = make_context()
    memory = store.remember(make_memory(), context)

    store.forget(memory.memory_id, context)

    assert not store.has(memory.memory_id)


def test_forget_emits_event(store: MemoryStore) -> None:
    context = make_context()
    memory = store.remember(make_memory(), context)
    received: list[Event] = []
    context.events.subscribe(MemoryForgotten, received.append)

    store.forget(memory.memory_id, context)

    assert len(received) == 1


def test_forget_missing_raises(store: MemoryStore) -> None:
    from shared.utils.uuid_utils import generate_id

    with pytest.raises(MemoryNotFoundError):
        store.forget(generate_id(), make_context())


# --- search ----------------------------------------------------------------


def test_search_finds_by_keyword(store: MemoryStore) -> None:
    context = make_context()
    store.remember(make_memory("The CubeSat uses 18650 lithium cells"), context)
    store.remember(make_memory("I prefer dark mode in every editor"), context)

    results = store.search("cubesat battery cells")

    assert len(results) == 1
    assert "18650" in results[0].memory.content


def test_search_relevance_is_normalized(store: MemoryStore) -> None:
    context = make_context()
    store.remember(make_memory("The CubeSat battery is lithium"), context)
    store.remember(make_memory("The CubeSat antenna is deployable"), context)

    results = store.search("cubesat battery")

    assert results
    assert all(0.0 <= candidate.relevance <= 1.0 for candidate in results)


def test_search_with_no_match_returns_nothing(store: MemoryStore) -> None:
    store.remember(make_memory("The CubeSat uses lithium cells"), make_context())

    assert store.search("kubernetes ingress controller") == ()


def test_search_respects_time_window(store: MemoryStore) -> None:
    context = make_context()
    store.remember(make_memory("CubeSat battery decision", occurred_at=NOW), context)
    store.remember(
        make_memory("CubeSat battery earlier note", occurred_at=NOW - timedelta(days=30)),
        context,
    )

    window = TimeWindow(start=NOW - timedelta(days=1), end=NOW + timedelta(days=1))
    results = store.search("cubesat battery", window=window)

    assert len(results) == 1
    assert "decision" in results[0].memory.content


def test_empty_query_returns_window_candidates(store: MemoryStore) -> None:
    context = make_context()
    store.remember(make_memory("Something from today", occurred_at=NOW), context)
    store.remember(
        make_memory("Something old", occurred_at=NOW - timedelta(days=90)), context
    )

    window = TimeWindow(start=NOW - timedelta(days=1), end=NOW + timedelta(days=1))
    results = store.search("the and of", window=window)

    assert len(results) == 1
    assert results[0].relevance == 0.0


def test_search_handles_fts_operator_characters(store: MemoryStore) -> None:
    # Query text containing FTS5 syntax must be treated as literal words,
    # not as query operators — otherwise ordinary user phrasing errors out.
    store.remember(make_memory("The CubeSat battery is lithium"), make_context())

    assert store.search('cubesat AND "battery* OR') is not None


def test_search_limit_is_respected(store: MemoryStore) -> None:
    context = make_context()
    for index in range(10):
        store.remember(make_memory(f"CubeSat note number {index}"), context)

    assert len(store.search("cubesat note", limit=3)) == 3


# --- touch ----------------------------------------------------------------


def test_touch_increments_access_count(store: MemoryStore) -> None:
    context = make_context()
    memory = store.remember(make_memory(), context)

    store.touch((memory,), context)

    refreshed = store.get(memory.memory_id)
    assert refreshed.access_count == 1
    assert refreshed.last_accessed_at > memory.last_accessed_at


def test_touch_ignores_unknown_memories(store: MemoryStore) -> None:
    # A recall observes work already done; a memory forgotten in between
    # must not turn that into an error.
    store.touch((make_memory(),), make_context())


def test_touch_with_nothing_is_a_no_op(store: MemoryStore) -> None:
    store.touch((), make_context())


# --- list ----------------------------------------------------------------


def test_list_returns_newest_first(store: MemoryStore) -> None:
    context = make_context()
    store.remember(make_memory("older", created_at=NOW - timedelta(days=2)), context)
    store.remember(make_memory("newer", created_at=NOW), context)

    assert [memory.content for memory in store.list()] == ["newer", "older"]


def test_list_is_empty_initially(store: MemoryStore) -> None:
    assert store.list() == []


# --- durability (sqlite only) ----------------------------------------------------------------


def test_sqlite_memories_survive_reopen(tmp_path: Path) -> None:
    path = tmp_path / "memory.db"
    context = make_context()
    first = SQLiteMemoryStore(path)
    memory = first.remember(make_memory("The CubeSat uses 18650 cells"), context)
    first.close()

    second = SQLiteMemoryStore(path)
    try:
        assert second.get(memory.memory_id).content == "The CubeSat uses 18650 cells"
    finally:
        second.close()


def test_sqlite_round_trips_every_field(tmp_path: Path) -> None:
    path = tmp_path / "memory.db"
    context = make_context()
    store_ = SQLiteMemoryStore(path)
    try:
        original = make_memory(
            "Decided on 18650 cells",
            kind=MemoryKind.DECISION,
            importance=9,
            pinned=True,
            tags=("cubesat", "power"),
            source="conversation",
            metadata={"conversation_id": "abc"},
            access_count=3,
        )
        store_.remember(original, context)

        restored = store_.get(original.memory_id)
        assert restored == original
    finally:
        store_.close()

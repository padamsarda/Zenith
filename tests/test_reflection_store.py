"""Tests for ReflectionStore implementations.

Both backends run the same parametrized cases, for the same reason the
memory stores do: an in-memory store that behaves differently from the
durable one is a misleading test double.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from configs.config import Config
from runtime.context import ApplicationContext
from runtime.exceptions import ReflectionNotFoundError, ReflectionValidationError
from runtime.reflection.events import ReflectionCreated, ReflectionDeleted
from runtime.reflection.in_memory_store import InMemoryReflectionStore
from runtime.reflection.reflection import Reflection, ReflectionKind
from runtime.reflection.sqlite.store import SQLiteReflectionStore
from runtime.reflection.store import ReflectionStore
from shared.events.event import Event
from shared.utils.uuid_utils import generate_id

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)


def make_context() -> ApplicationContext:
    return ApplicationContext(config=Config(), logger=logging.getLogger("test.reflection"))


@pytest.fixture(params=["in_memory", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[ReflectionStore]:
    if request.param == "in_memory":
        yield InMemoryReflectionStore()
        return
    sqlite_store = SQLiteReflectionStore(tmp_path / "reflections.db")
    try:
        yield sqlite_store
    finally:
        sqlite_store.close()


def make_reflection(content: str = "You keep returning to CubeSat power work", **kwargs) -> Reflection:
    return Reflection(content=content, **{"created_at": NOW, **kwargs})


# --- add / get ----------------------------------------------------------------


def test_add_stores_and_returns(store: ReflectionStore) -> None:
    context = make_context()
    reflection = make_reflection()

    stored = store.add(reflection, context)

    assert stored.reflection_id == reflection.reflection_id
    assert store.get(reflection.reflection_id).content == reflection.content


def test_add_emits_event(store: ReflectionStore) -> None:
    context = make_context()
    received: list[Event] = []
    context.events.subscribe(ReflectionCreated, received.append)

    store.add(make_reflection(kind=ReflectionKind.DEEP), context)

    assert len(received) == 1
    assert received[0].payload["kind"] == "DEEP"


def test_add_rejects_empty_content(store: ReflectionStore) -> None:
    with pytest.raises(ReflectionValidationError):
        store.add(make_reflection(content="   "), make_context())


def test_add_rejects_a_bad_generation(store: ReflectionStore) -> None:
    with pytest.raises(ReflectionValidationError):
        store.add(make_reflection(generation=0), make_context())


def test_get_missing_raises(store: ReflectionStore) -> None:
    with pytest.raises(ReflectionNotFoundError):
        store.get(generate_id())


# --- provenance ----------------------------------------------------------------


def test_provenance_round_trips_in_order(store: ReflectionStore) -> None:
    # Order matters: it is the record of what the insight was drawn from,
    # and a reordered list is a different (less useful) record.
    context = make_context()
    sources = tuple(generate_id() for _ in range(5))

    reflection = store.add(make_reflection(source_memory_ids=sources), context)

    assert store.get(reflection.reflection_id).source_memory_ids == sources


def test_source_count_reports_provenance_size(store: ReflectionStore) -> None:
    context = make_context()
    sources = tuple(generate_id() for _ in range(3))

    stored = store.add(make_reflection(source_memory_ids=sources), context)

    assert stored.source_count == 3


def test_a_reflection_can_have_no_sources(store: ReflectionStore) -> None:
    context = make_context()

    stored = store.add(make_reflection(source_memory_ids=()), context)

    assert store.get(stored.reflection_id).source_memory_ids == ()


def test_provenance_survives_the_referenced_memory_disappearing(
    store: ReflectionStore,
) -> None:
    # Reflections reference memory IDs without a foreign key: a pruned
    # memory must not erase the record of what an insight came from.
    context = make_context()
    gone = generate_id()

    stored = store.add(make_reflection(source_memory_ids=(gone,)), context)

    assert store.get(stored.reflection_id).source_memory_ids == (gone,)


# --- versioning ----------------------------------------------------------------


def test_generations_are_retained_not_overwritten(store: ReflectionStore) -> None:
    context = make_context()
    first = store.add(
        make_reflection("first pass", kind=ReflectionKind.DEEP, generation=1), context
    )
    store.add(
        make_reflection(
            "second pass",
            kind=ReflectionKind.DEEP,
            generation=2,
            supersedes=first.reflection_id,
            created_at=NOW + timedelta(days=1),
        ),
        context,
    )

    assert len(store.list(kind=ReflectionKind.DEEP)) == 2
    assert store.get(first.reflection_id).content == "first pass"


def test_supersedes_links_back_to_the_previous_generation(store: ReflectionStore) -> None:
    context = make_context()
    first = store.add(make_reflection("first", kind=ReflectionKind.DEEP), context)
    second = store.add(
        make_reflection(
            "second",
            kind=ReflectionKind.DEEP,
            generation=2,
            supersedes=first.reflection_id,
            created_at=NOW + timedelta(days=1),
        ),
        context,
    )

    assert store.get(second.reflection_id).supersedes == first.reflection_id


# --- list / latest ----------------------------------------------------------------


def test_list_returns_newest_first(store: ReflectionStore) -> None:
    context = make_context()
    store.add(make_reflection("older", created_at=NOW - timedelta(days=2)), context)
    store.add(make_reflection("newer", created_at=NOW), context)

    assert [reflection.content for reflection in store.list()] == ["newer", "older"]


def test_list_filters_by_kind(store: ReflectionStore) -> None:
    context = make_context()
    store.add(make_reflection("session one", kind=ReflectionKind.SESSION), context)
    store.add(make_reflection("deep one", kind=ReflectionKind.DEEP), context)

    found = store.list(kind=ReflectionKind.DEEP)

    assert [reflection.content for reflection in found] == ["deep one"]


def test_list_respects_the_limit(store: ReflectionStore) -> None:
    context = make_context()
    for index in range(5):
        store.add(
            make_reflection(f"reflection {index}", created_at=NOW + timedelta(hours=index)),
            context,
        )

    assert len(store.list(limit=2)) == 2


def test_latest_returns_the_most_recent_of_a_kind(store: ReflectionStore) -> None:
    context = make_context()
    store.add(
        make_reflection("older", kind=ReflectionKind.DEEP, created_at=NOW - timedelta(days=1)),
        context,
    )
    store.add(make_reflection("newer", kind=ReflectionKind.DEEP, created_at=NOW), context)

    latest = store.latest(ReflectionKind.DEEP)

    assert latest is not None and latest.content == "newer"


def test_latest_is_none_when_there_are_none(store: ReflectionStore) -> None:
    assert store.latest(ReflectionKind.DEEP) is None


def test_latest_ignores_other_kinds(store: ReflectionStore) -> None:
    store.add(make_reflection(kind=ReflectionKind.SESSION), make_context())

    assert store.latest(ReflectionKind.DEEP) is None


# --- delete ----------------------------------------------------------------


def test_delete_removes(store: ReflectionStore) -> None:
    context = make_context()
    reflection = store.add(make_reflection(), context)

    store.delete(reflection.reflection_id, context)

    with pytest.raises(ReflectionNotFoundError):
        store.get(reflection.reflection_id)


def test_delete_emits_event(store: ReflectionStore) -> None:
    context = make_context()
    reflection = store.add(make_reflection(), context)
    received: list[Event] = []
    context.events.subscribe(ReflectionDeleted, received.append)

    store.delete(reflection.reflection_id, context)

    assert len(received) == 1


def test_delete_missing_raises(store: ReflectionStore) -> None:
    with pytest.raises(ReflectionNotFoundError):
        store.delete(generate_id(), make_context())


# --- durability (sqlite only) ----------------------------------------------------------------


def test_sqlite_reflections_survive_reopen(tmp_path: Path) -> None:
    path = tmp_path / "reflections.db"
    context = make_context()
    sources = tuple(generate_id() for _ in range(3))

    first = SQLiteReflectionStore(path)
    reflection = first.add(make_reflection(source_memory_ids=sources), context)
    first.close()

    second = SQLiteReflectionStore(path)
    try:
        restored = second.get(reflection.reflection_id)
        assert restored.content == reflection.content
        assert restored.source_memory_ids == sources
    finally:
        second.close()


def test_sqlite_round_trips_every_field(tmp_path: Path) -> None:
    context = make_context()
    store_ = SQLiteReflectionStore(tmp_path / "reflections.db")
    try:
        original = make_reflection(
            "a considered insight",
            kind=ReflectionKind.DEEP,
            source_memory_ids=(generate_id(), generate_id()),
            generation=3,
            supersedes=generate_id(),
            model="claude-haiku-4-5",
            metadata={"question": "what patterns do you see"},
        )
        store_.add(original, context)

        assert store_.get(original.reflection_id) == original
    finally:
        store_.close()

"""InMemoryMemoryStore: the non-durable default MemoryStore."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from runtime.exceptions import MemoryNotFoundError
from runtime.memory.events import MemoryForgotten, MemoryRemembered
from runtime.memory.matching import normalize_scores, overlap_relevance, tokenize
from runtime.memory.retrieval import MemoryCandidate
from runtime.memory.store import SOURCE, MemoryStore
from runtime.memory.validation import validate_memory
from shared.utils.time_utils import utc_now

if TYPE_CHECKING:
    from runtime.context import ApplicationContext
    from runtime.memory.memory import Memory
    from runtime.memory.temporal import TimeWindow


class InMemoryMemoryStore(MemoryStore):
    """Holds memories in a dictionary for the lifetime of the process.

    `context.memory`'s default, and the same kind of honest scaffolding
    `InMemoryConversationStore` is: it makes the whole memory path
    exercisable — including in tests — without a database file, but
    nothing survives a restart, which is precisely the opposite of what
    memory is for. A real deployment assigns
    `runtime.memory.sqlite.store.SQLiteMemoryStore` (ADR 0027).
    """

    def __init__(self) -> None:
        self._memories: dict[UUID, Memory] = {}

    def remember(self, memory: Memory, application_context: ApplicationContext) -> Memory:
        validate_memory(memory)
        self._memories[memory.memory_id] = memory
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
        try:
            return self._memories[memory_id]
        except KeyError:
            raise MemoryNotFoundError(f"Memory '{memory_id}' is not stored.") from None

    def has(self, memory_id: UUID) -> bool:
        return memory_id in self._memories

    def forget(self, memory_id: UUID, application_context: ApplicationContext) -> None:
        self.get(memory_id)
        del self._memories[memory_id]
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
        in_window = [
            memory
            for memory in self._memories.values()
            if window is None or window.contains(memory.occurred_at)
        ]
        if not in_window:
            return ()

        query_tokens = tokenize(query)
        raw = [overlap_relevance(query_tokens, memory.content) for memory in in_window]

        # With no usable query every candidate is equally (ir)relevant, so
        # the store contributes nothing and the policy ranks on recency
        # and importance alone — which is what makes a bare "what was I
        # doing yesterday" work.
        if not query_tokens:
            scored = [MemoryCandidate(memory=memory, relevance=0.0) for memory in in_window]
        else:
            matched = [
                (memory, value) for memory, value in zip(in_window, raw) if value > 0.0
            ]
            if not matched:
                return ()
            normalized = normalize_scores([value for _, value in matched])
            scored = [
                MemoryCandidate(memory=memory, relevance=value)
                for (memory, _), value in zip(matched, normalized)
            ]

        scored.sort(key=lambda candidate: candidate.relevance, reverse=True)
        return tuple(scored[:limit])

    def touch(self, memories: tuple[Memory, ...], application_context: ApplicationContext) -> None:
        moment = utc_now()
        for memory in memories:
            stored = self._memories.get(memory.memory_id)
            if stored is not None:
                self._memories[memory.memory_id] = stored.accessed(moment)

    def list(self) -> list[Memory]:
        return sorted(self._memories.values(), key=lambda memory: memory.created_at, reverse=True)

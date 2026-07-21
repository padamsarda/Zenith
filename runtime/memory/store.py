"""MemoryStore: the abstract contract every memory backend implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from runtime.context import ApplicationContext
    from runtime.memory.memory import Memory
    from runtime.memory.retrieval import MemoryCandidate
    from runtime.memory.temporal import TimeWindow

SOURCE = "memory_store"


class MemoryStore(ABC):
    """The only path that stores, searches, or deletes what Zeni knows.

    Mirrors `ConversationStore` (ADR 0018) exactly: an ABC with an
    in-memory default and a durable SQLite backend, mutating methods
    taking the `ApplicationContext` so a store built by
    `field(default_factory=...)` can still reach the `EventBus`.

    `search` is the one method whose implementation genuinely differs
    between backends, because matching text is backend-specific — FTS5's
    BM25 in SQLite, a token overlap in memory, a vector similarity in
    some future backend. It returns `MemoryCandidate`s carrying a
    normalized relevance in `[0, 1]`; combining that with recency and
    importance is the `MemoryRetrievalPolicy`'s job, identical across
    every backend (ADR 0027).
    """

    @abstractmethod
    def remember(self, memory: Memory, application_context: ApplicationContext) -> Memory:
        """Store `memory` and return it.

        Emits `MemoryRemembered`.

        Raises:
            MemoryValidationError: If `memory` fails validation.
        """

    @abstractmethod
    def get(self, memory_id: UUID) -> Memory:
        """Return the memory with `memory_id`.

        Raises:
            MemoryNotFoundError: If no such memory is stored.
        """

    @abstractmethod
    def has(self, memory_id: UUID) -> bool:
        """Return True if a memory with `memory_id` is stored."""

    @abstractmethod
    def forget(self, memory_id: UUID, application_context: ApplicationContext) -> None:
        """Delete the memory with `memory_id`.

        Emits `MemoryForgotten`.

        Raises:
            MemoryNotFoundError: If no such memory is stored.
        """

    @abstractmethod
    def search(
        self,
        query: str,
        *,
        window: TimeWindow | None = None,
        limit: int = 50,
    ) -> tuple[MemoryCandidate, ...]:
        """Return up to `limit` memories matching `query`, with relevance scores.

        A `window` restricts candidates to memories whose `occurred_at`
        falls inside it — the time-aware filtering that makes relative
        questions ("what did we decide yesterday") answerable.

        An empty or unmatchable `query` returns candidates on time and
        recency alone rather than nothing, so a bare "what was I doing
        yesterday" still retrieves.
        """

    @abstractmethod
    def touch(self, memories: tuple[Memory, ...], application_context: ApplicationContext) -> None:
        """Record that `memories` were just recalled.

        Updates `last_accessed_at`/`access_count`, which is what lets
        recency reflect genuine use rather than only creation time.
        Silently ignores memories no longer stored — a recall is an
        observation about something that already happened, so it must
        never fail the request that triggered it.
        """

    @abstractmethod
    def list(self) -> list[Memory]:
        """Return a snapshot list of all stored memories, newest first."""

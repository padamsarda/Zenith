"""ReflectionStore: the abstract contract every reflection backend implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from runtime.context import ApplicationContext
    from runtime.reflection.reflection import Reflection, ReflectionKind

SOURCE = "reflection_store"


class ReflectionStore(ABC):
    """Stores derived insights, separately from the memories they came from.

    A deliberately separate store rather than a `MemoryKind` inside
    `MemoryStore` (ADR 0029). Reflections are *derived* data with
    different rules: they carry provenance, they are versioned into
    generations, they are regenerable from the memories beneath them,
    and a bad one should be deletable without touching anything the user
    actually said. Mixing the two would put derived content on the same
    footing as raw evidence and make "what did I actually tell you"
    unanswerable.

    Mirrors `MemoryStore` and `ConversationStore` in shape: an ABC with
    an in-memory default and a durable SQLite backend, mutating methods
    taking the `ApplicationContext` to reach the `EventBus`.
    """

    @abstractmethod
    def add(self, reflection: Reflection, application_context: ApplicationContext) -> Reflection:
        """Store `reflection` and return it.

        Emits `ReflectionCreated`.

        Raises:
            ReflectionValidationError: If `reflection` fails validation.
        """

    @abstractmethod
    def get(self, reflection_id: UUID) -> Reflection:
        """Return the reflection with `reflection_id`.

        Raises:
            ReflectionNotFoundError: If no such reflection is stored.
        """

    @abstractmethod
    def delete(self, reflection_id: UUID, application_context: ApplicationContext) -> None:
        """Delete the reflection with `reflection_id`.

        Emits `ReflectionDeleted`. Deleting a reflection never touches the
        memories it referenced — that separation is the point of this
        layer.

        Raises:
            ReflectionNotFoundError: If no such reflection is stored.
        """

    @abstractmethod
    def list(
        self, *, kind: ReflectionKind | None = None, limit: int | None = None
    ) -> list[Reflection]:
        """Return stored reflections, newest first, optionally filtered by `kind`."""

    @abstractmethod
    def latest(self, kind: ReflectionKind) -> Reflection | None:
        """Return the most recent reflection of `kind`, or None if there is none.

        How the scheduler decides whether a deep reflection is due, and
        how a new generation finds the one it supersedes.
        """

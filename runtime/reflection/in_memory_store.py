"""InMemoryReflectionStore: the non-durable default ReflectionStore."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from runtime.exceptions import ReflectionNotFoundError
from runtime.reflection.events import ReflectionCreated, ReflectionDeleted
from runtime.reflection.store import SOURCE, ReflectionStore
from runtime.reflection.validation import validate_reflection

if TYPE_CHECKING:
    from runtime.context import ApplicationContext
    from runtime.reflection.reflection import Reflection, ReflectionKind


class InMemoryReflectionStore(ReflectionStore):
    """Holds reflections in a dictionary for the lifetime of the process.

    `context.reflections`'s default, the same honest scaffolding
    `InMemoryMemoryStore` is. Losing reflections on restart is less
    damaging than losing memories — they are derived and can be
    regenerated from the memories beneath them — but a deployment that
    wants its accumulated understanding to persist assigns
    `runtime.reflection.sqlite.store.SQLiteReflectionStore`.
    """

    def __init__(self) -> None:
        self._reflections: dict[UUID, Reflection] = {}

    def add(self, reflection: Reflection, application_context: ApplicationContext) -> Reflection:
        validate_reflection(reflection)
        self._reflections[reflection.reflection_id] = reflection
        application_context.events.emit(
            ReflectionCreated(
                source=SOURCE,
                payload={
                    "reflection_id": str(reflection.reflection_id),
                    "kind": reflection.kind.name,
                    "generation": reflection.generation,
                    "sources": reflection.source_count,
                },
            )
        )
        return reflection

    def get(self, reflection_id: UUID) -> Reflection:
        try:
            return self._reflections[reflection_id]
        except KeyError:
            raise ReflectionNotFoundError(
                f"Reflection '{reflection_id}' is not stored."
            ) from None

    def delete(self, reflection_id: UUID, application_context: ApplicationContext) -> None:
        self.get(reflection_id)
        del self._reflections[reflection_id]
        application_context.events.emit(
            ReflectionDeleted(source=SOURCE, payload={"reflection_id": str(reflection_id)})
        )

    def list(
        self, *, kind: ReflectionKind | None = None, limit: int | None = None
    ) -> list[Reflection]:
        found = [
            reflection
            for reflection in self._reflections.values()
            if kind is None or reflection.kind is kind
        ]
        found.sort(key=lambda reflection: reflection.created_at, reverse=True)
        return found[:limit] if limit is not None else found

    def latest(self, kind: ReflectionKind) -> Reflection | None:
        found = self.list(kind=kind, limit=1)
        return found[0] if found else None

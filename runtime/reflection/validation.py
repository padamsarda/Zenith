"""Validation guard functions for the reflection layer."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from runtime.exceptions import ReflectionValidationError
from runtime.reflection.reflection import FIRST_GENERATION, ReflectionKind

if TYPE_CHECKING:
    from runtime.reflection.reflection import Reflection


def validate_reflection(reflection: Reflection) -> None:
    """Raise ReflectionValidationError if `reflection` is not storable."""
    if not isinstance(reflection.content, str) or not reflection.content.strip():
        raise ReflectionValidationError(
            f"Reflection content must be non-empty, got {reflection.content!r}"
        )
    if not isinstance(reflection.kind, ReflectionKind):
        raise ReflectionValidationError(
            f"Reflection kind must be a ReflectionKind, got {reflection.kind!r}"
        )
    if not isinstance(reflection.source_memory_ids, tuple) or not all(
        isinstance(memory_id, UUID) for memory_id in reflection.source_memory_ids
    ):
        raise ReflectionValidationError(
            "Reflection source_memory_ids must be a tuple of UUIDs, got "
            f"{reflection.source_memory_ids!r}"
        )
    if isinstance(reflection.generation, bool) or not isinstance(reflection.generation, int):
        raise ReflectionValidationError(
            f"Reflection generation must be an integer, got {reflection.generation!r}"
        )
    if reflection.generation < FIRST_GENERATION:
        raise ReflectionValidationError(
            f"Reflection generation must be at least {FIRST_GENERATION}, "
            f"got {reflection.generation}"
        )
    if reflection.supersedes is not None and not isinstance(reflection.supersedes, UUID):
        raise ReflectionValidationError(
            f"Reflection supersedes must be a UUID or None, got {reflection.supersedes!r}"
        )

"""Validation guard functions for the memory subsystem."""

from __future__ import annotations

from typing import TYPE_CHECKING

from runtime.exceptions import MemoryValidationError
from runtime.memory.memory import MAX_IMPORTANCE, MIN_IMPORTANCE, MemoryKind

if TYPE_CHECKING:
    from runtime.memory.memory import Memory


def validate_memory(memory: Memory) -> None:
    """Raise MemoryValidationError if `memory` is not storable.

    Content is prose, so it is checked the way `Message.content` is —
    non-empty once stripped, but incidental leading/trailing whitespace
    is acceptable rather than an error.
    """
    if not isinstance(memory.content, str) or not memory.content.strip():
        raise MemoryValidationError(f"Memory content must be non-empty, got {memory.content!r}")
    if not isinstance(memory.kind, MemoryKind):
        raise MemoryValidationError(f"Memory kind must be a MemoryKind, got {memory.kind!r}")
    if isinstance(memory.importance, bool) or not isinstance(memory.importance, int):
        raise MemoryValidationError(
            f"Memory importance must be an integer, got {memory.importance!r}"
        )
    if not MIN_IMPORTANCE <= memory.importance <= MAX_IMPORTANCE:
        raise MemoryValidationError(
            f"Memory importance must be between {MIN_IMPORTANCE} and {MAX_IMPORTANCE}, "
            f"got {memory.importance}"
        )
    if not isinstance(memory.pinned, bool):
        raise MemoryValidationError(f"Memory pinned must be a bool, got {memory.pinned!r}")
    if not isinstance(memory.tags, tuple) or not all(
        isinstance(tag, str) and tag.strip() for tag in memory.tags
    ):
        raise MemoryValidationError(
            f"Memory tags must be a tuple of non-empty strings, got {memory.tags!r}"
        )
    if memory.access_count < 0:
        raise MemoryValidationError(
            f"Memory access_count cannot be negative, got {memory.access_count}"
        )

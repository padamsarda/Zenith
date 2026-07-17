"""Text-related helpers."""

from __future__ import annotations


def is_blank_or_padded(value: object) -> bool:
    """Return True if `value` is not a usable identifier string.

    An identifier string must be a `str`, non-empty after stripping, and
    equal to its own stripped form (no leading/trailing whitespace).
    Shared by validators across the runtime and command frameworks that
    need this same "is this a well-formed short identifier" check.
    """
    return not isinstance(value, str) or not value.strip() or value != value.strip()

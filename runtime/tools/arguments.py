"""Shared argument-extraction helpers for built-in Tool implementations.

Every tool receives its invocation arguments as a loosely typed
`dict[str, Any]` — the shape `Tool.invoke` is given by the pipeline,
since a provider ultimately supplies them. These helpers apply one
consistent, explicit type check per argument and raise
`ToolExecutionError` with a clear message on mismatch, so no tool
repeats the same `isinstance` boilerplate.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from runtime.exceptions import ToolExecutionError


def require_str(arguments: Mapping[str, Any], key: str) -> str:
    """Return `arguments[key]` as a non-empty string.

    Raises:
        ToolExecutionError: If the key is missing, not a string, or blank.
    """
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolExecutionError(f"'{key}' must be a non-empty string, got {value!r}.")
    return value


def optional_str(arguments: Mapping[str, Any], key: str, default: str | None = None) -> str | None:
    """Return `arguments[key]` as a string, or `default` if absent or None.

    Raises:
        ToolExecutionError: If present but not a string.
    """
    value = arguments.get(key)
    if value is None:
        return default
    if not isinstance(value, str):
        raise ToolExecutionError(f"'{key}' must be a string, got {value!r}.")
    return value


def optional_bool(arguments: Mapping[str, Any], key: str, default: bool = False) -> bool:
    """Return `arguments[key]` as a bool, or `default` if absent or None.

    Raises:
        ToolExecutionError: If present but not a boolean.
    """
    value = arguments.get(key)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ToolExecutionError(f"'{key}' must be a boolean, got {value!r}.")
    return value


def optional_int(arguments: Mapping[str, Any], key: str, default: int | None = None) -> int | None:
    """Return `arguments[key]` as an int, or `default` if absent or None.

    Raises:
        ToolExecutionError: If present but not an integer. `bool` is
            rejected even though it is technically an `int` subclass.
    """
    value = arguments.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolExecutionError(f"'{key}' must be an integer, got {value!r}.")
    return value


def optional_float(
    arguments: Mapping[str, Any], key: str, default: float | None = None
) -> float | None:
    """Return `arguments[key]` as a float, or `default` if absent or None.

    Raises:
        ToolExecutionError: If present but not a number.
    """
    value = arguments.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolExecutionError(f"'{key}' must be a number, got {value!r}.")
    return float(value)


def optional_mapping(arguments: Mapping[str, Any], key: str) -> dict[str, str]:
    """Return `arguments[key]` as a `dict[str, str]`, or `{}` if absent or None.

    Raises:
        ToolExecutionError: If present but not a mapping of strings to
            strings.
    """
    value = arguments.get(key)
    if value is None:
        return {}
    if not isinstance(value, Mapping) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    ):
        raise ToolExecutionError(
            f"'{key}' must be an object of string to string, got {value!r}."
        )
    return dict(value)


def optional_sequence_str(arguments: Mapping[str, Any], key: str) -> tuple[str, ...]:
    """Return `arguments[key]` as a `tuple[str, ...]`, or `()` if absent or None.

    Raises:
        ToolExecutionError: If present but not a sequence of strings.
    """
    value = arguments.get(key)
    if value is None:
        return ()
    if (
        isinstance(value, str)
        or not isinstance(value, Sequence)
        or not all(isinstance(item, str) for item in value)
    ):
        raise ToolExecutionError(f"'{key}' must be an array of strings, got {value!r}.")
    return tuple(value)

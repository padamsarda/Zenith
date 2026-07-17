"""Tests for the CommandResult dataclass."""

from __future__ import annotations

import pytest

from runtime.commands.result import CommandResult


def test_success_result_carries_expected_fields() -> None:
    result = CommandResult(success=True, message="done", duration_seconds=0.5, data={"x": 1})

    assert result.success is True
    assert result.message == "done"
    assert result.duration_seconds == 0.5
    assert result.data == {"x": 1}
    assert result.exception is None


def test_failure_result_carries_exception() -> None:
    exc = ValueError("boom")

    result = CommandResult(success=False, message="boom", duration_seconds=0.1, exception=exc)

    assert result.success is False
    assert result.exception is exc


def test_data_defaults_to_none() -> None:
    result = CommandResult(success=True, message="done", duration_seconds=0.0)

    assert result.data is None


def test_exception_defaults_to_none() -> None:
    result = CommandResult(success=True, message="done", duration_seconds=0.0)

    assert result.exception is None


def test_command_result_is_immutable() -> None:
    result = CommandResult(success=True, message="done", duration_seconds=0.0)

    with pytest.raises(AttributeError):
        result.success = False  # type: ignore[misc]


def test_command_result_supports_falsy_data() -> None:
    result = CommandResult(success=True, message="done", duration_seconds=0.0, data=0)

    assert result.data == 0

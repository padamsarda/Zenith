"""Tests for the shared tool argument-extraction helpers."""

from __future__ import annotations

import pytest

from runtime.exceptions import ToolExecutionError
from runtime.tools.arguments import (
    optional_bool,
    optional_float,
    optional_int,
    optional_mapping,
    optional_sequence_str,
    optional_str,
    require_str,
)

# --- require_str ---------------------------------------------------------


def test_require_str_returns_the_value() -> None:
    assert require_str({"path": "a.txt"}, "path") == "a.txt"


@pytest.mark.parametrize("bad", [None, "", "   ", 42, ["a"]])
def test_require_str_rejects_missing_or_non_string(bad: object) -> None:
    with pytest.raises(ToolExecutionError):
        require_str({"path": bad}, "path")


def test_require_str_rejects_absent_key() -> None:
    with pytest.raises(ToolExecutionError):
        require_str({}, "path")


# --- optional_str ----------------------------------------------------------


def test_optional_str_returns_the_value() -> None:
    assert optional_str({"cwd": "sub"}, "cwd") == "sub"


def test_optional_str_returns_default_when_absent() -> None:
    assert optional_str({}, "cwd", default=".") == "."


def test_optional_str_returns_default_when_none() -> None:
    assert optional_str({"cwd": None}, "cwd", default=".") == "."


def test_optional_str_rejects_non_string() -> None:
    with pytest.raises(ToolExecutionError):
        optional_str({"cwd": 42}, "cwd")


# --- optional_bool ----------------------------------------------------------


def test_optional_bool_returns_the_value() -> None:
    assert optional_bool({"recursive": True}, "recursive") is True


def test_optional_bool_returns_default_when_absent() -> None:
    assert optional_bool({}, "recursive", default=False) is False


def test_optional_bool_rejects_non_bool() -> None:
    with pytest.raises(ToolExecutionError):
        optional_bool({"recursive": "true"}, "recursive")


# --- optional_int -----------------------------------------------------------


def test_optional_int_returns_the_value() -> None:
    assert optional_int({"max_count": 5}, "max_count") == 5


def test_optional_int_returns_default_when_absent() -> None:
    assert optional_int({}, "max_count", default=20) == 20


def test_optional_int_rejects_bool() -> None:
    with pytest.raises(ToolExecutionError):
        optional_int({"max_count": True}, "max_count")


def test_optional_int_rejects_float() -> None:
    with pytest.raises(ToolExecutionError):
        optional_int({"max_count": 1.5}, "max_count")


# --- optional_float ----------------------------------------------------------


def test_optional_float_returns_the_value_as_float() -> None:
    assert optional_float({"timeout_seconds": 5}, "timeout_seconds") == 5.0


def test_optional_float_returns_default_when_absent() -> None:
    assert optional_float({}, "timeout_seconds", default=30.0) == 30.0


def test_optional_float_rejects_bool() -> None:
    with pytest.raises(ToolExecutionError):
        optional_float({"timeout_seconds": False}, "timeout_seconds")


def test_optional_float_rejects_non_number() -> None:
    with pytest.raises(ToolExecutionError):
        optional_float({"timeout_seconds": "30"}, "timeout_seconds")


# --- optional_mapping --------------------------------------------------------


def test_optional_mapping_returns_a_plain_dict() -> None:
    assert optional_mapping({"env": {"KEY": "value"}}, "env") == {"KEY": "value"}


def test_optional_mapping_returns_empty_dict_when_absent() -> None:
    assert optional_mapping({}, "env") == {}


def test_optional_mapping_rejects_non_mapping() -> None:
    with pytest.raises(ToolExecutionError):
        optional_mapping({"env": ["KEY=value"]}, "env")


def test_optional_mapping_rejects_non_string_values() -> None:
    with pytest.raises(ToolExecutionError):
        optional_mapping({"env": {"KEY": 1}}, "env")


# --- optional_sequence_str ----------------------------------------------------


def test_optional_sequence_str_returns_a_tuple() -> None:
    assert optional_sequence_str({"args": ["-k", "foo"]}, "args") == ("-k", "foo")


def test_optional_sequence_str_returns_empty_tuple_when_absent() -> None:
    assert optional_sequence_str({}, "args") == ()


def test_optional_sequence_str_rejects_bare_string() -> None:
    with pytest.raises(ToolExecutionError):
        optional_sequence_str({"args": "-k foo"}, "args")


def test_optional_sequence_str_rejects_non_string_items() -> None:
    with pytest.raises(ToolExecutionError):
        optional_sequence_str({"args": ["-k", 1]}, "args")

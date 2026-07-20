"""Tests for the path-sandboxing helpers shared by built-in tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.exceptions import ToolExecutionError
from runtime.tools.sandbox import read_sandboxed_text, resolve_within_root

# --- resolve_within_root ---------------------------------------------------


def test_none_resolves_to_root(tmp_path: Path) -> None:
    assert resolve_within_root(tmp_path, None) == tmp_path


@pytest.mark.parametrize("raw_path", ["", "."])
def test_empty_or_dot_resolves_to_root(tmp_path: Path, raw_path: str) -> None:
    assert resolve_within_root(tmp_path, raw_path) == tmp_path


def test_relative_path_resolves_under_root(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()

    assert resolve_within_root(tmp_path, "sub") == tmp_path / "sub"


def test_nested_relative_path_resolves(tmp_path: Path) -> None:
    (tmp_path / "a" / "b").mkdir(parents=True)

    assert resolve_within_root(tmp_path, "a/b") == tmp_path / "a" / "b"


def test_absolute_path_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ToolExecutionError):
        resolve_within_root(tmp_path, str(tmp_path / "outside.txt"))


def test_traversal_outside_root_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ToolExecutionError):
        resolve_within_root(tmp_path, "../escaped.txt")


def test_traversal_that_stays_inside_root_is_allowed(tmp_path: Path) -> None:
    (tmp_path / "a" / "b").mkdir(parents=True)

    assert resolve_within_root(tmp_path, "a/b/../b") == tmp_path / "a" / "b"


def test_nonexistent_relative_path_is_still_resolved(tmp_path: Path) -> None:
    assert resolve_within_root(tmp_path, "does_not_exist.txt") == tmp_path / "does_not_exist.txt"


# --- read_sandboxed_text ----------------------------------------------------


def test_reads_file_contents(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")

    assert read_sandboxed_text(tmp_path, "a.txt") == "hello"


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ToolExecutionError):
        read_sandboxed_text(tmp_path, "missing.txt")


def test_directory_raises(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()

    with pytest.raises(ToolExecutionError):
        read_sandboxed_text(tmp_path, "sub")


def test_oversized_file_raises(tmp_path: Path) -> None:
    (tmp_path / "big.txt").write_text("x" * 100, encoding="utf-8")

    with pytest.raises(ToolExecutionError):
        read_sandboxed_text(tmp_path, "big.txt", max_bytes=10)


def test_non_utf8_file_raises(tmp_path: Path) -> None:
    (tmp_path / "bin.dat").write_bytes(b"\xff\xfe\x00\x01")

    with pytest.raises(ToolExecutionError):
        read_sandboxed_text(tmp_path, "bin.dat")


def test_path_escaping_root_raises(tmp_path: Path) -> None:
    with pytest.raises(ToolExecutionError):
        read_sandboxed_text(tmp_path, "../escaped.txt")

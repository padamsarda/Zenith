"""Tests for runtime.utils helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from runtime.utils.fs_utils import directory_exists, file_exists
from runtime.utils.time_utils import utc_now
from runtime.utils.uuid_utils import generate_id


def test_utc_now_returns_timezone_aware_datetime() -> None:
    result = utc_now()

    assert isinstance(result, datetime)
    assert result.tzinfo == timezone.utc


def test_utc_now_is_current() -> None:
    before = datetime.now(timezone.utc)
    result = utc_now()
    after = datetime.now(timezone.utc)

    assert before <= result <= after


def test_generate_id_returns_uuid() -> None:
    assert isinstance(generate_id(), UUID)


def test_generate_id_is_unique() -> None:
    assert generate_id() != generate_id()


def test_directory_exists_true_for_directory(tmp_path: Path) -> None:
    assert directory_exists(tmp_path) is True


def test_directory_exists_false_for_missing_path(tmp_path: Path) -> None:
    assert directory_exists(tmp_path / "missing") is False


def test_directory_exists_false_for_file(tmp_path: Path) -> None:
    file_path = tmp_path / "file.txt"
    file_path.write_text("content")

    assert directory_exists(file_path) is False


def test_file_exists_true_for_file(tmp_path: Path) -> None:
    file_path = tmp_path / "file.txt"
    file_path.write_text("content")

    assert file_exists(file_path) is True


def test_file_exists_false_for_missing_path(tmp_path: Path) -> None:
    assert file_exists(tmp_path / "missing.txt") is False


def test_file_exists_false_for_directory(tmp_path: Path) -> None:
    assert file_exists(tmp_path) is False

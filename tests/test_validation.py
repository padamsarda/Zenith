"""Tests for runtime.validation helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from configs.config import Config
from runtime.validation import validate_config, validate_path_exists, validate_service_name
from shared.exceptions import ValidationError


def test_validate_path_exists_passes_for_existing_file(tmp_path: Path) -> None:
    file_path = tmp_path / "file.txt"
    file_path.write_text("content")

    validate_path_exists(file_path)


def test_validate_path_exists_passes_for_existing_directory(tmp_path: Path) -> None:
    validate_path_exists(tmp_path)


def test_validate_path_exists_raises_for_missing_path(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        validate_path_exists(tmp_path / "missing")


def test_validate_path_exists_must_be_dir_raises_for_file(tmp_path: Path) -> None:
    file_path = tmp_path / "file.txt"
    file_path.write_text("content")

    with pytest.raises(ValidationError):
        validate_path_exists(file_path, must_be_dir=True)


def test_validate_path_exists_must_be_dir_passes_for_directory(tmp_path: Path) -> None:
    validate_path_exists(tmp_path, must_be_dir=True)


@pytest.mark.parametrize("name", ["service", "my-service", "my_service_1"])
def test_validate_service_name_accepts_valid_names(name: str) -> None:
    validate_service_name(name)


@pytest.mark.parametrize("name", ["", "   ", " service", "service "])
def test_validate_service_name_rejects_invalid_names(name: str) -> None:
    with pytest.raises(ValidationError):
        validate_service_name(name)


def test_validate_service_name_rejects_non_string() -> None:
    with pytest.raises(ValidationError):
        validate_service_name(123)  # type: ignore[arg-type]


def test_validate_config_passes_for_config_instance() -> None:
    validate_config(Config())


def test_validate_config_rejects_non_config() -> None:
    with pytest.raises(ValidationError):
        validate_config({"debug": True})  # type: ignore[arg-type]

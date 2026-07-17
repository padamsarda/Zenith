"""Tests for centralized configuration loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from configs.config import Config, load_config
from runtime.exceptions import ConfigurationError


def test_load_config_missing_file_returns_defaults(tmp_path: Path) -> None:
    config = load_config(tmp_path / "does_not_exist.toml")

    assert config == Config()
    assert config.debug is False


def test_load_config_reads_debug_flag(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("debug = true\n")

    config = load_config(config_path)

    assert config.debug is True


def test_config_is_immutable() -> None:
    config = Config()

    with pytest.raises(AttributeError):
        config.debug = True  # type: ignore[misc]


def test_load_config_invalid_toml_raises_configuration_error(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("this is not valid toml =====")

    with pytest.raises(ConfigurationError):
        load_config(config_path)

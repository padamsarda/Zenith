"""Tests for centralized configuration loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from configs.config import Config, load_config
from shared.exceptions import ConfigurationError


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


def test_new_fields_default_sensibly() -> None:
    config = Config()

    assert config.interactive is False
    assert config.assistant_provider == "echo"
    assert config.assistant_max_turns == 8


def test_load_config_reads_assistant_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        'interactive = true\nassistant_provider = "claude"\nassistant_max_turns = 3\n'
    )

    config = load_config(config_path)

    assert config.interactive is True
    assert config.assistant_provider == "claude"
    assert config.assistant_max_turns == 3


def test_load_config_partial_file_keeps_other_defaults(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("debug = true\n")

    config = load_config(config_path)

    assert config.debug is True
    assert config.assistant_provider == "echo"
    assert config.assistant_max_turns == 8


def test_load_config_unconvertible_max_turns_raises(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('assistant_max_turns = "many"\n')

    with pytest.raises(ConfigurationError):
        load_config(config_path)

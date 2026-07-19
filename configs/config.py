"""Centralized configuration loading for Zenith.

Configuration is optional: if `config.toml` is absent, sensible defaults
are used. The resulting `Config` object is immutable once loaded.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from runtime.exceptions import ConfigurationError
from shared.utils.fs_utils import file_exists

DEFAULT_CONFIG_PATH = Path("configs/config.toml")


@dataclass(frozen=True)
class Config:
    """Immutable runtime configuration.

    Attributes:
        debug: Whether DEBUG-level logging is enabled.
    """

    debug: bool = False


def load_config(config_path: Path = DEFAULT_CONFIG_PATH) -> Config:
    """Load configuration from a TOML file, falling back to defaults.

    Args:
        config_path: Path to a `config.toml` file. If it does not exist,
            the default `Config` is returned.

    Returns:
        An immutable `Config` instance.

    Raises:
        ConfigurationError: If the file exists but cannot be parsed.
    """
    if not file_exists(config_path):
        return Config()

    try:
        with config_path.open("rb") as config_file:
            data = tomllib.load(config_file)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(f"Failed to parse {config_path}: {exc}") from exc

    return Config(debug=bool(data.get("debug", False)))

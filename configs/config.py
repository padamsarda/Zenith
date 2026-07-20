"""Centralized configuration loading for Zenith.

Configuration is optional: if `config.toml` is absent, sensible defaults
are used. The resulting `Config` object is immutable once loaded.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from shared.exceptions import ConfigurationError
from shared.utils.fs_utils import file_exists

DEFAULT_CONFIG_PATH = Path("configs/config.toml")


@dataclass(frozen=True)
class Config:
    """Immutable runtime configuration.

    Attributes:
        debug: Whether DEBUG-level logging is enabled.
        interactive: Whether `Runtime.run` serves an interactive console
            session instead of idling.
        assistant_provider: The `provider_id` of the assistant provider
            the pipeline uses when a request does not name one.
        assistant_max_turns: How many provider turns one request may
            take before the engine fails it (bounds the tool loop).
    """

    debug: bool = False
    interactive: bool = False
    assistant_provider: str = "echo"
    assistant_max_turns: int = 8


def load_config(config_path: Path = DEFAULT_CONFIG_PATH) -> Config:
    """Load configuration from a TOML file, falling back to defaults.

    Args:
        config_path: Path to a `config.toml` file. If it does not exist,
            the default `Config` is returned.

    Returns:
        An immutable `Config` instance.

    Raises:
        ConfigurationError: If the file exists but cannot be parsed, or
            a value cannot be converted to its field's type.
    """
    if not file_exists(config_path):
        return Config()

    try:
        with config_path.open("rb") as config_file:
            data = tomllib.load(config_file)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(f"Failed to parse {config_path}: {exc}") from exc

    defaults = Config()
    try:
        return Config(
            debug=bool(data.get("debug", defaults.debug)),
            interactive=bool(data.get("interactive", defaults.interactive)),
            assistant_provider=str(
                data.get("assistant_provider", defaults.assistant_provider)
            ),
            assistant_max_turns=int(
                data.get("assistant_max_turns", defaults.assistant_max_turns)
            ),
        )
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"Invalid value in {config_path}: {exc}") from exc

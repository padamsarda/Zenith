"""Validation helpers for Zenith.

These are small, explicit guard functions used at the boundaries of the
system (filesystem paths, configuration, service names). Each raises
`ValidationError` on failure rather than returning a boolean, so a
successful call means the value has already been checked.
"""

from __future__ import annotations

from pathlib import Path

from configs.config import Config
from shared.exceptions import ValidationError
from shared.utils.fs_utils import directory_exists
from shared.utils.text_utils import is_blank_or_padded


def validate_path_exists(path: Path, *, must_be_dir: bool = False) -> None:
    """Raise ValidationError if `path` does not exist.

    Args:
        path: The filesystem path to check.
        must_be_dir: If True, also require the path to be a directory.
    """
    if must_be_dir:
        if not directory_exists(path):
            raise ValidationError(f"Required directory does not exist: {path}")
        return

    if not path.exists():
        raise ValidationError(f"Required path does not exist: {path}")


def validate_service_name(name: str) -> None:
    """Raise ValidationError if `name` is not a usable service name.

    A valid service name is a non-empty string with no leading or
    trailing whitespace.
    """
    if is_blank_or_padded(name):
        raise ValidationError(f"Invalid service name: {name!r}")


def validate_config(config: Config) -> None:
    """Raise ValidationError if `config` is not a usable Config instance.

    Checks the instance's type and every field's type and range, so a
    successful call means the whole configuration is safe to run on.
    """
    if not isinstance(config, Config):
        raise ValidationError(
            f"Expected a Config instance, got {type(config).__name__}"
        )
    if not isinstance(config.debug, bool):
        raise ValidationError(f"debug must be a bool, got {config.debug!r}")
    if not isinstance(config.interactive, bool):
        raise ValidationError(f"interactive must be a bool, got {config.interactive!r}")
    if is_blank_or_padded(config.assistant_provider):
        raise ValidationError(
            f"assistant_provider must be a provider ID, got {config.assistant_provider!r}"
        )
    if not isinstance(config.assistant_max_turns, int) or config.assistant_max_turns < 1:
        raise ValidationError(
            f"assistant_max_turns must be a positive integer, got {config.assistant_max_turns!r}"
        )

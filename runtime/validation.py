"""Validation helpers for Zenith.

These are small, explicit guard functions used at the boundaries of the
system (filesystem paths, configuration, service names). Each raises
`ValidationError` on failure rather than returning a boolean, so a
successful call means the value has already been checked.
"""

from __future__ import annotations

from pathlib import Path

from configs.config import Config
from runtime.exceptions import ValidationError
from runtime.utils.fs_utils import directory_exists
from runtime.utils.text_utils import is_blank_or_padded


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
    """Raise ValidationError if `config` is not a valid Config instance."""
    if not isinstance(config, Config):
        raise ValidationError(
            f"Expected a Config instance, got {type(config).__name__}"
        )

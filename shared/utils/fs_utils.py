"""Filesystem-related helpers."""

from __future__ import annotations

from pathlib import Path


def directory_exists(path: Path) -> bool:
    """Return True if `path` exists and is a directory."""
    return path.is_dir()


def file_exists(path: Path) -> bool:
    """Return True if `path` exists and is a regular file."""
    return path.is_file()

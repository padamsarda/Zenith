"""Path sandboxing: confines tool operations to a configured root directory.

Filesystem, Shell, Git, Diff, and Test Runner tools all operate against
a directory tree rather than the whole filesystem. `resolve_within_root`
is the one guard every one of them runs a path argument through before
touching disk or spawning a process, so "can this path ever escape its
sandbox" has one answer instead of five slightly different ones.
"""

from __future__ import annotations

from pathlib import Path, PurePath

from runtime.exceptions import ToolExecutionError

DEFAULT_MAX_READ_BYTES = 1_000_000


def resolve_within_root(root: Path, raw_path: str | None) -> Path:
    """Resolve `raw_path` against `root`, refusing to let it leave.

    `raw_path` of `None`, `""`, or `"."` resolves to `root` itself. Any
    absolute path, or a relative path whose `..` segments walk outside
    `root` once resolved against the real filesystem (following
    symlinks), is rejected.

    Args:
        root: The sandbox root. Callers are expected to have resolved it
            once already (an absolute, symlink-free path), typically at
            tool construction.
        raw_path: A path relative to `root`, or `None`/`"."` for `root`
            itself.

    Returns:
        The resolved, absolute path. Not guaranteed to exist.

    Raises:
        ToolExecutionError: If `raw_path` is absolute or resolves outside
            `root`.
    """
    if raw_path is None or raw_path in ("", "."):
        return root

    if PurePath(raw_path).is_absolute():
        raise ToolExecutionError(
            f"Path '{raw_path}' must be relative to the sandbox root, not absolute."
        )

    candidate = (root / raw_path).resolve()
    if not candidate.is_relative_to(root):
        raise ToolExecutionError(f"Path '{raw_path}' escapes the sandbox root '{root}'.")
    return candidate


def read_sandboxed_text(
    root: Path, raw_path: str, *, max_bytes: int = DEFAULT_MAX_READ_BYTES
) -> str:
    """Read a UTF-8 text file within `root`, enforcing a size limit.

    Args:
        root: The sandbox root.
        raw_path: Path to the file, relative to `root`.
        max_bytes: Refuse to read a file larger than this many bytes.

    Returns:
        The file's decoded text content.

    Raises:
        ToolExecutionError: If the path escapes `root`, does not exist,
            is not a regular file, exceeds `max_bytes`, or is not valid
            UTF-8 text.
    """
    path = resolve_within_root(root, raw_path)
    if not path.is_file():
        raise ToolExecutionError(f"'{raw_path}' does not exist or is not a file.")

    size = path.stat().st_size
    if size > max_bytes:
        raise ToolExecutionError(
            f"'{raw_path}' is {size} bytes, exceeding the {max_bytes}-byte limit."
        )

    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ToolExecutionError(f"'{raw_path}' is not valid UTF-8 text.") from exc

"""FilesystemTool: sandboxed file and directory operations."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from runtime.capabilities.tool import Tool, ToolParameter
from runtime.exceptions import ToolExecutionError
from runtime.tools.arguments import optional_bool, require_str
from runtime.tools.sandbox import DEFAULT_MAX_READ_BYTES, read_sandboxed_text, resolve_within_root

if TYPE_CHECKING:
    from runtime.commands.context import CommandContext

DEFAULT_LOGGER_NAME = "zenith.tools.filesystem"
OPERATIONS = ("read", "write", "list", "mkdir", "delete", "exists")


@dataclass(frozen=True)
class FilesystemResult:
    """The structured outcome of one filesystem operation.

    Only the fields relevant to `operation` are populated; the rest keep
    their defaults. `str(result)` renders the way a provider should see
    it in its next turn — raw file content for `read`, a newline-per-entry
    listing for `list`, and a plain human-readable message otherwise.
    """

    operation: str
    path: str
    message: str
    content: str | None = None
    entries: tuple[str, ...] = ()
    exists: bool | None = None

    def __str__(self) -> str:
        if self.operation == "read" and self.content is not None:
            return self.content
        if self.operation == "list":
            return "\n".join(self.entries) if self.entries else "(empty directory)"
        return self.message


class FilesystemTool(Tool):
    """Reads, writes, lists, creates, deletes, and checks paths within a sandbox root.

    Every path argument is resolved through
    `runtime.tools.sandbox.resolve_within_root` against the configured
    `root`, so no operation can read, write, or delete anything outside
    the directory tree the tool was constructed with — "well-defined
    interfaces rather than arbitrary unrestricted access" (ADR 0016). It
    is not itself a `PermissionPolicy`: whether this tool may run at all
    for a given call is still the policy's decision, evaluated before
    `invoke` is ever called.
    """

    def __init__(
        self,
        root: Path,
        *,
        max_read_bytes: int = DEFAULT_MAX_READ_BYTES,
        logger: logging.Logger | None = None,
    ) -> None:
        """Create a FilesystemTool sandboxed to `root`.

        Args:
            root: The directory every path argument is resolved against.
                Not required to exist yet — existence is checked per
                operation, not at construction.
            max_read_bytes: Refuse to `read` a file larger than this.
            logger: Defaults to a module logger.
        """
        self._root = root.resolve()
        self._max_read_bytes = max_read_bytes
        self._logger = logger or logging.getLogger(DEFAULT_LOGGER_NAME)

    @property
    def tool_id(self) -> str:
        return "filesystem"

    @property
    def name(self) -> str:
        return "Filesystem"

    @property
    def description(self) -> str:
        return (
            "Reads, writes, lists, creates, deletes, and checks the existence of "
            "files and directories within a sandboxed project root."
        )

    @property
    def parameters(self) -> tuple[ToolParameter, ...]:
        return (
            ToolParameter(
                name="operation",
                description=f"One of: {', '.join(OPERATIONS)}.",
                required=True,
            ),
            ToolParameter(
                name="path",
                description="Path relative to the sandbox root ('.' for the root itself).",
                required=True,
            ),
            ToolParameter(
                name="content",
                description="Text content to write. Required for 'write'.",
                required=False,
            ),
            ToolParameter(
                name="recursive",
                description="For 'delete': remove a non-empty directory and its contents.",
                required=False,
                type="boolean",
            ),
            ToolParameter(
                name="create_parents",
                description="For 'write': create missing parent directories.",
                required=False,
                type="boolean",
            ),
        )

    def invoke(self, context: CommandContext, arguments: dict[str, Any]) -> FilesystemResult:
        """Perform one filesystem operation.

        Raises:
            ToolExecutionError: If `operation` is unrecognized, arguments
                are malformed, or the operation's own guards fail (path
                escapes the sandbox, wrong node type, size limit, etc.).
        """
        operation = require_str(arguments, "operation")
        path = require_str(arguments, "path")
        self._logger.info("Filesystem %s: %s", operation, path)

        if operation == "read":
            return self._read(path)
        if operation == "write":
            return self._write(path, arguments)
        if operation == "list":
            return self._list(path)
        if operation == "mkdir":
            return self._mkdir(path)
        if operation == "delete":
            return self._delete(path, arguments)
        if operation == "exists":
            return self._exists(path)
        raise ToolExecutionError(
            f"Unknown filesystem operation {operation!r}; expected one of {OPERATIONS}."
        )

    def _read(self, path: str) -> FilesystemResult:
        content = read_sandboxed_text(self._root, path, max_bytes=self._max_read_bytes)
        return FilesystemResult(
            operation="read",
            path=path,
            message=f"Read {len(content)} characters from '{path}'.",
            content=content,
        )

    def _write(self, path: str, arguments: dict[str, Any]) -> FilesystemResult:
        content = arguments.get("content")
        if not isinstance(content, str):
            raise ToolExecutionError("'content' must be a string for the 'write' operation.")
        create_parents = optional_bool(arguments, "create_parents", default=False)

        target = resolve_within_root(self._root, path)
        if target.is_dir():
            raise ToolExecutionError(f"'{path}' is a directory, not a file.")
        if not target.parent.exists():
            if not create_parents:
                raise ToolExecutionError(
                    f"Parent directory of '{path}' does not exist; pass create_parents=true."
                )
            target.parent.mkdir(parents=True, exist_ok=True)

        target.write_text(content, encoding="utf-8")
        return FilesystemResult(
            operation="write", path=path, message=f"Wrote {len(content)} characters to '{path}'."
        )

    def _list(self, path: str) -> FilesystemResult:
        target = resolve_within_root(self._root, path)
        if not target.is_dir():
            raise ToolExecutionError(f"'{path}' does not exist or is not a directory.")

        entries = tuple(
            sorted(child.name + "/" if child.is_dir() else child.name for child in target.iterdir())
        )
        noun = "entry" if len(entries) == 1 else "entries"
        return FilesystemResult(
            operation="list",
            path=path,
            message=f"{len(entries)} {noun} in '{path}'.",
            entries=entries,
        )

    def _mkdir(self, path: str) -> FilesystemResult:
        target = resolve_within_root(self._root, path)
        if target.is_file():
            raise ToolExecutionError(f"'{path}' already exists and is a file.")
        target.mkdir(parents=True, exist_ok=True)
        return FilesystemResult(
            operation="mkdir", path=path, message=f"Created directory '{path}'."
        )

    def _delete(self, path: str, arguments: dict[str, Any]) -> FilesystemResult:
        target = resolve_within_root(self._root, path)
        if target == self._root:
            raise ToolExecutionError("Refusing to delete the sandbox root itself.")
        if not target.exists():
            raise ToolExecutionError(f"'{path}' does not exist.")

        recursive = optional_bool(arguments, "recursive", default=False)
        if target.is_dir():
            if any(target.iterdir()) and not recursive:
                raise ToolExecutionError(
                    f"'{path}' is a non-empty directory; pass recursive=true to remove it."
                )
            shutil.rmtree(target)
        else:
            target.unlink()
        return FilesystemResult(operation="delete", path=path, message=f"Deleted '{path}'.")

    def _exists(self, path: str) -> FilesystemResult:
        target = resolve_within_root(self._root, path)
        exists = target.exists()
        kind = "directory" if target.is_dir() else "file" if target.is_file() else None
        message = f"'{path}' {'exists (' + kind + ')' if exists else 'does not exist'}."
        return FilesystemResult(operation="exists", path=path, message=message, exists=exists)

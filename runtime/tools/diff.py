"""DiffTool: unified diffs between inline text or sandboxed files."""

from __future__ import annotations

import difflib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from runtime.capabilities.tool import Tool, ToolParameter
from runtime.exceptions import ToolExecutionError
from runtime.tools.arguments import optional_int, optional_str
from runtime.tools.sandbox import DEFAULT_MAX_READ_BYTES, read_sandboxed_text

if TYPE_CHECKING:
    from runtime.commands.context import CommandContext

DEFAULT_LOGGER_NAME = "zenith.tools.diff"
DEFAULT_CONTEXT_LINES = 3


@dataclass(frozen=True)
class DiffResult:
    """The structured outcome of one diff computation."""

    from_label: str
    to_label: str
    unified_diff: str
    lines_added: int
    lines_removed: int

    @property
    def identical(self) -> bool:
        """Whether the two sides had no differences."""
        return not self.unified_diff

    def __str__(self) -> str:
        if self.unified_diff:
            return self.unified_diff
        return f"No differences between '{self.from_label}' and '{self.to_label}'."


class DiffTool(Tool):
    """Computes a unified diff between two texts, or two sandboxed files.

    Independent of `GitTool`: `git diff` only ever compares things git
    already tracks, so this tool exists for comparing arbitrary text — a
    proposed edit against a file's current content, or two files with no
    git relationship at all. File paths are resolved through
    `runtime.tools.sandbox.read_sandboxed_text` against the configured
    `root`, the same sandboxing convention `FilesystemTool` uses. Purely
    synchronous, in-memory text processing — there is no subprocess to
    time out or cancel here.
    """

    def __init__(
        self,
        root: Path,
        *,
        max_read_bytes: int = DEFAULT_MAX_READ_BYTES,
        logger: logging.Logger | None = None,
    ) -> None:
        """Create a DiffTool sandboxed to `root` for its file-based mode.

        Args:
            root: The directory `from_path`/`to_path` are resolved
                against. Irrelevant to the inline-text mode.
            max_read_bytes: Refuse to read a file larger than this.
            logger: Defaults to a module logger.
        """
        self._root = root.resolve()
        self._max_read_bytes = max_read_bytes
        self._logger = logger or logging.getLogger(DEFAULT_LOGGER_NAME)

    @property
    def tool_id(self) -> str:
        return "diff"

    @property
    def name(self) -> str:
        return "Diff"

    @property
    def description(self) -> str:
        return (
            "Computes a unified diff between two pieces of text, or between two "
            "files within the sandboxed project root."
        )

    @property
    def parameters(self) -> tuple[ToolParameter, ...]:
        return (
            ToolParameter(name="from_text", description="The 'before' text.", required=False),
            ToolParameter(name="to_text", description="The 'after' text.", required=False),
            ToolParameter(
                name="from_path",
                description="The 'before' file, relative to the sandbox root.",
                required=False,
            ),
            ToolParameter(
                name="to_path",
                description="The 'after' file, relative to the sandbox root.",
                required=False,
            ),
            ToolParameter(
                name="context_lines",
                description="Lines of surrounding context in the unified diff. Defaults to 3.",
                required=False,
                type="integer",
            ),
        )

    def invoke(self, context: CommandContext, arguments: dict[str, Any]) -> DiffResult:
        """Compute the requested diff and return its structured result.

        Exactly one pair must be supplied: `from_text` with `to_text`,
        or `from_path` with `to_path`.

        Raises:
            ToolExecutionError: If neither or both pairs are supplied,
                only one side of a pair is given, or a path escapes the
                sandbox root, does not exist, or is not valid UTF-8 text.
        """
        from_text = optional_str(arguments, "from_text")
        to_text = optional_str(arguments, "to_text")
        from_path = optional_str(arguments, "from_path")
        to_path = optional_str(arguments, "to_path")
        context_lines = optional_int(arguments, "context_lines", default=DEFAULT_CONTEXT_LINES)

        text_mode = from_text is not None or to_text is not None
        path_mode = from_path is not None or to_path is not None
        if text_mode and path_mode:
            raise ToolExecutionError(
                "Provide either from_text/to_text or from_path/to_path, not both."
            )
        if text_mode:
            if from_text is None or to_text is None:
                raise ToolExecutionError("Both from_text and to_text are required together.")
            from_label, to_label = "before", "after"
            from_content, to_content = from_text, to_text
        elif path_mode:
            if from_path is None or to_path is None:
                raise ToolExecutionError("Both from_path and to_path are required together.")
            from_label, to_label = from_path, to_path
            from_content = read_sandboxed_text(
                self._root, from_path, max_bytes=self._max_read_bytes
            )
            to_content = read_sandboxed_text(self._root, to_path, max_bytes=self._max_read_bytes)
        else:
            raise ToolExecutionError("Provide either from_text/to_text or from_path/to_path.")

        self._logger.info("Diffing '%s' against '%s'", from_label, to_label)
        return self._diff(from_label, to_label, from_content, to_content, context_lines)

    def _diff(
        self,
        from_label: str,
        to_label: str,
        from_content: str,
        to_content: str,
        context_lines: int,
    ) -> DiffResult:
        from_lines = from_content.splitlines(keepends=True)
        to_lines = to_content.splitlines(keepends=True)
        diff_lines = list(
            difflib.unified_diff(
                from_lines, to_lines, fromfile=from_label, tofile=to_label, n=context_lines
            )
        )
        added = sum(
            1 for line in diff_lines if line.startswith("+") and not line.startswith("+++")
        )
        removed = sum(
            1 for line in diff_lines if line.startswith("-") and not line.startswith("---")
        )
        return DiffResult(
            from_label=from_label,
            to_label=to_label,
            unified_diff="".join(diff_lines),
            lines_added=added,
            lines_removed=removed,
        )

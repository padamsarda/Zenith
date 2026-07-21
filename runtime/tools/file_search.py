"""FileSearchTool: finding files across the places a person actually keeps them."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING, Any

from runtime.capabilities.tool import Tool, ToolParameter
from runtime.exceptions import ToolExecutionError
from runtime.tools.arguments import optional_int, optional_str, require_str

if TYPE_CHECKING:
    from runtime.commands.context import CommandContext

DEFAULT_LOGGER_NAME = "zenith.tools.file_search"
OPERATIONS = ("name", "content", "recent")

DEFAULT_RESULT_LIMIT = 20
MAX_RESULT_LIMIT = 100
DEFAULT_MAX_CONTENT_BYTES = 2_000_000
DEFAULT_MAX_SCANNED = 20_000

# Directories never worth walking: enormous, and nothing a person means
# when they say "find my datasheet". Skipping them is the difference
# between a search that answers in a second and one that appears to hang.
SKIPPED_DIRECTORIES: frozenset[str] = frozenset(
    {
        ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
        "env", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist",
        "build", ".next", ".cache", "site-packages", "AppData", "Library",
        "$RECYCLE.BIN", "System Volume Information", ".idea", ".vscode",
    }
)

# Extensions worth reading for a content search. Everything else is
# binary or generated, where a byte-level match is noise rather than a
# find.
TEXT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".txt", ".md", ".rst", ".log", ".csv", ".tsv", ".json", ".yaml", ".yml",
        ".toml", ".ini", ".cfg", ".conf", ".xml", ".html", ".htm", ".css",
        ".py", ".pyi", ".js", ".ts", ".tsx", ".jsx", ".c", ".h", ".cpp", ".hpp",
        ".rs", ".go", ".java", ".kt", ".rb", ".php", ".sh", ".bat", ".ps1",
        ".sql", ".tex", ".bib", ".ipynb", ".sch", ".kicad_pro", ".kicad_sch",
        ".kicad_pcb", ".net", ".gitignore", ".env",
    }
)


@dataclass(frozen=True)
class FileHit:
    """One file the search matched."""

    path: str
    root: str
    size_bytes: int
    modified_at: datetime
    excerpt: str | None = None

    def __str__(self) -> str:
        stamp = self.modified_at.strftime("%Y-%m-%d %H:%M")
        line = f"{self.path}  ({_human_size(self.size_bytes)}, modified {stamp})"
        return f"{line}\n    {self.excerpt}" if self.excerpt else line


@dataclass(frozen=True)
class FileSearchResult:
    """The structured outcome of one search."""

    operation: str
    query: str
    hits: tuple[FileHit, ...]
    scanned: int
    truncated: bool = False

    def __str__(self) -> str:
        if not self.hits:
            return f"No files matched {self.query!r} (searched {self.scanned} files)."
        noun = "file" if len(self.hits) == 1 else "files"
        header = f"{len(self.hits)} {noun} matching {self.query!r}"
        if self.truncated:
            header += " (more exist; showing the best matches)"
        return header + ":\n" + "\n".join(str(hit) for hit in self.hits)


def _human_size(size_bytes: int) -> str:
    """Render a byte count the way a file manager would."""
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def default_roots() -> dict[str, Path]:
    """The everyday folders to search, for those that exist on this machine.

    Deliberately a person's own document folders and not the whole
    filesystem: searching `C:\\` or `/` would be slow, would surface
    system files nobody meant, and would give a tool with no other
    boundary an unnecessarily large one.
    """
    home = Path.home()
    candidates = {
        "home": home,
        "desktop": home / "Desktop",
        "documents": home / "Documents",
        "downloads": home / "Downloads",
        "onedrive": home / "OneDrive",
    }
    return {name: path for name, path in candidates.items() if path.is_dir()}


class FileSearchTool(Tool):
    """Finds files by name, content, or recency across configured roots.

    The counterpart to `FilesystemTool` (ADR 0016), which is sandboxed to
    a single project root because its job is acting *inside* one. This
    one answers a different question — "where is the thing I'm thinking
    of" — which by nature spans the places a person keeps work, not one
    directory chosen at startup (ADR 0030).

    **Read-only by construction.** It has no operation that writes,
    moves, renames, or deletes: finding is the whole contract. That is
    what makes searching several roots a reasonable thing to allow at
    all, and is why it needs no confirmation step while
    `FilesystemTool`'s `write`/`delete` do.
    """

    def __init__(
        self,
        roots: Mapping[str, Path] | None = None,
        *,
        max_content_bytes: int = DEFAULT_MAX_CONTENT_BYTES,
        max_scanned: int = DEFAULT_MAX_SCANNED,
        logger: logging.Logger | None = None,
    ) -> None:
        """Create a FileSearchTool.

        Args:
            roots: Named directories to search. Defaults to
                `default_roots()`. A deployment with project folders
                elsewhere names them here.
            max_content_bytes: Skip files larger than this for content
                searches.
            max_scanned: Stop after examining this many files. A bound is
                what keeps a search over a large home directory
                predictable rather than open-ended.
            logger: Defaults to a module logger.
        """
        # `is None`, not falsiness: an explicitly empty mapping means
        # "search nothing", and must not fall back to the user's whole
        # home directory. Asking for no roots and silently getting every
        # document would be the worst possible reading of that call.
        configured = default_roots() if roots is None else roots
        self._roots = {name: path.resolve() for name, path in configured.items()}
        self._max_content_bytes = max_content_bytes
        self._max_scanned = max_scanned
        self._logger = logger or logging.getLogger(DEFAULT_LOGGER_NAME)

    @property
    def tool_id(self) -> str:
        return "file_search"

    @property
    def name(self) -> str:
        return "File Search"

    @property
    def description(self) -> str:
        return (
            "Finds files across the user's documents by name pattern, by text content, "
            "or by how recently they changed. Read-only: it locates files, it does not "
            "modify them."
        )

    @property
    def parameters(self) -> tuple[ToolParameter, ...]:
        return (
            ToolParameter(
                name="operation",
                description=(
                    "'name' matches the filename (supports * and ? wildcards), "
                    "'content' searches inside text files, 'recent' lists recently "
                    "modified files."
                ),
                required=True,
            ),
            ToolParameter(
                name="query",
                description=(
                    "What to look for. Required for 'name' and 'content'; for 'recent' "
                    "it optionally filters the filename."
                ),
                required=False,
            ),
            ToolParameter(
                name="root",
                description=(
                    f"Which root to search: {', '.join(sorted(self._roots)) or '(none configured)'}"
                    ". Defaults to all of them."
                ),
                required=False,
            ),
            ToolParameter(
                name="limit",
                description=f"How many results to return. Defaults to {DEFAULT_RESULT_LIMIT}.",
                required=False,
                type="integer",
            ),
        )

    def invoke(self, context: CommandContext, arguments: dict[str, Any]) -> FileSearchResult:
        """Run one search.

        Raises:
            ToolExecutionError: If `operation` is unrecognized, a required
                argument is missing, `root` names an unconfigured root, or
                `limit` is out of range.
        """
        operation = require_str(arguments, "operation")
        if operation not in OPERATIONS:
            raise ToolExecutionError(
                f"Unknown file search operation {operation!r}; expected one of {OPERATIONS}."
            )

        limit = optional_int(arguments, "limit", default=DEFAULT_RESULT_LIMIT)
        if not 1 <= limit <= MAX_RESULT_LIMIT:
            raise ToolExecutionError(
                f"'limit' must be between 1 and {MAX_RESULT_LIMIT}, got {limit}."
            )

        roots = self._resolve_roots(arguments)
        query = optional_str(arguments, "query") or ""
        if operation in ("name", "content") and not query.strip():
            raise ToolExecutionError(f"'query' is required for the {operation!r} operation.")

        self._logger.info("File search (%s): %r", operation, query)
        if operation == "name":
            return self._by_name(query, roots, limit)
        if operation == "content":
            return self._by_content(query, roots, limit)
        return self._recent(query, roots, limit)

    # --- operations ------------------------------------------------

    def _by_name(
        self, query: str, roots: dict[str, Path], limit: int
    ) -> FileSearchResult:
        """Match against the filename, newest first among matches."""
        pattern = query if any(character in query for character in "*?") else f"*{query}*"
        hits: list[FileHit] = []
        scanned = 0
        for root_name, root, path in self._walk(roots):
            scanned += 1
            if fnmatch(path.name.lower(), pattern.lower()):
                hits.append(self._describe(path, root_name, root))
        hits.sort(key=lambda hit: hit.modified_at, reverse=True)
        return FileSearchResult(
            operation="name",
            query=query,
            hits=tuple(hits[:limit]),
            scanned=scanned,
            truncated=len(hits) > limit,
        )

    def _by_content(
        self, query: str, roots: dict[str, Path], limit: int
    ) -> FileSearchResult:
        """Search inside text files, returning the first matching line as an excerpt."""
        needle = query.lower()
        hits: list[FileHit] = []
        scanned = 0
        for root_name, root, path in self._walk(roots):
            if path.suffix.lower() not in TEXT_EXTENSIONS:
                continue
            scanned += 1
            excerpt = self._first_match(path, needle)
            if excerpt is not None:
                hits.append(self._describe(path, root_name, root, excerpt=excerpt))
                if len(hits) >= limit:
                    break
        hits.sort(key=lambda hit: hit.modified_at, reverse=True)
        return FileSearchResult(
            operation="content",
            query=query,
            hits=tuple(hits[:limit]),
            scanned=scanned,
            truncated=len(hits) >= limit,
        )

    def _recent(
        self, query: str, roots: dict[str, Path], limit: int
    ) -> FileSearchResult:
        """List the most recently modified files, optionally filtered by name."""
        pattern = f"*{query}*".lower() if query.strip() else "*"
        hits: list[FileHit] = []
        scanned = 0
        for root_name, root, path in self._walk(roots):
            scanned += 1
            if fnmatch(path.name.lower(), pattern):
                hits.append(self._describe(path, root_name, root))
        hits.sort(key=lambda hit: hit.modified_at, reverse=True)
        return FileSearchResult(
            operation="recent",
            query=query or "(any)",
            hits=tuple(hits[:limit]),
            scanned=scanned,
            truncated=len(hits) > limit,
        )

    # --- walking ------------------------------------------------

    def _walk(self, roots: dict[str, Path]) -> Iterator[tuple[str, Path, Path]]:
        """Yield `(root_name, root, file_path)` for every file worth examining.

        Prunes `SKIPPED_DIRECTORIES` in place (mutating `os.walk`'s
        directory list is how pruning is done, and is why this uses
        `os.walk` rather than `Path.rglob` — the latter has no way to
        avoid descending into `node_modules`). Stops at `max_scanned`, so
        a search over a large home directory stays predictable.
        """
        seen = 0
        for root_name, root in roots.items():
            for directory, subdirectories, filenames in os.walk(root, onerror=lambda _: None):
                subdirectories[:] = [
                    name
                    for name in subdirectories
                    if name not in SKIPPED_DIRECTORIES and not name.startswith(".")
                ]
                for filename in filenames:
                    if seen >= self._max_scanned:
                        return
                    seen += 1
                    yield root_name, root, Path(directory) / filename

    def _first_match(self, path: Path, needle: str) -> str | None:
        """Return the first line of `path` containing `needle`, or None.

        Unreadable files (permissions, a lock, an encoding that is not
        text after all) are skipped rather than raised: a search that
        aborts on one awkward file is useless on a real filesystem.
        """
        try:
            if path.stat().st_size > self._max_content_bytes:
                return None
            with path.open("r", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    if needle in line.lower():
                        return line.strip()[:200]
        except OSError:
            return None
        return None

    def _describe(
        self, path: Path, root_name: str, root: Path, *, excerpt: str | None = None
    ) -> FileHit:
        """Build a `FileHit`, reporting the path relative to its root where possible."""
        try:
            stat = path.stat()
            size, modified = stat.st_size, stat.st_mtime
        except OSError:
            size, modified = 0, 0.0
        # Forward slashes throughout, including on Windows: a path built
        # by joining a root name to an OS-separated tail would otherwise
        # render as "work/notes\\file.md", which reads as neither.
        try:
            shown = path.relative_to(root).as_posix()
        except ValueError:
            shown = path.as_posix()
        return FileHit(
            path=f"{root_name}/{shown}",
            root=root_name,
            size_bytes=size,
            modified_at=datetime.fromtimestamp(modified, tz=timezone.utc),
            excerpt=excerpt,
        )

    def _resolve_roots(self, arguments: dict[str, Any]) -> dict[str, Path]:
        """Resolve the `root` argument to the roots to search."""
        if not self._roots:
            raise ToolExecutionError("No search roots are configured.")
        requested = optional_str(arguments, "root")
        if requested is None:
            return dict(self._roots)
        name = requested.strip().lower()
        if name not in self._roots:
            raise ToolExecutionError(
                f"Unknown root {requested!r}; expected one of {sorted(self._roots)}."
            )
        return {name: self._roots[name]}

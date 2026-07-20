"""GitTool: engineering-focused git operations against a repository."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from runtime.capabilities.tool import Tool, ToolParameter
from runtime.exceptions import ToolExecutionError
from runtime.tools.arguments import (
    optional_bool,
    optional_int,
    optional_sequence_str,
    optional_str,
    require_str,
)
from runtime.tools.process import ProcessOutcome, run_process
from runtime.tools.sandbox import resolve_within_root

if TYPE_CHECKING:
    from runtime.commands.context import CommandContext

DEFAULT_LOGGER_NAME = "zenith.tools.git"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_LOG_MAX_COUNT = 20
LOG_FORMAT = "%H\x1f%an\x1f%ad\x1f%s"
OPERATIONS = ("status", "diff", "add", "commit", "branch", "checkout", "log", "reset")


@dataclass(frozen=True)
class GitLogEntry:
    """One parsed `git log` entry."""

    commit_hash: str
    author: str
    date: str
    subject: str

    def __str__(self) -> str:
        return f"{self.commit_hash[:8]} {self.date} {self.author}: {self.subject}"


@dataclass(frozen=True)
class GitResult:
    """The structured outcome of one git operation.

    `entries` is populated only for `log`; every other operation leaves
    it empty and is read through `stdout`/`stderr` instead — git itself
    is the source of truth for `status`/`diff`/etc., so this tool
    reports its raw text rather than re-parsing it.
    """

    operation: str
    exit_code: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    entries: tuple[GitLogEntry, ...] = ()

    @property
    def success(self) -> bool:
        """Whether git exited zero."""
        return self.exit_code == 0

    def __str__(self) -> str:
        if self.operation == "log" and self.entries:
            return "\n".join(str(entry) for entry in self.entries)
        parts = []
        if self.stdout.strip():
            parts.append(self.stdout.rstrip())
        if self.stderr.strip():
            parts.append(f"--- stderr ---\n{self.stderr.rstrip()}")
        if not parts:
            parts.append(f"git {self.operation}: exit {self.exit_code}")
        return "\n".join(parts)


class GitTool(Tool):
    """Runs a fixed set of engineering-focused git operations.

    Deliberately narrower than the `git` CLI (ADR 0016): `status`,
    `diff`, `add`, `commit`, `branch` (informational listing only),
    `checkout`, `log`, and `reset` (mixed mode only). There is no `push`,
    `pull`, `clone`, or `--hard` reset — nothing this tool does can reach
    a remote or discard already-made commits or working-tree edits.
    `add`/`diff`/`reset` path arguments are resolved through
    `resolve_within_root` against the configured repository root, the
    same sandboxing convention `FilesystemTool` uses.

    Every operation returns a structured `GitResult` regardless of git's
    own exit code — a failing precondition git itself reports (nothing
    to commit, merge conflict, unknown ref) is data for the caller to
    react to, not an exception. `ToolExecutionError` is reserved for
    what this tool's own guards catch: a missing repository, a path
    escaping the sandbox, or malformed arguments.
    """

    def __init__(
        self,
        repo_root: Path,
        *,
        default_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        logger: logging.Logger | None = None,
    ) -> None:
        """Create a GitTool bound to the repository at `repo_root`.

        Args:
            repo_root: The repository's working directory. Not required
                to contain a `.git` yet — checked per invocation.
            default_timeout_seconds: Timeout applied to every git
                invocation.
            logger: Defaults to a module logger.
        """
        self._repo_root = repo_root.resolve()
        self._default_timeout_seconds = default_timeout_seconds
        self._logger = logger or logging.getLogger(DEFAULT_LOGGER_NAME)

    @property
    def tool_id(self) -> str:
        return "git"

    @property
    def name(self) -> str:
        return "Git"

    @property
    def description(self) -> str:
        return (
            "Runs git operations (status, diff, add, commit, branch, checkout, log, "
            "reset) against a repository. Deliberately excludes push, pull, and "
            "--hard resets: nothing this tool does can reach a remote or discard "
            "commits or working-tree edits."
        )

    @property
    def parameters(self) -> tuple[ToolParameter, ...]:
        return (
            ToolParameter(
                name="operation", description=f"One of: {', '.join(OPERATIONS)}.", required=True
            ),
            ToolParameter(
                name="path",
                description="A single path, relative to the repository root, scoping 'diff' or 'log'.",
                required=False,
            ),
            ToolParameter(
                name="paths",
                description="One or more paths, relative to the repository root, for 'add' or 'reset'.",
                required=False,
                type="array",
            ),
            ToolParameter(
                name="staged",
                description="For 'diff': show the staged (--cached) diff instead of the working tree.",
                required=False,
                type="boolean",
            ),
            ToolParameter(
                name="message", description="The commit message. Required for 'commit'.",
                required=False,
            ),
            ToolParameter(
                name="all",
                description="For 'commit': stage all tracked, modified files first (-a).",
                required=False,
                type="boolean",
            ),
            ToolParameter(
                name="ref",
                description="A commit-ish. Required for 'checkout'; an optional target for 'reset'.",
                required=False,
            ),
            ToolParameter(
                name="create",
                description="For 'checkout': create 'ref' as a new branch (-b) instead of switching to it.",
                required=False,
                type="boolean",
            ),
            ToolParameter(
                name="max_count",
                description="For 'log': maximum number of commits to return. Defaults to 20.",
                required=False,
                type="integer",
            ),
        )

    def invoke(self, context: CommandContext, arguments: dict[str, Any]) -> GitResult:
        """Run the requested git operation and return its structured result.

        Raises:
            ToolExecutionError: If `operation` is unrecognized, required
                arguments are missing, a path escapes the repository
                root, or `repo_root` is not a git repository.
            CommandCancelledError: If the command's cancellation token is
                already set.
        """
        operation = require_str(arguments, "operation")
        self._require_repo()

        if operation == "status":
            return self._result("status", self._execute(["status", "--porcelain=v1", "--branch"], context))
        if operation == "diff":
            return self._diff(arguments, context)
        if operation == "add":
            return self._add(arguments, context)
        if operation == "commit":
            return self._commit(arguments, context)
        if operation == "branch":
            return self._result("branch", self._execute(["branch", "--list", "-a"], context))
        if operation == "checkout":
            return self._checkout(arguments, context)
        if operation == "log":
            return self._log(arguments, context)
        if operation == "reset":
            return self._reset(arguments, context)
        raise ToolExecutionError(
            f"Unknown git operation {operation!r}; expected one of {OPERATIONS}."
        )

    def _require_repo(self) -> None:
        if not (self._repo_root / ".git").exists():
            raise ToolExecutionError(f"'{self._repo_root}' is not a git repository (no .git found).")

    def _execute(self, git_args: list[str], context: CommandContext) -> ProcessOutcome:
        self._logger.info("git %s", " ".join(git_args))
        return run_process(
            ["git", *git_args],
            cwd=self._repo_root,
            env=os.environ,
            timeout_seconds=self._default_timeout_seconds,
            cancellation_token=context.cancellation_token,
        )

    def _result(
        self, operation: str, outcome: ProcessOutcome, *, entries: tuple[GitLogEntry, ...] = ()
    ) -> GitResult:
        return GitResult(
            operation=operation,
            exit_code=outcome.exit_code,
            stdout=outcome.stdout,
            stderr=outcome.stderr,
            duration_seconds=outcome.duration_seconds,
            entries=entries,
        )

    def _resolve_path(self, raw_path: str) -> str:
        return str(resolve_within_root(self._repo_root, raw_path))

    def _diff(self, arguments: dict[str, Any], context: CommandContext) -> GitResult:
        staged = optional_bool(arguments, "staged", default=False)
        path = optional_str(arguments, "path")
        args = ["diff"]
        if staged:
            args.append("--cached")
        if path:
            args += ["--", self._resolve_path(path)]
        return self._result("diff", self._execute(args, context))

    def _add(self, arguments: dict[str, Any], context: CommandContext) -> GitResult:
        paths = optional_sequence_str(arguments, "paths")
        if not paths:
            raise ToolExecutionError("'paths' must contain at least one path for 'add'.")
        resolved = [self._resolve_path(path) for path in paths]
        return self._result("add", self._execute(["add", "--", *resolved], context))

    def _commit(self, arguments: dict[str, Any], context: CommandContext) -> GitResult:
        message = require_str(arguments, "message")
        args = ["commit", "-m", message]
        if optional_bool(arguments, "all", default=False):
            args.append("-a")
        return self._result("commit", self._execute(args, context))

    def _checkout(self, arguments: dict[str, Any], context: CommandContext) -> GitResult:
        ref = require_str(arguments, "ref")
        args = ["checkout", "-b", ref] if optional_bool(arguments, "create", default=False) else [
            "checkout",
            ref,
        ]
        return self._result("checkout", self._execute(args, context))

    def _log(self, arguments: dict[str, Any], context: CommandContext) -> GitResult:
        max_count = optional_int(arguments, "max_count", default=DEFAULT_LOG_MAX_COUNT)
        path = optional_str(arguments, "path")
        args = ["log", f"-n{max_count}", "--date=iso-strict", f"--pretty=format:{LOG_FORMAT}"]
        if path:
            args += ["--", self._resolve_path(path)]
        outcome = self._execute(args, context)
        entries = self._parse_log(outcome.stdout) if outcome.exit_code == 0 else ()
        return self._result("log", outcome, entries=entries)

    def _reset(self, arguments: dict[str, Any], context: CommandContext) -> GitResult:
        ref = optional_str(arguments, "ref")
        paths = optional_sequence_str(arguments, "paths")
        resolved_paths = [self._resolve_path(path) for path in paths]
        args = ["reset"]
        if ref:
            args.append(ref)
        if resolved_paths:
            args += ["--", *resolved_paths]
        return self._result("reset", self._execute(args, context))

    def _parse_log(self, stdout: str) -> tuple[GitLogEntry, ...]:
        entries = []
        for line in stdout.splitlines():
            if not line.strip():
                continue
            parts = line.split("\x1f")
            if len(parts) != 4:
                continue
            commit_hash, author, date, subject = parts
            entries.append(
                GitLogEntry(commit_hash=commit_hash, author=author, date=date, subject=subject)
            )
        return tuple(entries)

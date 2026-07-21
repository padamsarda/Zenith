"""RevisionProbe: the seam for recording what a session changed on disk.

A finished session reports a prose summary, and until now that summary
was the *only* evidence a session did anything. Prose is what the
provider claims; it is not what happened. After an unattended run the
question a human actually asks — "show me what moved" — had no answer in
durable state at all, which made the engineering report a record of
assertions rather than of work.

A `RevisionProbe` closes that gap the way `VerificationPolicy` and
`StopCondition` close theirs: the engine supplies facts (a project, and
later two revisions it stamped), the policy decides what they mean, and
the default implementation changes nothing for anyone who has not opted
in. The probe is deliberately ignorant of *why* it is being asked —
stamping at dispatch and stamping at close are the same call — so the
dispatcher and the session-closing path share one method rather than
two half-duplicated ones.

Two properties matter more than the git plumbing:

Nothing here raises. A missing `git`, a project that is not a
repository, a repository with no commits yet, a revision that has since
been garbage-collected — every one of these is reported as `None`, an
absent measurement. Reporting is an observation, not a step in the work,
and an observation that cannot be made must never take down the tick
that was doing the real thing. This is the same discipline ADR 0019
imposes on `verify`, applied to a seam where it matters more, because a
probe runs on paths that have already succeeded.

What it measures is committed history, not the working tree. Two
revisions and the diff between them say nothing about work a session
left uncommitted, so a session that edits files without committing
reads as `RevisionDiff(0, 0, 0)` — an honest zero rather than a wrong
number. That is a real limit of revision-to-revision measurement, and
callers should read an empty diff as "nothing landed in history", not
as "the session did nothing".
"""

from __future__ import annotations

import logging
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass

from engineering_manager.domain.project import Project
from engineering_manager.exceptions import OrchestrationError

DEFAULT_LOGGER_NAME = "zenith.em"
DEFAULT_GIT_EXECUTABLE = "git"
DEFAULT_TIMEOUT_SECONDS = 30.0

# `git diff --numstat` emits one line per file as
# "<insertions>\t<deletions>\t<path>", with "-" in both counts for a
# binary file, whose line-level change is undefined rather than zero.
NUMSTAT_FIELDS = 3
BINARY_COUNT = "-"


@dataclass(frozen=True)
class RevisionDiff:
    """How much changed between two revisions of a project."""

    files_changed: int
    insertions: int
    deletions: int


class RevisionProbe(ABC):
    """Records where a project stood, and what moved between two points."""

    @abstractmethod
    def current_revision(self, project: Project) -> str | None:
        """Return `project`'s current revision, or None if it can't be read.

        Called once when a session is dispatched and once when it closes,
        so the identifier must be stable enough to compare across that
        span — a commit hash, not a branch name that could be moved
        underneath it.
        """

    @abstractmethod
    def changes_between(
        self, project: Project, start_revision: str, end_revision: str
    ) -> RevisionDiff | None:
        """Return what changed in `project` between two revisions.

        Returns None when the measurement cannot be made — an unknown
        revision, a missing tool, a project that is not under version
        control. `None` means "unknown", which is not the same as
        `RevisionDiff(0, 0, 0)`, which means "measured, and nothing
        landed"; callers must be able to tell those apart. Implementations
        report trouble this way rather than raising, so a probe can never
        turn completed work into a failed tick.
        """


class NoRevisionProbe(RevisionProbe):
    """Records nothing. The default, and behavior before this seam existed."""

    def current_revision(self, project: Project) -> str | None:
        """Return None, always."""
        return None

    def changes_between(
        self, project: Project, start_revision: str, end_revision: str
    ) -> RevisionDiff | None:
        """Return None, always."""
        return None


class GitRevisionProbe(RevisionProbe):
    """Reads revisions and diff statistics from git.

    Shells out rather than reimplementing anything: `git rev-parse HEAD`
    to stamp a point in history, `git diff --numstat` to measure between
    two. Both commands run synchronously inside the caller's tick under a
    bounded `timeout_seconds`, and both are cheap on any repository the
    engine is realistically driving.
    """

    def __init__(
        self,
        git_executable: str = DEFAULT_GIT_EXECUTABLE,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        logger: logging.Logger | None = None,
    ) -> None:
        """Create the probe.

        Raises:
            OrchestrationError: If `git_executable` is empty or
                `timeout_seconds` is not positive.
        """
        if not git_executable:
            raise OrchestrationError("GitRevisionProbe requires a git executable.")
        if timeout_seconds <= 0:
            raise OrchestrationError(f"timeout_seconds must be positive, got {timeout_seconds!r}")
        self._git_executable = git_executable
        self._timeout_seconds = timeout_seconds
        self._logger = logger or logging.getLogger(DEFAULT_LOGGER_NAME)

    def current_revision(self, project: Project) -> str | None:
        """Resolve HEAD in `project.root_path`.

        A repository with no commits yet has no HEAD to resolve, and
        reports None like any other unreadable revision.
        """
        output = self._run(project, ("rev-parse", "HEAD"))
        if output is None:
            return None
        revision = output.strip()
        return revision or None

    def changes_between(
        self, project: Project, start_revision: str, end_revision: str
    ) -> RevisionDiff | None:
        """Sum `git diff --numstat` between the two revisions."""
        if not _is_safe_revision(start_revision) or not _is_safe_revision(end_revision):
            return None
        # The trailing `--` stops git reading a revision that no longer
        # exists as a pathspec, which would silently diff nothing instead
        # of failing.
        output = self._run(project, ("diff", "--numstat", start_revision, end_revision, "--"))
        if output is None:
            return None
        return _parse_numstat(output)

    def _run(self, project: Project, arguments: tuple[str, ...]) -> str | None:
        """Run one git command in the project root, or None if it fails.

        Every failure mode collapses to None: git absent or unlaunchable,
        the project directory gone, the command timing out, or git itself
        exiting non-zero because the directory is not a repository or a
        revision is unknown.
        """
        if not project.root_path.is_dir():
            self._logger.debug(
                "Revision probe skipped: %s does not exist.", project.root_path
            )
            return None
        try:
            completed = subprocess.run(
                [self._git_executable, *arguments],
                cwd=project.root_path,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                encoding="utf-8",
                errors="ignore",
            )
        except subprocess.TimeoutExpired:
            self._logger.warning(
                "Revision probe for project %s timed out after %ss.",
                project.project_id,
                self._timeout_seconds,
            )
            return None
        except OSError as exc:
            self._logger.warning(
                "Revision probe for project %s could not run git: %s", project.project_id, exc
            )
            return None

        if completed.returncode != 0:
            self._logger.debug(
                "Revision probe for project %s: git %s exited %s.",
                project.project_id,
                arguments[0],
                completed.returncode,
            )
            return None
        return completed.stdout


def _is_safe_revision(revision: str) -> bool:
    """True if `revision` can be passed to git as a revision argument.

    Revisions reach this module from the store, so a blank or
    option-looking value is a corrupted stamp rather than a caller error
    — refusing it here keeps a bad row from turning into an unintended
    git invocation.
    """
    return bool(revision) and not revision.startswith("-")


def _parse_numstat(output: str) -> RevisionDiff:
    """Total one `git diff --numstat` report.

    A binary file counts toward `files_changed` but contributes no line
    counts, since it has none to contribute. Unparseable lines are
    skipped rather than guessed at.
    """
    files_changed = 0
    insertions = 0
    deletions = 0
    for line in output.splitlines():
        fields = line.split("\t", NUMSTAT_FIELDS - 1)
        if len(fields) < NUMSTAT_FIELDS:
            continue
        added, removed, _path = fields
        files_changed += 1
        if added == BINARY_COUNT or removed == BINARY_COUNT:
            continue
        try:
            insertions += int(added)
            deletions += int(removed)
        except ValueError:
            continue
    return RevisionDiff(files_changed=files_changed, insertions=insertions, deletions=deletions)

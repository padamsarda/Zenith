"""Tests for RevisionProbe and its implementations."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from engineering_manager.domain.project import Project
from engineering_manager.exceptions import OrchestrationError
from engineering_manager.orchestration.revisions import (
    GitRevisionProbe,
    NoRevisionProbe,
    RevisionDiff,
)

# Every git-backed test needs the real binary; the probe's contract is
# about what git actually reports, so faking it would test nothing.
requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

UNKNOWN_REVISION = "0" * 40


def _project(root_path: Path) -> Project:
    return Project(project_id="zenith", name="Zenith", root_path=root_path)


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
        errors="ignore",
    )
    return completed.stdout.strip()


def _repo(root: Path) -> Path:
    """Initialize an isolated repository with committer identity set.

    The identity and signing settings are written locally so the suite
    does not depend on — or inherit — whatever global git config the
    machine running it happens to have.
    """
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "--quiet")
    _git(root, "config", "user.email", "em@example.invalid")
    _git(root, "config", "user.name", "Engineering Manager")
    _git(root, "config", "commit.gpgsign", "false")
    return root


def _commit(root: Path, message: str) -> str:
    _git(root, "add", "-A")
    _git(root, "commit", "--quiet", "-m", message)
    return _git(root, "rev-parse", "HEAD")


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def test_no_revision_probe_records_no_revision(tmp_path: Path) -> None:
    assert NoRevisionProbe().current_revision(_project(tmp_path)) is None


def test_no_revision_probe_records_no_changes(tmp_path: Path) -> None:
    probe = NoRevisionProbe()

    assert probe.changes_between(_project(tmp_path), "abc123", "def456") is None


@requires_git
def test_git_revision_probe_resolves_head(tmp_path: Path) -> None:
    root = _repo(tmp_path / "repo")
    _write(root / "a.txt", "one\n")
    expected = _commit(root, "first")

    assert GitRevisionProbe().current_revision(_project(root)) == expected


@requires_git
def test_git_revision_probe_reports_no_revision_before_first_commit(tmp_path: Path) -> None:
    root = _repo(tmp_path / "repo")

    assert GitRevisionProbe().current_revision(_project(root)) is None


@requires_git
def test_git_revision_probe_reports_no_revision_outside_a_repository(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()

    assert GitRevisionProbe().current_revision(_project(plain)) is None


def test_git_revision_probe_reports_no_revision_when_project_missing(tmp_path: Path) -> None:
    assert GitRevisionProbe().current_revision(_project(tmp_path / "gone")) is None


@requires_git
def test_git_revision_probe_counts_files_insertions_and_deletions(tmp_path: Path) -> None:
    root = _repo(tmp_path / "repo")
    _write(root / "a.txt", "1\n2\n3\n")
    _write(root / "b.txt", "x\n")
    start = _commit(root, "first")
    _write(root / "a.txt", "1\n2\n3\n4\n")
    (root / "b.txt").unlink()
    _write(root / "c.txt", "new\n")
    end = _commit(root, "second")

    diff = GitRevisionProbe().changes_between(_project(root), start, end)

    assert diff == RevisionDiff(files_changed=3, insertions=2, deletions=1)


@requires_git
def test_git_revision_probe_reports_an_empty_diff_for_identical_revisions(tmp_path: Path) -> None:
    root = _repo(tmp_path / "repo")
    _write(root / "a.txt", "one\n")
    revision = _commit(root, "first")

    diff = GitRevisionProbe().changes_between(_project(root), revision, revision)

    assert diff == RevisionDiff(files_changed=0, insertions=0, deletions=0)


@requires_git
def test_git_revision_probe_counts_a_binary_file_without_line_counts(tmp_path: Path) -> None:
    root = _repo(tmp_path / "repo")
    _write(root / "a.txt", "one\n")
    start = _commit(root, "first")
    (root / "image.bin").write_bytes(b"\x00\x01\x02\x00")
    end = _commit(root, "second")

    diff = GitRevisionProbe().changes_between(_project(root), start, end)

    assert diff == RevisionDiff(files_changed=1, insertions=0, deletions=0)


@requires_git
def test_git_revision_probe_reports_no_changes_for_an_unknown_revision(tmp_path: Path) -> None:
    root = _repo(tmp_path / "repo")
    _write(root / "a.txt", "one\n")
    start = _commit(root, "first")

    assert GitRevisionProbe().changes_between(_project(root), start, UNKNOWN_REVISION) is None


@requires_git
@pytest.mark.parametrize("revision", ["", "--output=/tmp/pwned", "-x"])
def test_git_revision_probe_refuses_unusable_revisions(tmp_path: Path, revision: str) -> None:
    root = _repo(tmp_path / "repo")
    _write(root / "a.txt", "one\n")
    start = _commit(root, "first")

    assert GitRevisionProbe().changes_between(_project(root), start, revision) is None
    assert GitRevisionProbe().changes_between(_project(root), revision, start) is None


def test_git_revision_probe_reports_no_revision_when_git_is_missing(tmp_path: Path) -> None:
    probe = GitRevisionProbe("definitely-not-a-real-git-executable")

    assert probe.current_revision(_project(tmp_path)) is None


def test_git_revision_probe_reports_no_changes_when_git_is_missing(tmp_path: Path) -> None:
    probe = GitRevisionProbe("definitely-not-a-real-git-executable")

    assert probe.changes_between(_project(tmp_path), "abc123", "def456") is None


def test_git_revision_probe_reports_no_revision_on_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _timeout(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd="git", timeout=0.1)

    monkeypatch.setattr(subprocess, "run", _timeout)

    assert GitRevisionProbe(timeout_seconds=0.1).current_revision(_project(tmp_path)) is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"git_executable": ""},
        {"timeout_seconds": 0},
        {"timeout_seconds": -1},
    ],
)
def test_git_revision_probe_rejects_bad_construction(kwargs: dict[str, object]) -> None:
    defaults: dict[str, object] = {"git_executable": "git", "timeout_seconds": 5.0}
    defaults.update(kwargs)

    with pytest.raises(OrchestrationError):
        GitRevisionProbe(
            defaults["git_executable"],  # type: ignore[arg-type]
            timeout_seconds=defaults["timeout_seconds"],  # type: ignore[arg-type]
        )

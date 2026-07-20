"""Tests for Claude Code CLI subprocess plumbing."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from engineering_manager.providers.claude_code_process import (
    OutputDrain,
    account_env,
    default_launcher,
)


def test_account_env_overrides_anthropic_api_key_when_set() -> None:
    environ = {"PATH": "/usr/bin", "ZENITH_CLAUDE_PERSONAL_API_KEY": "sk-test-123"}

    env = account_env("personal", environ)

    assert env["ANTHROPIC_API_KEY"] == "sk-test-123"
    assert env["PATH"] == "/usr/bin"


def test_account_env_normalizes_account_id() -> None:
    environ = {"ZENITH_CLAUDE_MY_WORK_ACCT_API_KEY": "sk-work"}

    env = account_env("my-work.acct", environ)

    assert env["ANTHROPIC_API_KEY"] == "sk-work"


def test_account_env_passes_through_when_no_override_is_set() -> None:
    environ = {"PATH": "/usr/bin"}

    env = account_env("personal", environ)

    assert "ANTHROPIC_API_KEY" not in env
    assert env == {"PATH": "/usr/bin"}


def test_account_env_does_not_mutate_input() -> None:
    environ = {"ZENITH_CLAUDE_PERSONAL_API_KEY": "sk-test"}

    account_env("personal", environ)

    assert "ANTHROPIC_API_KEY" not in environ


def test_account_env_defaults_to_the_real_process_environment(monkeypatch) -> None:
    monkeypatch.setenv("ZENITH_CLAUDE_DEFAULT_API_KEY", "sk-default")

    env = account_env("default")

    assert env["ANTHROPIC_API_KEY"] == "sk-default"


def test_default_launcher_runs_command_and_captures_combined_output(tmp_path: Path) -> None:
    process = default_launcher(
        [sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr)"],
        dict(os.environ),
        tmp_path,
    )
    drain = OutputDrain(process.stdout)
    process.wait(timeout=10)
    drain.join()

    assert process.returncode == 0
    assert "out" in drain.text()
    assert "err" in drain.text()


def test_default_launcher_missing_executable_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        default_launcher(["non_existent_executable_12345"], dict(os.environ), tmp_path)


def test_output_drain_captures_lines_as_they_are_written() -> None:
    drain = OutputDrain(iter(["one\n", "two\n"]))
    drain.join()

    assert drain.text() == "one\ntwo\n"


def test_output_drain_survives_a_closed_stream() -> None:
    class ClosedStream:
        def __iter__(self):
            return self

        def __next__(self):
            raise ValueError("I/O operation on closed file")

    drain = OutputDrain(ClosedStream())
    drain.join()

    assert drain.text() == ""

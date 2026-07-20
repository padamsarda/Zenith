"""Tests for interpret_exit, Claude Code output interpretation."""

from __future__ import annotations

from engineering_manager.providers.base import ProviderSessionState
from engineering_manager.providers.claude_code_output import interpret_exit


def test_clean_exit_with_json_result_is_finished() -> None:
    output = (
        '{"is_error": false, "result": "Docs written.", '
        '"usage": {"input_tokens": 10, "output_tokens": 20}, "total_cost_usd": 0.01}'
    )

    status = interpret_exit(output, 0)

    assert status.state is ProviderSessionState.FINISHED
    assert status.detail == "Docs written."
    assert status.usage == {"input_tokens": 10, "output_tokens": 20, "total_cost_usd": 0.01}


def test_clean_exit_with_is_error_is_failed() -> None:
    output = '{"is_error": true, "result": "could not comply"}'

    status = interpret_exit(output, 0)

    assert status.state is ProviderSessionState.FAILED
    assert status.detail == "could not comply"


def test_clean_exit_with_non_json_output_is_finished_with_raw_text() -> None:
    status = interpret_exit("Plain text output\n", 0)

    assert status.state is ProviderSessionState.FINISHED
    assert status.detail == "Plain text output"


def test_clean_exit_with_empty_output_has_no_detail() -> None:
    status = interpret_exit("   \n", 0)

    assert status.state is ProviderSessionState.FINISHED
    assert status.detail is None


def test_json_result_without_usage_reports_no_usage() -> None:
    status = interpret_exit('{"is_error": false, "result": "done"}', 0)

    assert status.usage is None


def test_json_preceded_by_incidental_text_falls_back_to_last_line() -> None:
    output = 'Some startup banner\n{"is_error": false, "result": "done"}'

    status = interpret_exit(output, 0)

    assert status.state is ProviderSessionState.FINISHED
    assert status.detail == "done"


def test_nonzero_exit_with_session_limit_line_is_limit_reached() -> None:
    output = "You've hit your session limit · resets 1:40am (Asia/Calcutta)\n"

    status = interpret_exit(output, 1)

    assert status.state is ProviderSessionState.LIMIT_REACHED
    assert status.resume_at is not None
    assert "session limit" in status.detail


def test_nonzero_exit_without_session_limit_is_failed_with_last_line() -> None:
    output = "some error\ntraceback line\n"

    status = interpret_exit(output, 1)

    assert status.state is ProviderSessionState.FAILED
    assert status.detail == "traceback line"


def test_nonzero_exit_with_no_output_reports_exit_code() -> None:
    status = interpret_exit("", 42)

    assert status.state is ProviderSessionState.FAILED
    assert status.detail == "exit code 42"

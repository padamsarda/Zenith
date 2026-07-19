"""Tests for the Zenith Watchdog."""

from __future__ import annotations

import sys
import unittest.mock as mock
from datetime import datetime, timedelta
import zoneinfo
import pytest

from engineering_tools.watchdog import watchdog


def test_parse_reset_time_basic_am() -> None:
    # 1:40am today
    ref = datetime(2026, 7, 17, 1, 0, 0, tzinfo=zoneinfo.ZoneInfo("Asia/Calcutta"))
    res = watchdog.parse_reset_time(
        "You've hit your session limit · resets 1:40am (Asia/Calcutta)", ref_now=ref
    )
    assert res is not None
    assert res.hour == 1
    assert res.minute == 40
    assert res.year == 2026
    assert res.month == 7
    assert res.day == 17
    assert str(res.tzinfo) == "Asia/Calcutta"


def test_parse_reset_time_basic_pm() -> None:
    # 1:40pm today
    ref = datetime(2026, 7, 17, 11, 0, 0, tzinfo=zoneinfo.ZoneInfo("Asia/Calcutta"))
    res = watchdog.parse_reset_time(
        "You've hit your session limit · resets 1:40pm (Asia/Calcutta)", ref_now=ref
    )
    assert res is not None
    assert res.hour == 13
    assert res.minute == 40
    assert res.day == 17


def test_parse_reset_time_cross_midnight() -> None:
    # Current time: 21:35 (9:35pm) on July 17
    # Reset: 1:40am -> must be July 18
    ref = datetime(2026, 7, 17, 21, 35, 0, tzinfo=zoneinfo.ZoneInfo("Asia/Calcutta"))
    res = watchdog.parse_reset_time(
        "You've hit your session limit · resets 1:40am (Asia/Calcutta)", ref_now=ref
    )
    assert res is not None
    assert res.hour == 1
    assert res.minute == 40
    assert res.year == 2026
    assert res.month == 7
    assert res.day == 18


def test_parse_reset_time_no_timezone_defaults_to_local() -> None:
    ref = datetime(2026, 7, 17, 10, 0, 0)
    res = watchdog.parse_reset_time(
        "You've hit your session limit · resets 11:30am", ref_now=ref
    )
    assert res is not None
    assert res.hour == 11
    assert res.minute == 30
    assert res.day == 17


def test_parse_reset_time_invalid_line() -> None:
    res = watchdog.parse_reset_time("Some other normal output from Claude")
    assert res is None


def test_make_continue_command() -> None:
    assert watchdog.make_continue_command(["claude"]) == ["claude", "--continue"]
    assert watchdog.make_continue_command(["npx", "claude"]) == ["npx", "claude", "--continue"]
    assert watchdog.make_continue_command(["claude", "--continue"]) == ["claude", "--continue"]


def test_run_and_stream_captures_limit_and_output(capsys: pytest.CaptureFixture) -> None:
    # Let's run python itself to print a message containing the limit
    cmd = [
        sys.executable,
        "-c",
        "print(\"You've hit your session limit · resets 1:40am (Asia/Calcutta)\")",
    ]
    exit_code, limit_line = watchdog.run_and_stream(cmd)
    
    assert exit_code == 0
    assert limit_line is not None
    assert "You've hit your session limit" in limit_line
    assert "resets 1:40am" in limit_line
    
    captured = capsys.readouterr()
    assert "You've hit your session limit" in captured.out


def test_run_and_stream_command_not_found() -> None:
    exit_code, limit_line = watchdog.run_and_stream(["non_existent_executable_12345"])
    assert exit_code == 127
    assert limit_line is None


def test_main_loop_flow() -> None:
    # Reset watchdog test sleep accumulator
    watchdog._TEST_SLEEP_ACCUMULATOR = []

    # Mock the run_and_stream process call to simulate hitting a limit,
    # then retrying once (still limited), and then succeeding (resumed).
    #
    # Sequence of calls to run_and_stream:
    # 1. First run of "claude": hits limit -> returns (1, "You've hit your session limit · resets 1:40am (Asia/Calcutta)")
    # 2. Retry "claude --continue": still limited -> returns (1, "You've hit your session limit · resets 1:40am (Asia/Calcutta)")
    # 3. Next retry "claude --continue": success! -> returns (0, None)
    
    mock_run = mock.Mock()
    mock_run.side_effect = [
        (1, "You've hit your session limit · resets 1:40am (Asia/Calcutta)"),
        (1, "You've hit your session limit · resets 1:40am (Asia/Calcutta)"),
        (0, None),
    ]

    # Mock parse_reset_time to return a fixed datetime exactly 5 minutes in the future from "now"
    now_tz = datetime.now(zoneinfo.ZoneInfo("Asia/Calcutta"))
    future_reset = now_tz + timedelta(minutes=5)
    
    mock_parse = mock.Mock()
    mock_parse.return_value = future_reset

    with mock.patch("engineering_tools.watchdog.watchdog.run_and_stream", mock_run), \
         mock.patch("engineering_tools.watchdog.watchdog.parse_reset_time", mock_parse), \
         mock.patch("engineering_tools.watchdog.watchdog.log_msg") as mock_log:
         
        exit_code = watchdog.main_loop(["claude"])
        
        assert exit_code == 0
        
        # Verify the logs are printed in the correct order
        # First log: Claude started
        mock_log.assert_any_call("Claude started")
        # Second log: Session limit detected
        mock_log.assert_any_call("Session limit detected")
        # Third log: Reset time
        reset_str = future_reset.astimezone(datetime.now().astimezone().tzinfo).strftime("%H:%M")
        mock_log.assert_any_call(f"Reset: {reset_str}")
        # Fourth log: Retrying...
        mock_log.assert_any_call("Retrying...")
        
        # Verify sleep amounts
        # First sleep (until 1 minute before reset): 5 minutes minus 1 minute = 4 minutes = 240 seconds
        # Second sleep (during retry failure loop): 30 seconds
        assert len(watchdog._TEST_SLEEP_ACCUMULATOR) == 2
        
        # Let's assert we slept approximately 240 seconds (give or take a few seconds of tolerance in calculation)
        assert 235 <= watchdog._TEST_SLEEP_ACCUMULATOR[0] <= 245
        assert watchdog._TEST_SLEEP_ACCUMULATOR[1] == 30

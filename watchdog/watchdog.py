"""Zenith Watchdog - Auto-resumes Claude Code after session limit.

This is a simple, lightweight utility to run Claude Code, monitor its output,
detect session limits, parse the reset time, wait, and automatically resume
using 'claude --continue'.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
import subprocess
import threading
from datetime import datetime, timedelta
import zoneinfo

# Global configuration / flags for testing
_TEST_SLEEP_ACCUMULATOR: list[float] = []
_MOCK_TIME_NOW: datetime | None = None


def log_msg(msg: str) -> None:
    """Print message with local timestamp [HH:MM]."""
    time_str = datetime.now().strftime("%H:%M")
    print(f"[{time_str}] {msg}", flush=True)


def parse_reset_time(line: str, ref_now: datetime | None = None) -> datetime | None:
    """
    Parse reset time and timezone from a line of output.
    Example: "You've hit your session limit · resets 1:40am (Asia/Calcutta)"
    
    Returns a timezone-aware datetime representing the reset time, or None.
    """
    # Pattern to match resets <time> (<timezone>) or resets <time>
    pattern = r"resets\s+(\d{1,2}):(\d{2})\s*(am|pm)?(?:\s+\(([^)]+)\))?"
    match = re.search(pattern, line, re.IGNORECASE)
    if not match:
        return None

    hour_str, min_str, am_pm, tz_str = match.groups()
    hour = int(hour_str)
    minute = int(min_str)

    if am_pm:
        am_pm = am_pm.lower()
        if am_pm == "pm" and hour < 12:
            hour += 12
        elif am_pm == "am" and hour == 12:
            hour = 0

    # Determine timezone
    if tz_str:
        try:
            tz = zoneinfo.ZoneInfo(tz_str)
        except Exception:
            # Fallback to local system timezone
            tz = datetime.now().astimezone().tzinfo
    else:
        tz = datetime.now().astimezone().tzinfo

    # Determine reference current time
    if ref_now is not None:
        # If ref_now is naive, localize it to the target tz
        if ref_now.tzinfo is None:
            now_tz = ref_now.replace(tzinfo=tz)
        else:
            now_tz = ref_now.astimezone(tz)
    else:
        now_tz = datetime.now(tz)

    # Construct target datetime for today in that timezone
    target_dt = now_tz.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # If the target is in the past compared to reference now, it must be tomorrow
    if target_dt <= now_tz:
        target_dt += timedelta(days=1)

    return target_dt


def _sleep(seconds: float) -> None:
    """Actual sleep implementation with periodic checking for interruption."""
    start = time.time()
    while time.time() - start < seconds:
        # sleep in small increments to remain highly responsive to Ctrl+C
        time.sleep(min(0.2, seconds - (time.time() - start)))


def interruptible_sleep(seconds: float) -> None:
    """Sleep that registers in testing or executes real sleep."""
    if _TEST_SLEEP_ACCUMULATOR is not None and isinstance(_TEST_SLEEP_ACCUMULATOR, list):
        _TEST_SLEEP_ACCUMULATOR.append(seconds)
        # Skip actual sleeping in tests
        return
    _sleep(seconds)


def forward_input(process: subprocess.Popen) -> None:
    """Forward standard input of the watchdog to the subprocess."""
    try:
        while process.poll() is None:
            line = sys.stdin.readline()
            if not line:
                break
            if process.poll() is not None:
                break
            try:
                process.stdin.write(line)
                process.stdin.flush()
            except (IOError, ValueError):
                break
    except Exception:
        pass


def run_and_stream(cmd_args: list[str], is_retry: bool = False) -> tuple[int, str | None]:
    """
    Run a command, stream stdout/stderr to terminal in real time, and check
    for the session limit warning.
    
    Returns (exit_code, limit_line_if_found).
    """
    # Locate executable if not absolute
    # This ensures subprocess works reliably on Windows
    executable = cmd_args[0]
    
    try:
        process = subprocess.Popen(
            cmd_args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="ignore"
        )
    except FileNotFoundError:
        print(f"Error: Command '{executable}' not found. Please verify your installation and PATH.", file=sys.stderr)
        return 127, None

    # Thread to pass user input down to the child process
    input_thread = threading.Thread(target=forward_input, args=(process,), daemon=True)
    input_thread.start()

    output_buffer = ""
    session_limit_line = None
    resumed_logged = False
    start_time = time.time()

    try:
        while True:
            # If in retry/resume mode, check if we've successfully stayed alive for 3 seconds
            # without encountering any session limit line. If so, declare resumption!
            if is_retry and not resumed_logged:
                if time.time() - start_time > 3.0 and process.poll() is None and not session_limit_line:
                    log_msg("Claude resumed")
                    resumed_logged = True

            char = process.stdout.read(1)
            if not char:
                break

            # Print to standard output in real-time
            sys.stdout.write(char)
            sys.stdout.flush()
            output_buffer += char

            # Process completed lines to look for the session limit warning
            if "\n" in output_buffer:
                lines = output_buffer.split("\n")
                output_buffer = lines[-1]  # Keep trailing partial line
                for completed_line in lines[:-1]:
                    if "You've hit your session limit" in completed_line:
                        session_limit_line = completed_line
            else:
                if "You've hit your session limit" in output_buffer:
                    session_limit_line = output_buffer

            # Also log resumption if we see output progress and are clearly past any immediate startup limit exit
            if is_retry and not resumed_logged and not session_limit_line:
                if len(output_buffer) > 100 or "\n" in output_buffer:
                    log_msg("Claude resumed")
                    resumed_logged = True
                    
    except Exception as e:
        # Silently absorb reading errors (e.g. process terminated suddenly)
        pass
    finally:
        try:
            process.stdout.close()
        except Exception:
            pass
        exit_code = process.wait()

    # Fallback to log resumption if process successfully terminated without session limit
    if is_retry and not resumed_logged and not session_limit_line:
        log_msg("Claude resumed")

    return exit_code, session_limit_line


def make_continue_command(cmd_args: list[str]) -> list[str]:
    """Append --continue to the command arguments if not present."""
    if "--continue" in cmd_args:
        return cmd_args
    return cmd_args + ["--continue"]


def main_loop(cmd_args: list[str]) -> int:
    """
    Main controller loop for running Claude Code and handling session limits.
    """
    continue_mode = False

    while True:
        if not continue_mode:
            log_msg("Claude started")
            current_cmd = cmd_args
        else:
            log_msg("Claude resumed")
            current_cmd = make_continue_command(cmd_args)

        exit_code, limit_line = run_and_stream(current_cmd)

        if not limit_line:
            # Process terminated normally (no session limit detected)
            return exit_code

        # Limit detected!
        log_msg("Session limit detected")
        reset_dt = parse_reset_time(limit_line)
        if not reset_dt:
            log_msg("Reset: Unknown")
            wait_seconds = 3600  # Default to 1 hour
        else:
            local_tz = datetime.now().astimezone().tzinfo
            local_reset_dt = reset_dt.astimezone(local_tz)
            reset_str = local_reset_dt.strftime("%H:%M")
            log_msg(f"Reset: {reset_str}")

            now_tz = datetime.now(reset_dt.tzinfo)
            # Sleep until 1 minute before reset
            wait_seconds = (reset_dt - now_tz).total_seconds() - 60

        if wait_seconds > 0:
            interruptible_sleep(wait_seconds)

        # Retry loop phase
        while True:
            log_msg("Retrying...")
            retry_cmd = make_continue_command(cmd_args)
            exit_code, limit_line = run_and_stream(retry_cmd, is_retry=True)

            if limit_line:
                # Still limited! Wait 30 seconds and try again
                interruptible_sleep(30)
            else:
                # Successfully resumed and executed!
                # If it eventually exited normally, we are done
                continue_mode = True
                break

        # If the resumed process eventually finished normally, exit the watchdog
        if not limit_line:
            break

    return 0


def main() -> None:
    """Entry point for the Zenith Watchdog CLI."""
    parser = argparse.ArgumentParser(
        description="Zenith Watchdog - Automatically resume Claude Code sessions."
    )
    parser.add_argument(
        "command",
        nargs="*",
        default=["claude"],
        help="The command to run. Defaults to 'claude'."
    )
    args = parser.parse_args()

    try:
        sys.exit(main_loop(args.command))
    except KeyboardInterrupt:
        print("\n[Watchdog] Interrupted by user. Exiting...", flush=True)
        sys.exit(130)


if __name__ == "__main__":
    main()

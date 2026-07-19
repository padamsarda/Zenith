# Zenith Watchdog

Zenith Watchdog is a simple, lightweight utility designed to automatically resume **Claude Code** after hitting a session limit.

It runs Claude Code inside a subprocess, captures output in real time, parses the reset time when a session limit is hit, sleeps until one minute before the reset, and then retries starting Claude Code using `claude --continue` every 30 seconds until the session resumes successfully.

## Folder Structure

```
Zenith/
└── watchdog/
    ├── README.md         # This documentation
    ├── __init__.py       # Package marker
    └── watchdog.py       # Main watchdog script
```

## How It Works

1. **Launches Claude Code:** Runs `claude` (or a custom command) using Python's `subprocess.Popen`.
2. **Streams Output:** Captures stdout in real-time, forwarding input/output transparently so you don't lose the interactive look and feel.
3. **Detects Limits:** Listens for the text: `"You've hit your session limit"`.
4. **Extracts Reset Time:** When a limit is detected, it parses the reset time and timezone from the message (e.g., `resets 1:40am (Asia/Calcutta)`), converting it to local time.
5. **Sleeps Smartly:** Sleeps until exactly one minute before the reset time. It sleeps in small, interruptible intervals to ensure that pressing `Ctrl+C` terminates the watchdog instantly.
6. **Auto-Resumes:** Retries launching `claude --continue` every 30 seconds until Claude successfully resumes.
7. **Maintains Logs:** Prints clear, formatted timestamped logs showing the exact state of the watchdog.

### Log Output Example

```
[21:12] Claude started
[21:35] Session limit detected
[21:35] Reset: 01:40
[01:39] Retrying...
[01:39] Retrying...
[01:40] Claude resumed
```

## Requirements

- Python 3.11+
- Installed Claude Code CLI (`claude` must be in your `PATH` or configured)

## Instructions to Run

To start the watchdog with the default `claude` command, run:

```bash
python watchdog/watchdog.py
```

### Running with a Custom Command

If your Claude Code CLI has a different name, or you need to run it via `npx`, or you want to run a mock script for testing, you can pass the custom command directly as arguments:

```bash
# Example with npx
python watchdog/watchdog.py npx @anthropic-ai/claude

# Example with a mock python command
python watchdog/watchdog.py python tests/mock_claude.py
```

## Developer Notes

### Automated Test Suite

A comprehensive test suite is included in `tests/test_watchdog.py` to verify:
- Timezone-aware reset time parsing and crossing midnight.
- Successful subprocess launching and output streaming.
- State-machine transitions and retry logic with simulated processes.

To run the tests:

```bash
python -m pytest tests/test_watchdog.py
```

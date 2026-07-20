"""Interpreting a finished Claude Code subprocess's captured output.

Split out from `claude_code.py` so turning raw subprocess output into a
`ProviderSessionStatus` is a separate responsibility from the `Provider`
contract and subprocess lifecycle themselves.
"""

from __future__ import annotations

import json
from typing import Any

from engineering_manager.providers.base import ProviderSessionState, ProviderSessionStatus
from engineering_tools.watchdog.watchdog import SESSION_LIMIT_MARKER, parse_reset_time


def interpret_exit(output: str, exit_code: int) -> ProviderSessionStatus:
    """Turn a finished subprocess's captured output and exit code into a status."""
    if exit_code == 0:
        return _parse_success(output)
    return _parse_failure(output, exit_code)


def _parse_success(output: str) -> ProviderSessionStatus:
    """Interpret a zero exit code as FINISHED or FAILED.

    `claude --output-format json` reports application-level failures (a
    bad prompt, a tool error the model could not recover from) as
    `is_error: true` inside an otherwise successful process exit —
    distinct from the process crashing outright.
    """
    payload = _parse_json_result(output)
    if payload is None:
        return ProviderSessionStatus(
            state=ProviderSessionState.FINISHED, detail=output.strip() or None
        )
    usage = _usage_from(payload)
    if payload.get("is_error"):
        return ProviderSessionStatus(
            state=ProviderSessionState.FAILED,
            detail=str(payload.get("result") or "Claude Code reported an error."),
            usage=usage,
        )
    return ProviderSessionStatus(
        state=ProviderSessionState.FINISHED,
        detail=str(payload.get("result", output.strip())),
        usage=usage,
    )


def _parse_failure(output: str, exit_code: int) -> ProviderSessionStatus:
    """Interpret a nonzero exit code as LIMIT_REACHED or FAILED."""
    limit_line = _find_limit_line(output)
    if limit_line is not None:
        return ProviderSessionStatus(
            state=ProviderSessionState.LIMIT_REACHED,
            detail=limit_line,
            resume_at=parse_reset_time(limit_line),
        )
    stripped = output.strip()
    detail = stripped.splitlines()[-1] if stripped else f"exit code {exit_code}"
    return ProviderSessionStatus(state=ProviderSessionState.FAILED, detail=detail)


def _usage_from(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Collect token/cost accounting out of a `--output-format json` payload."""
    usage = dict(payload.get("usage") or {})
    if "total_cost_usd" in payload:
        usage["total_cost_usd"] = payload["total_cost_usd"]
    if "num_turns" in payload:
        usage["num_turns"] = payload["num_turns"]
    return usage or None


def _find_limit_line(output: str) -> str | None:
    """Return the first line reporting a session limit, if any."""
    for line in output.splitlines():
        if SESSION_LIMIT_MARKER in line:
            return line
    return None


def _parse_json_result(output: str) -> dict[str, Any] | None:
    """Parse `--output-format json`'s result object from `output`.

    Tried against the whole trimmed output first; falls back to just its
    last line, since print mode may emit incidental status text before
    the final JSON result.
    """
    text = output.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(text.splitlines()[-1])
    except json.JSONDecodeError:
        return None

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

# How many blocked tool names to name in a denial detail before eliding
# the rest — enough to diagnose, short enough to read in a report line.
MAX_REPORTED_DENIALS = 5


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

    A session whose tool calls were *denied* is the third case, and the
    most dangerous, because nothing else in the payload marks it: the
    process exits 0, `is_error` is false, and the final message is a
    fluent explanation of what the model would have done. Trusting that
    as FINISHED records a task as complete when the repository was never
    touched — and it survives the verification gate too, since a suite
    that passed before a no-op still passes after it (ADR 0022).
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
    denied = _denied_tools(payload)
    if denied:
        return ProviderSessionStatus(
            state=ProviderSessionState.FAILED, detail=_denial_detail(denied), usage=usage
        )
    return ProviderSessionStatus(
        state=ProviderSessionState.FINISHED,
        detail=str(payload.get("result", output.strip())),
        usage=usage,
    )


def _denied_tools(payload: dict[str, Any]) -> list[str]:
    """Names of the tools Claude Code was refused permission to use."""
    denials = payload.get("permission_denials")
    if not isinstance(denials, list):
        return []
    return [
        str(denial.get("tool_name", "unknown"))
        for denial in denials
        if isinstance(denial, dict)
    ]


def _denial_detail(denied: list[str]) -> str:
    """Explain a permission-blocked session, and how to unblock it.

    The detail becomes the session's failure reason, so it is what a
    human reads in the engineering report and what `ContextAssembler`
    feeds to the next attempt. Both are better served by naming the
    remedy than by restating the symptom.
    """
    shown = denied[:MAX_REPORTED_DENIALS]
    listed = ", ".join(shown)
    if len(denied) > len(shown):
        listed += f", and {len(denied) - len(shown)} more"
    return (
        f"Claude Code was denied permission to use: {listed}. "
        "The session could not change the repository, so its completion "
        "claim is not trustworthy. Grant the session authority to act "
        "with --permission-mode (e.g. acceptEdits)."
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

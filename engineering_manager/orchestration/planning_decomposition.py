"""Parsing a provider's planning output into task drafts.

Split from `planning.py` (which talks to a provider) because this half
fails differently: not network or subprocess trouble, but malformed or
adversarial text. Kept as pure functions over strings — no store access,
no provider — so it is trivial to test against arbitrary model output
without running a session at all.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from engineering_manager.exceptions import OrchestrationError

MAX_RAW_OUTPUT_IN_ERROR = 500

PLANNING_PROMPT_TEMPLATE = """\
You are decomposing an engineering goal into a task graph for an \
autonomous engineering platform. Nothing you write here executes \
anything; a human reviews the decomposition before any task runs.

Goal: {goal}
{description_line}
Respond with ONLY a JSON array (no prose, no markdown code fences) of \
task objects, each with:
  "title": a short imperative task title (required)
  "description": one or two sentences of detail (optional)
  "priority": an integer, higher runs first (optional, default 0)
  "depends_on": a list of 0-based indices into this same array, naming \
tasks that must finish first (optional, default [])

Keep the decomposition to the smallest number of tasks that meaningfully \
divides the work, and order the array so a task's dependencies appear \
naturally alongside it.
"""


@dataclass(frozen=True)
class TaskDraft:
    """One task as decomposed from a goal, not yet written to the store.

    `depends_on` holds 0-based indices into the same decomposition list
    this draft came from — resolved to real task IDs by the caller once
    every draft has been created (a task cannot depend on an ID that
    doesn't exist yet, ADR 0006).
    """

    title: str
    description: str | None = None
    priority: int = 0
    depends_on: tuple[int, ...] = field(default_factory=tuple)


def build_planning_instructions(goal: str, description: str | None = None) -> str:
    """Compose the instructions handed to the provider for a planning session."""
    description_line = f"Context: {description}\n" if description else ""
    return PLANNING_PROMPT_TEMPLATE.format(goal=goal, description_line=description_line)


def parse_decomposition(raw_text: str) -> list[TaskDraft]:
    """Parse a provider's planning output into task drafts.

    Tolerant of markdown code fences around the JSON and of prose before
    or after the array (common LLM habits); a malformed item is skipped
    rather than failing the whole decomposition, since the plan stays
    DRAFT for a human to fix up regardless.

    Raises:
        OrchestrationError: If no JSON array can be found, or it does
            not parse as JSON.
    """
    payload = _extract_json_array(raw_text)
    if payload is None:
        raise OrchestrationError(
            "Could not find a JSON task array in the planning output: "
            f"{raw_text[:MAX_RAW_OUTPUT_IN_ERROR]!r}"
        )
    try:
        items = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise OrchestrationError(f"Planning output was not valid JSON: {exc}") from exc
    if not isinstance(items, list):
        raise OrchestrationError("Planning output JSON must be an array of task objects.")

    drafts: list[TaskDraft] = []
    for item in items:
        draft = _parse_item(item)
        if draft is not None:
            drafts.append(draft)
    return drafts


def _parse_item(item: object) -> TaskDraft | None:
    """Parse one decomposition item, or None if it is unusable."""
    if not isinstance(item, dict):
        return None
    title = item.get("title")
    if not isinstance(title, str) or not title.strip():
        return None
    description = item.get("description")
    if not isinstance(description, str) or not description.strip():
        description = None
    priority = item.get("priority", 0)
    if not isinstance(priority, int) or isinstance(priority, bool):
        priority = 0
    raw_depends_on = item.get("depends_on", [])
    depends_on = (
        tuple(
            index
            for index in raw_depends_on
            if isinstance(index, int) and not isinstance(index, bool)
        )
        if isinstance(raw_depends_on, list)
        else ()
    )
    return TaskDraft(
        title=title.strip(), description=description, priority=priority, depends_on=depends_on
    )


def _extract_json_array(raw_text: str) -> str | None:
    """Pull the first plausible JSON array out of `raw_text`."""
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        return None
    return text[start : end + 1]

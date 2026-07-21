"""Tests for planning_decomposition: parsing a provider's planning output."""

from __future__ import annotations

import pytest

from engineering_manager.exceptions import OrchestrationError
from engineering_manager.orchestration.planning_decomposition import (
    TaskDraft,
    build_planning_instructions,
    parse_decomposition,
)


def test_build_planning_instructions_includes_goal() -> None:
    instructions = build_planning_instructions("Ship plugin support")

    assert "Ship plugin support" in instructions
    assert "JSON array" in instructions


def test_build_planning_instructions_includes_description_when_given() -> None:
    instructions = build_planning_instructions("Ship it", description="Read docs/plugins.md first.")

    assert "Read docs/plugins.md first." in instructions


def test_parse_decomposition_plain_json_array() -> None:
    raw = '[{"title": "Write the loader"}, {"title": "Write tests", "depends_on": [0]}]'

    drafts = parse_decomposition(raw)

    assert drafts == [
        TaskDraft(title="Write the loader"),
        TaskDraft(title="Write tests", depends_on=(0,)),
    ]


def test_parse_decomposition_strips_markdown_fence() -> None:
    raw = '```json\n[{"title": "Do it"}]\n```'

    drafts = parse_decomposition(raw)

    assert drafts == [TaskDraft(title="Do it")]


def test_parse_decomposition_ignores_surrounding_prose() -> None:
    raw = 'Sure, here is the plan:\n[{"title": "Do it"}]\nLet me know if you need more.'

    drafts = parse_decomposition(raw)

    assert drafts == [TaskDraft(title="Do it")]


def test_parse_decomposition_reads_all_fields() -> None:
    raw = '[{"title": "A", "description": "details", "priority": 5, "depends_on": [1, 2]}]'

    (draft,) = parse_decomposition(raw)

    assert draft == TaskDraft(title="A", description="details", priority=5, depends_on=(1, 2))


def test_parse_decomposition_skips_items_without_a_title() -> None:
    raw = '[{"description": "no title"}, {"title": "has one"}]'

    drafts = parse_decomposition(raw)

    assert drafts == [TaskDraft(title="has one")]


def test_parse_decomposition_skips_non_object_items() -> None:
    raw = '["just a string", {"title": "real task"}, 42]'

    drafts = parse_decomposition(raw)

    assert drafts == [TaskDraft(title="real task")]


def test_parse_decomposition_tolerates_malformed_optional_fields() -> None:
    raw = '[{"title": "A", "priority": "high", "depends_on": "not-a-list"}]'

    (draft,) = parse_decomposition(raw)

    assert draft == TaskDraft(title="A", priority=0, depends_on=())


def test_parse_decomposition_rejects_non_array_json() -> None:
    with pytest.raises(OrchestrationError):
        parse_decomposition('{"title": "not an array"}')


def test_parse_decomposition_rejects_invalid_json() -> None:
    with pytest.raises(OrchestrationError):
        parse_decomposition("not json at all")


def test_parse_decomposition_rejects_text_with_no_array() -> None:
    with pytest.raises(OrchestrationError):
        parse_decomposition("I refuse to produce a plan.")

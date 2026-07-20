"""Tests for consume_event_stream, the Claude SSE accumulator."""

from __future__ import annotations

from runtime.providers.claude_stream import consume_event_stream


def sse(event: str | None, data: dict) -> list[str]:
    """Build the SSE lines for one event, followed by a blank separator."""
    import json

    lines = []
    if event is not None:
        lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data)}")
    lines.append("")
    return lines


def test_accumulates_text_deltas_into_one_block() -> None:
    lines = [
        *sse("message_start", {"message": {"id": "msg_1", "model": "claude-sonnet-5", "usage": {"input_tokens": 5}}}),
        *sse("content_block_start", {"index": 0, "content_block": {"type": "text", "text": ""}}),
        *sse("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": "Hello, "}}),
        *sse("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": "world."}}),
        *sse("content_block_stop", {"index": 0}),
        *sse("message_delta", {"delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 7}}),
        *sse("message_stop", {}),
    ]

    result = consume_event_stream(lines)

    assert result["id"] == "msg_1"
    assert result["model"] == "claude-sonnet-5"
    assert result["content"] == [{"type": "text", "text": "Hello, world."}]
    assert result["stop_reason"] == "end_turn"
    assert result["usage"] == {"input_tokens": 5, "output_tokens": 7}


def test_accumulates_tool_use_input_json_deltas() -> None:
    lines = [
        *sse("message_start", {"message": {"id": "msg_2", "model": "claude-sonnet-5", "usage": {}}}),
        *sse(
            "content_block_start",
            {"index": 0, "content_block": {"type": "tool_use", "id": "toolu_1", "name": "clock", "input": {}}},
        ),
        *sse("content_block_delta", {"index": 0, "delta": {"type": "input_json_delta", "partial_json": '{"tz":'}}),
        *sse("content_block_delta", {"index": 0, "delta": {"type": "input_json_delta", "partial_json": ' "UTC"}'}}),
        *sse("content_block_stop", {"index": 0}),
        *sse("message_delta", {"delta": {"stop_reason": "tool_use"}, "usage": {}}),
    ]

    result = consume_event_stream(lines)

    assert result["content"] == [
        {"type": "tool_use", "id": "toolu_1", "name": "clock", "input": {"tz": "UTC"}}
    ]
    assert result["stop_reason"] == "tool_use"


def test_multiple_content_blocks_preserve_order() -> None:
    lines = [
        *sse("content_block_start", {"index": 0, "content_block": {"type": "text", "text": ""}}),
        *sse("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": "one"}}),
        *sse("content_block_start", {"index": 1, "content_block": {"type": "tool_use", "name": "clock", "id": "t1", "input": {}}}),
        *sse("message_delta", {"delta": {"stop_reason": "tool_use"}, "usage": {}}),
    ]

    result = consume_event_stream(lines)

    assert [block["type"] for block in result["content"]] == ["text", "tool_use"]
    assert result["content"][0]["text"] == "one"


def test_works_without_explicit_event_lines() -> None:
    lines = [
        'data: {"type": "message_start", "message": {"id": "msg_3", "model": "m", "usage": {}}}',
        "",
        'data: {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}',
        "",
        'data: {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "hi"}}',
        "",
        'data: {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {}}',
        "",
    ]

    result = consume_event_stream(lines)

    assert result["id"] == "msg_3"
    assert result["content"] == [{"type": "text", "text": "hi"}]


def test_stops_at_done_marker() -> None:
    lines = [
        *sse("content_block_start", {"index": 0, "content_block": {"type": "text", "text": ""}}),
        *sse("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": "hi"}}),
        "data: [DONE]",
        *sse("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": " should not appear"}}),
    ]

    result = consume_event_stream(lines)

    assert result["content"] == [{"type": "text", "text": "hi"}]


def test_malformed_data_line_is_skipped_not_raised() -> None:
    lines = [
        "event: content_block_delta",
        "data: not valid json",
        "",
        *sse("content_block_start", {"index": 0, "content_block": {"type": "text", "text": ""}}),
        *sse("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": "ok"}}),
    ]

    result = consume_event_stream(lines)

    assert result["content"] == [{"type": "text", "text": "ok"}]


def test_empty_stream_yields_empty_content() -> None:
    result = consume_event_stream([])

    assert result == {"id": None, "model": None, "content": [], "stop_reason": None, "usage": {}}

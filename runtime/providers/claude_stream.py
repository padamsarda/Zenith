"""SSE parsing for the Claude Messages API's streaming responses.

Folds a stream of Server-Sent Events into the same normalized response
shape a plain (non-streaming) request produces — `id`, `model`,
`content`, `stop_reason`, `usage` — so `ClaudeTransport.send` returns one
shape regardless of transport mode. Event types follow Anthropic's
streaming reference: `message_start`, `content_block_start`/`_delta`,
`message_delta`.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

DATA_PREFIX = "data:"
EVENT_PREFIX = "event:"
DONE_MARKER = "[DONE]"


@dataclass
class _BlockBuilder:
    """Accumulates one content block across `content_block_delta` events."""

    block: dict[str, Any]
    json_fragments: list[str] = field(default_factory=list)

    def apply_delta(self, delta: dict[str, Any]) -> None:
        """Fold one `content_block_delta`'s `delta` object into this block."""
        delta_type = delta.get("type")
        if delta_type == "text_delta":
            self.block["text"] = self.block.get("text", "") + delta.get("text", "")
        elif delta_type == "input_json_delta":
            self.json_fragments.append(delta.get("partial_json", ""))

    def finalize(self) -> dict[str, Any]:
        """Return the completed block, parsing any accumulated tool input."""
        if self.json_fragments:
            joined = "".join(self.json_fragments)
            self.block["input"] = json.loads(joined) if joined.strip() else {}
        return self.block


def consume_event_stream(lines: Iterable[str]) -> dict[str, Any]:
    """Fold an SSE event stream into a normalized Messages API response.

    `lines` yields decoded text lines; the caller decodes raw bytes into
    text first. Malformed `data:` payloads are skipped rather than
    raised, since a partial or corrupt line should not lose everything
    already accumulated.
    """
    message_id: str | None = None
    model: str | None = None
    stop_reason: str | None = None
    usage: dict[str, Any] = {}
    blocks: dict[int, _BlockBuilder] = {}
    order: list[int] = []

    event_name: str | None = None
    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        if not line:
            event_name = None
            continue
        if line.startswith(EVENT_PREFIX):
            event_name = line[len(EVENT_PREFIX):].strip()
            continue
        if not line.startswith(DATA_PREFIX):
            continue
        data = line[len(DATA_PREFIX):].strip()
        if data == DONE_MARKER:
            break
        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            continue

        kind = event_name or event.get("type")
        if kind == "message_start":
            message = event.get("message") or {}
            message_id = message.get("id")
            model = message.get("model")
            usage.update(message.get("usage") or {})
        elif kind == "content_block_start":
            index = event["index"]
            blocks[index] = _BlockBuilder(block=dict(event.get("content_block") or {}))
            order.append(index)
        elif kind == "content_block_delta":
            builder = blocks.get(event["index"])
            if builder is not None:
                builder.apply_delta(event.get("delta") or {})
        elif kind == "message_delta":
            delta = event.get("delta") or {}
            if "stop_reason" in delta:
                stop_reason = delta["stop_reason"]
            usage.update(event.get("usage") or {})

    content = [blocks[index].finalize() for index in order]
    return {
        "id": message_id,
        "model": model,
        "content": content,
        "stop_reason": stop_reason,
        "usage": usage,
    }

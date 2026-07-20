"""Message and tool-call translation between Zenith and the Claude API.

Converts `runtime.conversation.message.Message` history into Claude's
`messages` array (plus a `system` string), and `CapabilityCatalog` tool
descriptors into Claude's tool JSON schema. The trickiest part is
round-tripping tool calls: the Messages API is stateless per request and
requires every `tool_use` block to be answered by a `tool_result` block
sharing its ID within that same request, but the assistant pipeline only
records a call's *outcome* as a `TOOL` message (ADR 0012) — never the
call that produced it, since that is the provider's own business.
`ToolCallCache` closes that gap entirely inside the provider: it
remembers each `ToolCall` this provider issued, keyed by `call_id`, so a
later request in the same conversation can rebuild a faithful `tool_use`
block. No engine or conversation-model change is involved.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any
from uuid import UUID

from runtime.capabilities.catalog import CapabilityCatalog, CapabilityDescriptor
from runtime.conversation.message import Message, MessageRole
from runtime.providers.base import ToolCall

DEFAULT_MAX_CACHED_BATCHES = 512


class ToolCallCache:
    """Remembers tool calls this provider issued, grouped into batches.

    A "batch" is every `ToolCall` returned in one `AssistantTurn`: they
    must be replayed together as one assistant message's `tool_use`
    blocks and answered together by one user message's `tool_result`
    blocks, because Claude requires every `tool_use` in a turn to be
    resolved before the conversation can continue. Bounded to the most
    recent `max_batches`; eviction only degrades fidelity for very old
    calls (see `build_claude_messages`'s handling of an unknown
    `call_id`), it never breaks request validity.
    """

    def __init__(self, max_batches: int = DEFAULT_MAX_CACHED_BATCHES) -> None:
        self._max_batches = max_batches
        self._batches: OrderedDict[int, list[ToolCall]] = OrderedDict()
        self._batch_of: dict[UUID, int] = {}
        self._next_batch_id = 0

    def register(self, tool_calls: tuple[ToolCall, ...]) -> None:
        """Record a new batch of tool calls this provider just issued."""
        if not tool_calls:
            return
        batch_id = self._next_batch_id
        self._next_batch_id += 1
        self._batches[batch_id] = list(tool_calls)
        for call in tool_calls:
            self._batch_of[call.call_id] = batch_id
        while len(self._batches) > self._max_batches:
            oldest_id, oldest_calls = self._batches.popitem(last=False)
            for call in oldest_calls:
                self._batch_of.pop(call.call_id, None)

    def batch_of(self, call_id: UUID) -> int | None:
        """Return the batch ID `call_id` belongs to, or None if forgotten."""
        return self._batch_of.get(call_id)

    def calls_in(self, batch_id: int) -> list[ToolCall]:
        """Return every `ToolCall` recorded for `batch_id`, in issue order."""
        return list(self._batches.get(batch_id, ()))


def build_claude_messages(
    messages: tuple[Message, ...], cache: ToolCallCache
) -> tuple[str | None, list[dict[str, Any]]]:
    """Convert conversation history into `(system_text, claude_messages)`.

    `SYSTEM` messages are pulled out into the returned system text
    (Claude takes `system` as a top-level request field, not a message
    role). Adjacent same-role messages are merged into one Claude message
    — the API requires strict user/assistant alternation, and a `TOOL`
    batch's reconstructed `tool_use`/`tool_result` pair must appear as
    exactly one assistant message and one user message regardless of how
    many individual tool calls it contained.
    """
    system_parts: list[str] = []
    groups: list[tuple[str, list[dict[str, Any]]]] = []
    index = 0
    total = len(messages)
    while index < total:
        message = messages[index]
        if message.role is MessageRole.SYSTEM:
            system_parts.append(message.content)
            index += 1
        elif message.role is MessageRole.TOOL:
            index = _consume_tool_batch(messages, index, cache, groups)
        else:
            role = "user" if message.role is MessageRole.USER else "assistant"
            groups.append((role, [{"type": "text", "text": message.content}]))
            index += 1

    claude_messages: list[dict[str, Any]] = []
    for role, blocks in groups:
        if claude_messages and claude_messages[-1]["role"] == role:
            claude_messages[-1]["content"].extend(blocks)
        else:
            claude_messages.append({"role": role, "content": blocks})
    system = "\n\n".join(system_parts) if system_parts else None
    return system, claude_messages


def build_tools_payload(catalog: CapabilityCatalog) -> list[dict[str, Any]] | None:
    """Convert the catalog's tool descriptors into Claude's tool-schema JSON.

    Returns None (omitting `tools` from the request entirely) when
    nothing is registered.
    """
    if not catalog.tools:
        return None
    return [_tool_schema(descriptor) for descriptor in catalog.tools]


def parse_turn(
    response: dict[str, Any], cache: ToolCallCache
) -> tuple[str | None, tuple[ToolCall, ...]]:
    """Convert a normalized Claude response into `(text, tool_calls)`.

    Every returned tool call is a fresh `ToolCall` (a new random
    `call_id` — Claude's own string ID is discarded and never needed
    again: each request is self-contained, so only *this* request's
    `tool_use`/`tool_result` IDs must agree with each other, not with
    anything Claude issued in an earlier, separate call). The batch is
    registered with `cache` so a later request can rebuild it.
    """
    texts: list[str] = []
    tool_calls: list[ToolCall] = []
    for block in response.get("content") or []:
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text", "")
            if text:
                texts.append(text)
        elif block_type == "tool_use":
            tool_calls.append(
                ToolCall(tool_id=block.get("name", ""), arguments=block.get("input") or {})
            )
    result_calls = tuple(tool_calls)
    cache.register(result_calls)
    return ("\n".join(texts) if texts else None), result_calls


def _consume_tool_batch(
    messages: tuple[Message, ...],
    start: int,
    cache: ToolCallCache,
    groups: list[tuple[str, list[dict[str, Any]]]],
) -> int:
    """Group the contiguous run of TOOL messages starting at `start`.

    Appends the reconstructed assistant `tool_use` message and user
    `tool_result` message to `groups`, and returns the index just past
    the consumed run.
    """
    key = _group_key(messages[start], cache)
    index = start
    batch_messages: list[Message] = []
    while (
        index < len(messages)
        and messages[index].role is MessageRole.TOOL
        and _group_key(messages[index], cache) == key
    ):
        batch_messages.append(messages[index])
        index += 1

    groups.append(("assistant", _tool_use_blocks(key, batch_messages, cache)))
    groups.append(("user", [_tool_result_block(message) for message in batch_messages]))
    return index


def _group_key(message: Message, cache: ToolCallCache) -> tuple[str, object]:
    """The identity a TOOL message groups by: its known batch, or itself."""
    call_id = _call_id_of(message)
    if call_id is not None:
        batch_id = cache.batch_of(call_id)
        if batch_id is not None:
            return ("known", batch_id)
    return ("unknown", message.message_id)


def _tool_use_blocks(
    key: tuple[str, object], batch_messages: list[Message], cache: ToolCallCache
) -> list[dict[str, Any]]:
    """Rebuild the assistant `tool_use` blocks for one grouped batch.

    A "known" batch (this provider issued it and still remembers it)
    replays the original tool name and arguments faithfully. An
    "unknown" one — a different provider's call, or one this cache has
    since evicted — degrades gracefully to a synthetic single-call block
    with no remembered arguments: still valid Claude API shape, just
    without the original input.
    """
    kind, batch_id = key
    if kind == "known":
        return [
            {"type": "tool_use", "id": str(call.call_id), "name": call.tool_id, "input": call.arguments}
            for call in cache.calls_in(batch_id)
        ]
    message = batch_messages[0]
    return [
        {
            "type": "tool_use",
            "id": message.metadata.get("call_id", str(message.message_id)),
            "name": message.metadata.get("tool_id", "unknown_tool"),
            "input": {},
        }
    ]


def _tool_result_block(message: Message) -> dict[str, Any]:
    """Build the `tool_result` block reporting one TOOL message's outcome."""
    call_id = message.metadata.get("call_id", str(message.message_id))
    return {"type": "tool_result", "tool_use_id": call_id, "content": message.content}


def _call_id_of(message: Message) -> UUID | None:
    """Parse a TOOL message's `call_id` metadata, if present and valid."""
    raw = message.metadata.get("call_id")
    if raw is None:
        return None
    try:
        return UUID(str(raw))
    except ValueError:
        return None


def _tool_schema(descriptor: CapabilityDescriptor) -> dict[str, Any]:
    """Convert one tool `CapabilityDescriptor` into Claude's tool JSON schema."""
    properties = {
        parameter.name: {
            "type": parameter.type,
            **({"description": parameter.description} if parameter.description else {}),
        }
        for parameter in descriptor.parameters
    }
    required = [parameter.name for parameter in descriptor.parameters if parameter.required]
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return {"name": descriptor.capability_id, "description": descriptor.description, "input_schema": schema}

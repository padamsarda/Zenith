"""Tests for Claude message/tool-call translation."""

from __future__ import annotations

from runtime.capabilities.catalog import CapabilityCatalog, CapabilityDescriptor, CapabilityKind
from runtime.capabilities.tool import ToolParameter
from runtime.conversation.message import Message, MessageRole
from runtime.providers.base import ToolCall
from runtime.providers.claude_messages import (
    ToolCallCache,
    build_claude_messages,
    build_tools_payload,
    parse_turn,
)


def user(text: str) -> Message:
    return Message(role=MessageRole.USER, content=text)


def assistant(text: str) -> Message:
    return Message(role=MessageRole.ASSISTANT, content=text)


def system(text: str) -> Message:
    return Message(role=MessageRole.SYSTEM, content=text)


def tool_result(call: ToolCall, content: str) -> Message:
    return Message(
        role=MessageRole.TOOL,
        content=content,
        metadata={"tool_id": call.tool_id, "call_id": str(call.call_id)},
    )


# -- build_claude_messages --------------------------------------------------


def test_user_and_assistant_messages_become_text_blocks() -> None:
    system_text, messages = build_claude_messages((user("hi"), assistant("hello")), ToolCallCache())

    assert system_text is None
    assert messages == [
        {"role": "user", "content": [{"type": "text", "text": "hi"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "hello"}]},
    ]


def test_system_messages_are_pulled_into_system_text() -> None:
    system_text, messages = build_claude_messages(
        (system("Be concise."), user("hi")), ToolCallCache()
    )

    assert system_text == "Be concise."
    assert messages == [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]


def test_multiple_system_messages_are_joined() -> None:
    system_text, _ = build_claude_messages((system("One."), system("Two.")), ToolCallCache())

    assert system_text == "One.\n\nTwo."


def test_known_tool_batch_reconstructs_tool_use_and_tool_result() -> None:
    cache = ToolCallCache()
    call = ToolCall(tool_id="clock", arguments={"tz": "UTC"})
    cache.register((call,))
    history = (user("what time is it"), tool_result(call, "12:00"))

    _, messages = build_claude_messages(history, cache)

    assert messages == [
        {"role": "user", "content": [{"type": "text", "text": "what time is it"}]},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": str(call.call_id), "name": "clock", "input": {"tz": "UTC"}}
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": str(call.call_id), "content": "12:00"}
        ]},
    ]


def test_multi_call_batch_groups_into_one_assistant_and_one_user_message() -> None:
    cache = ToolCallCache()
    first = ToolCall(tool_id="clock", arguments={})
    second = ToolCall(tool_id="weather", arguments={"city": "NYC"})
    cache.register((first, second))
    history = (
        user("what's up"),
        tool_result(first, "12:00"),
        tool_result(second, "sunny"),
    )

    _, messages = build_claude_messages(history, cache)

    assert len(messages) == 3
    assistant_message = messages[1]
    assert assistant_message["role"] == "assistant"
    assert [block["id"] for block in assistant_message["content"]] == [
        str(first.call_id), str(second.call_id)
    ]
    tool_result_message = messages[2]
    assert [block["tool_use_id"] for block in tool_result_message["content"]] == [
        str(first.call_id), str(second.call_id)
    ]


def test_unknown_tool_call_id_degrades_to_synthetic_single_call_batch() -> None:
    orphan = Message(
        role=MessageRole.TOOL, content="done",
        metadata={"tool_id": "mystery", "call_id": "11111111-1111-1111-1111-111111111111"},
    )

    _, messages = build_claude_messages((orphan,), ToolCallCache())

    assistant_message, user_message = messages
    assert assistant_message["content"][0]["name"] == "mystery"
    assert assistant_message["content"][0]["input"] == {}
    assert assistant_message["content"][0]["id"] == user_message["content"][0]["tool_use_id"]


def test_two_consecutive_batches_with_no_intervening_text_stay_separate() -> None:
    cache = ToolCallCache()
    first_batch = ToolCall(tool_id="a")
    second_batch = ToolCall(tool_id="b")
    cache.register((first_batch,))
    cache.register((second_batch,))
    history = (tool_result(first_batch, "done a"), tool_result(second_batch, "done b"))

    _, messages = build_claude_messages(history, cache)

    # Two distinct batches means two assistant/user pairs, each carrying
    # exactly its own call -- they must not be merged into one giant
    # tool_use block despite having no user/assistant text between them.
    assert len(messages) == 4
    assert messages[0]["content"][0]["id"] == str(first_batch.call_id)
    assert messages[2]["content"][0]["id"] == str(second_batch.call_id)


def test_adjacent_same_role_text_messages_merge() -> None:
    cache = ToolCallCache()
    call = ToolCall(tool_id="clock")
    cache.register((call,))
    history = (tool_result(call, "12:00"), user("thanks"))

    _, messages = build_claude_messages(history, cache)

    # The tool_result's user message and the fresh user text both have
    # role "user" and are adjacent, so they merge into one Claude message.
    assert len(messages) == 2
    assert messages[1]["role"] == "user"
    assert len(messages[1]["content"]) == 2


# -- build_tools_payload -----------------------------------------------------


def make_catalog(descriptors: tuple[CapabilityDescriptor, ...]) -> CapabilityCatalog:
    return CapabilityCatalog(tools=descriptors, skills=())


def test_empty_catalog_produces_no_tools_payload() -> None:
    assert build_tools_payload(make_catalog(())) is None


def test_tool_descriptor_converts_to_input_schema() -> None:
    descriptor = CapabilityDescriptor(
        kind=CapabilityKind.TOOL,
        capability_id="clock",
        name="Clock",
        description="Tells the time.",
        parameters=(
            ToolParameter(name="tz", description="IANA timezone", type="string"),
            ToolParameter(name="format24h", required=False, type="boolean"),
        ),
    )

    (schema,) = build_tools_payload(make_catalog((descriptor,)))

    assert schema["name"] == "clock"
    assert schema["description"] == "Tells the time."
    assert schema["input_schema"]["properties"]["tz"] == {"type": "string", "description": "IANA timezone"}
    assert schema["input_schema"]["properties"]["format24h"] == {"type": "boolean"}
    assert schema["input_schema"]["required"] == ["tz"]


def test_tool_with_no_required_parameters_omits_required_key() -> None:
    descriptor = CapabilityDescriptor(
        kind=CapabilityKind.TOOL, capability_id="clock", name="Clock", description="d.",
        parameters=(ToolParameter(name="tz", required=False),),
    )

    (schema,) = build_tools_payload(make_catalog((descriptor,)))

    assert "required" not in schema["input_schema"]


# -- parse_turn ---------------------------------------------------------------


def test_parse_turn_extracts_text() -> None:
    response = {"content": [{"type": "text", "text": "hello"}]}

    text, tool_calls = parse_turn(response, ToolCallCache())

    assert text == "hello"
    assert tool_calls == ()


def test_parse_turn_extracts_tool_calls_and_registers_them() -> None:
    response = {"content": [{"type": "tool_use", "name": "clock", "input": {"tz": "UTC"}}]}
    cache = ToolCallCache()

    text, tool_calls = parse_turn(response, cache)

    assert text is None
    assert len(tool_calls) == 1
    assert tool_calls[0].tool_id == "clock"
    assert tool_calls[0].arguments == {"tz": "UTC"}
    assert cache.batch_of(tool_calls[0].call_id) is not None


def test_parse_turn_handles_mixed_text_and_tool_calls() -> None:
    response = {
        "content": [
            {"type": "text", "text": "Let me check."},
            {"type": "tool_use", "name": "clock", "input": {}},
        ]
    }

    text, tool_calls = parse_turn(response, ToolCallCache())

    assert text == "Let me check."
    assert len(tool_calls) == 1


def test_parse_turn_empty_content_yields_no_text_and_no_calls() -> None:
    text, tool_calls = parse_turn({"content": []}, ToolCallCache())

    assert text is None
    assert tool_calls == ()


# -- ToolCallCache -------------------------------------------------------------


def test_cache_evicts_oldest_batch_beyond_the_limit() -> None:
    cache = ToolCallCache(max_batches=1)
    first = ToolCall(tool_id="a")
    second = ToolCall(tool_id="b")
    cache.register((first,))
    cache.register((second,))

    assert cache.batch_of(first.call_id) is None
    assert cache.batch_of(second.call_id) is not None


def test_cache_ignores_an_empty_batch() -> None:
    cache = ToolCallCache()

    cache.register(())

    assert cache.calls_in(0) == []

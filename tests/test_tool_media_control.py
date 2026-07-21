"""Tests for MediaControlTool."""

from __future__ import annotations

import logging
import sys
from uuid import uuid4

import pytest

from configs.config import Config
from runtime.commands.context import CommandContext
from runtime.context import ApplicationContext
from runtime.exceptions import ToolExecutionError
from runtime.tools.media_control import (
    ACTIONS,
    MediaControlResult,
    MediaControlTool,
    default_key_sender,
)


def make_context() -> CommandContext:
    app_context = ApplicationContext(config=Config(), logger=logging.getLogger("test.media_control"))
    return CommandContext(application_context=app_context, command_id=uuid4())


class RecordingKeySender:
    """A fake `KeySender` that records every virtual-key code sent."""

    def __init__(self) -> None:
        self.calls: list[int] = []

    def __call__(self, vk_code: int) -> None:
        self.calls.append(vk_code)


# --- identity ----------------------------------------------------------------


def test_tool_identity() -> None:
    tool = MediaControlTool(key_sender=RecordingKeySender())

    assert tool.tool_id == "media_control"
    assert tool.name == "Media Control"
    assert {parameter.name for parameter in tool.parameters} == {"action", "steps"}


# --- actions ----------------------------------------------------------------


@pytest.mark.parametrize("action", ACTIONS)
def test_every_action_sends_exactly_one_key_press_by_default(action: str) -> None:
    key_sender = RecordingKeySender()
    tool = MediaControlTool(key_sender=key_sender)

    result = tool.invoke(make_context(), {"action": action})

    assert len(key_sender.calls) == 1
    assert result == MediaControlResult(action=action, steps=1, message=f"Sent {action} x1.")
    assert str(result) == f"Sent {action} x1."


def test_distinct_actions_send_distinct_key_codes() -> None:
    key_sender = RecordingKeySender()
    tool = MediaControlTool(key_sender=key_sender)

    for action in ACTIONS:
        tool.invoke(make_context(), {"action": action})

    assert len(set(key_sender.calls)) == len(ACTIONS)


def test_steps_repeats_the_key_press() -> None:
    key_sender = RecordingKeySender()
    tool = MediaControlTool(key_sender=key_sender)

    tool.invoke(make_context(), {"action": "volume_up", "steps": 5})

    assert len(key_sender.calls) == 5
    assert len(set(key_sender.calls)) == 1


# --- failures ----------------------------------------------------------------


def test_unknown_action_raises() -> None:
    tool = MediaControlTool(key_sender=RecordingKeySender())

    with pytest.raises(ToolExecutionError):
        tool.invoke(make_context(), {"action": "set_volume"})


@pytest.mark.parametrize("steps", [0, -1, 26])
def test_steps_out_of_range_raises(steps: int) -> None:
    key_sender = RecordingKeySender()
    tool = MediaControlTool(key_sender=key_sender)

    with pytest.raises(ToolExecutionError):
        tool.invoke(make_context(), {"action": "mute", "steps": steps})

    assert key_sender.calls == []


def test_default_key_sender_off_windows_fails_loudly() -> None:
    if sys.platform == "win32":
        pytest.skip("this platform can act; nothing to assert")

    with pytest.raises(ToolExecutionError, match="Windows"):
        default_key_sender(0xAF)

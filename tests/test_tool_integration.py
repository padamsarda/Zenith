"""Integration tests: built-in tools running through the real assistant pipeline.

Unlike the per-tool unit tests (which call `Tool.invoke` directly), these
exercise the whole path a provider's tool call actually takes:
`ToolRegistry` -> `AssistantEngine` -> `PermissionPolicy` ->
`ToolCallRunner` -> `CommandExecutor` -> `Tool.invoke` -> recorded back
into the conversation as a `TOOL` message. `ScriptedProvider` is the
injected fake standing in for "a provider," the same role it plays in
`tests/test_assistant_engine.py`.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from configs.config import Config
from runtime.assistant.permissions import ToolAllowlistPolicy
from runtime.assistant.request import AssistantRequest
from runtime.context import ApplicationContext
from runtime.conversation.conversation import Conversation
from runtime.conversation.message import Message, MessageRole
from runtime.providers.base import AssistantTurn, ToolCall
from runtime.providers.scripted import ScriptedProvider
from runtime.tools.diff import DiffTool
from runtime.tools.filesystem import FilesystemTool
from runtime.tools.git import GitTool
from runtime.tools.shell import ShellTool
from runtime.tools.test_runner import TestRunnerTool

ALL_BUILTIN_TOOL_IDS = ("filesystem", "shell", "git", "diff", "test_runner")


def make_application_context(allowed_tool_ids: tuple[str, ...] = ALL_BUILTIN_TOOL_IDS) -> ApplicationContext:
    app_context = ApplicationContext(
        config=Config(assistant_provider="scripted"),
        logger=logging.getLogger("test.tool_integration"),
    )
    app_context.assistant.set_permission_policy(ToolAllowlistPolicy(allowed_tool_ids))
    return app_context


def make_conversation(app_context: ApplicationContext) -> Conversation:
    return app_context.conversations.create(app_context)


def make_request(conversation: Conversation) -> AssistantRequest:
    return AssistantRequest(conversation_id=conversation.conversation_id, text="do the work")


def install_scripted(app_context: ApplicationContext, turns: list[AssistantTurn]) -> ScriptedProvider:
    provider = ScriptedProvider(turns)
    app_context.assistant_providers.register(provider)
    return provider


def tool_messages(conversation: Conversation) -> list[Message]:
    return [message for message in conversation.messages if message.role is MessageRole.TOOL]


def init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-b", "master", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@example.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"], check=True, capture_output=True
    )


# --- Filesystem ----------------------------------------------------------------


def test_filesystem_tool_write_then_read_round_trips_through_the_engine(tmp_path: Path) -> None:
    app_context = make_application_context()
    app_context.tools.register(FilesystemTool(tmp_path), app_context)
    install_scripted(
        app_context,
        [
            AssistantTurn(
                tool_calls=(
                    ToolCall(
                        tool_id="filesystem",
                        arguments={"operation": "write", "path": "notes.txt", "content": "hello"},
                    ),
                )
            ),
            AssistantTurn(
                tool_calls=(
                    ToolCall(tool_id="filesystem", arguments={"operation": "read", "path": "notes.txt"}),
                )
            ),
            AssistantTurn(text="Done."),
        ],
    )
    conversation = make_conversation(app_context)

    response = app_context.assistant.handle(make_request(conversation), app_context)

    assert response.success is True
    assert response.turns == 3
    messages = tool_messages(conversation)
    assert "Wrote" in messages[0].content
    assert messages[1].content == "hello"
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "hello"


# --- Shell ----------------------------------------------------------------


def test_shell_tool_runs_through_the_engine(tmp_path: Path) -> None:
    app_context = make_application_context()
    app_context.tools.register(ShellTool(tmp_path), app_context)
    install_scripted(
        app_context,
        [
            AssistantTurn(
                tool_calls=(
                    ToolCall(
                        tool_id="shell",
                        arguments={"command": f'"{sys.executable}" -c "print(6 * 7)"'},
                    ),
                )
            ),
            AssistantTurn(text="42."),
        ],
    )
    conversation = make_conversation(app_context)

    response = app_context.assistant.handle(make_request(conversation), app_context)

    assert response.success is True
    assert "42" in tool_messages(conversation)[0].content


# --- Git ----------------------------------------------------------------


def test_git_tool_status_through_the_engine(tmp_path: Path) -> None:
    init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    app_context = make_application_context()
    app_context.tools.register(GitTool(tmp_path), app_context)
    install_scripted(
        app_context,
        [
            AssistantTurn(tool_calls=(ToolCall(tool_id="git", arguments={"operation": "status"}),)),
            AssistantTurn(text="An untracked file is present."),
        ],
    )
    conversation = make_conversation(app_context)

    response = app_context.assistant.handle(make_request(conversation), app_context)

    assert response.success is True
    assert "a.txt" in tool_messages(conversation)[0].content


# --- Diff ----------------------------------------------------------------


def test_diff_tool_through_the_engine(tmp_path: Path) -> None:
    app_context = make_application_context()
    app_context.tools.register(DiffTool(tmp_path), app_context)
    install_scripted(
        app_context,
        [
            AssistantTurn(
                tool_calls=(ToolCall(tool_id="diff", arguments={"from_text": "a\n", "to_text": "b\n"}),)
            ),
            AssistantTurn(text="They differ."),
        ],
    )
    conversation = make_conversation(app_context)

    response = app_context.assistant.handle(make_request(conversation), app_context)

    assert response.success is True
    assert "-a" in tool_messages(conversation)[0].content
    assert "+b" in tool_messages(conversation)[0].content


# --- Test Runner ----------------------------------------------------------------


def test_test_runner_tool_through_the_engine(tmp_path: Path) -> None:
    (tmp_path / "test_sample.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    app_context = make_application_context()
    app_context.tools.register(TestRunnerTool(tmp_path), app_context)
    install_scripted(
        app_context,
        [
            AssistantTurn(tool_calls=(ToolCall(tool_id="test_runner", arguments={}),)),
            AssistantTurn(text="The suite passes."),
        ],
    )
    conversation = make_conversation(app_context)

    response = app_context.assistant.handle(make_request(conversation), app_context)

    assert response.success is True
    assert "passed=1" in tool_messages(conversation)[0].content


# --- ToolAllowlistPolicy gating real tools ----------------------------------------------------------------


def test_allowlist_policy_denies_a_tool_not_on_the_list(tmp_path: Path) -> None:
    app_context = make_application_context(allowed_tool_ids=("filesystem",))
    app_context.tools.register(ShellTool(tmp_path), app_context)
    install_scripted(
        app_context,
        [
            AssistantTurn(tool_calls=(ToolCall(tool_id="shell", arguments={"command": "echo hi"}),)),
            AssistantTurn(text="Could not run the shell."),
        ],
    )
    conversation = make_conversation(app_context)

    response = app_context.assistant.handle(make_request(conversation), app_context)

    assert response.success is True
    message = tool_messages(conversation)[0].content
    assert "denied" in message.lower()
    assert "not on the allowlist" in message


def test_allowlist_policy_allows_a_listed_tool_to_run(tmp_path: Path) -> None:
    app_context = make_application_context(allowed_tool_ids=("filesystem",))
    app_context.tools.register(FilesystemTool(tmp_path), app_context)
    install_scripted(
        app_context,
        [
            AssistantTurn(
                tool_calls=(
                    ToolCall(
                        tool_id="filesystem",
                        arguments={"operation": "write", "path": "a.txt", "content": "hi"},
                    ),
                )
            ),
            AssistantTurn(text="Done."),
        ],
    )
    conversation = make_conversation(app_context)

    response = app_context.assistant.handle(make_request(conversation), app_context)

    assert response.success is True
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hi"

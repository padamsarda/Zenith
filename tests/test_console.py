"""Tests for the ConsoleInterface."""

from __future__ import annotations

import io
import logging

from configs.config import Config
from runtime.console import ConsoleInterface
from runtime.context import ApplicationContext
from runtime.conversation.state import ConversationState
from runtime.providers.base import AssistantTurn
from runtime.providers.echo import EchoProvider
from runtime.providers.scripted import ScriptedProvider


def make_application_context(config: Config | None = None) -> ApplicationContext:
    app_context = ApplicationContext(
        config=config or Config(), logger=logging.getLogger("test.console")
    )
    app_context.assistant_providers.register(EchoProvider())
    return app_context


def run_session(app_context: ApplicationContext, user_input: str) -> str:
    output = io.StringIO()
    ConsoleInterface(input_stream=io.StringIO(user_input), output_stream=output).run(
        app_context
    )
    return output.getvalue()


def test_session_echoes_a_reply() -> None:
    app_context = make_application_context()

    output = run_session(app_context, "hello\nexit\n")

    assert "you> " in output
    assert "zenith> You said: hello" in output


def test_session_ends_at_eof() -> None:
    app_context = make_application_context()

    output = run_session(app_context, "")

    assert "zenith>" not in output


def test_quit_also_ends_the_session() -> None:
    app_context = make_application_context()

    output = run_session(app_context, "QUIT\n")

    assert "zenith>" not in output


def test_blank_lines_are_skipped() -> None:
    app_context = make_application_context()

    output = run_session(app_context, "\n   \nexit\n")

    assert "zenith>" not in output


def test_whole_session_shares_one_conversation() -> None:
    app_context = make_application_context()

    run_session(app_context, "first\nsecond\nexit\n")

    (conversation,) = app_context.conversations.list()
    assert len(conversation.messages) == 4


def test_conversation_is_archived_after_the_session() -> None:
    app_context = make_application_context()

    run_session(app_context, "hello\nexit\n")

    (conversation,) = app_context.conversations.list()
    assert conversation.state is ConversationState.ARCHIVED


def test_failed_requests_still_print_their_text() -> None:
    app_context = ApplicationContext(
        config=Config(assistant_provider="scripted"),
        logger=logging.getLogger("test.console"),
    )
    app_context.assistant_providers.register(ScriptedProvider([]))

    output = run_session(app_context, "hello\nexit\n")

    assert "zenith> " in output
    assert "no turns left" in output


def test_session_serves_scripted_replies_in_order() -> None:
    app_context = ApplicationContext(
        config=Config(assistant_provider="scripted"),
        logger=logging.getLogger("test.console"),
    )
    app_context.assistant_providers.register(
        ScriptedProvider([AssistantTurn(text="one"), AssistantTurn(text="two")])
    )

    output = run_session(app_context, "a\nb\nexit\n")

    assert output.index("zenith> one") < output.index("zenith> two")

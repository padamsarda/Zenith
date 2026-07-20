"""ConsoleInterface: an interactive text session over the assistant pipeline."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, TextIO

from runtime.assistant.request import AssistantRequest

if TYPE_CHECKING:
    from runtime.context import ApplicationContext

EXIT_WORDS: frozenset[str] = frozenset({"exit", "quit"})
PROMPT = "you> "
REPLY_PREFIX = "zenith> "


class ConsoleInterface:
    """Reads user lines, submits them as requests, and prints the replies.

    The first user-facing surface of the runtime, and deliberately a
    thin one: it owns nothing but line I/O. Each line becomes an
    `AssistantRequest` served by `context.assistant`, inside one
    conversation created at session start and archived at session end —
    everything else (validation, events, tools, permissions) is the
    pipeline's, so any future interface (voice, GUI, network) gets
    identical behavior by doing exactly what this class does.

    Streams are injectable for tests; they default to stdin/stdout.
    """

    def __init__(
        self, input_stream: TextIO | None = None, output_stream: TextIO | None = None
    ) -> None:
        self._input = input_stream if input_stream is not None else sys.stdin
        self._output = output_stream if output_stream is not None else sys.stdout

    def run(self, application_context: ApplicationContext) -> None:
        """Serve one console session until EOF or an exit word.

        Blank lines are skipped. The session's conversation is archived
        on the way out, whatever ended the session.
        """
        conversation = application_context.conversations.create(
            application_context, title="Console session"
        )
        self._write("Zenith console. Type 'exit' to quit.\n")
        try:
            while True:
                self._write(PROMPT)
                line = self._input.readline()
                if not line or line.strip().lower() in EXIT_WORDS:
                    break
                if not line.strip():
                    continue
                request = AssistantRequest(
                    conversation_id=conversation.conversation_id, text=line.strip()
                )
                response = application_context.assistant.handle(
                    request, application_context
                )
                self._write(f"{REPLY_PREFIX}{response.text}\n")
        finally:
            application_context.conversations.archive(
                conversation.conversation_id, application_context
            )

    def _write(self, text: str) -> None:
        """Write `text` to the output stream and flush it."""
        self._output.write(text)
        self._output.flush()

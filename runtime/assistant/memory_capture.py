"""MemoryCaptureHook: storing what is worth remembering, without being asked.

Automatic recall (`AssistantContextAssembler`) is only half of memory
working by itself; something has to *write* memories without the user
running a command. This `AssistantHook` watches completed requests and
stores the user's own words when the salience rules say they are worth
keeping — an explicit "remember that…", a decision, a preference, a
task — and stays silent for the device commands and pleasantries that
make up most of what an assistant is told (ADR 0027).

It is an `after_request` hook, so it observes rather than intercepts:
capture happens once a request has already succeeded, and a failure to
capture is logged and swallowed exactly like any other observational
hook. Nothing a memory system does is worth failing a user's request
over.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from runtime.assistant.hooks import AssistantHook
from runtime.memory.consolidation import MemoryConsolidator
from runtime.memory.memory import Memory
from runtime.memory.salience import classify, has_explicit_marker, is_trivial, score_importance

if TYPE_CHECKING:
    from runtime.assistant.request import AssistantRequest
    from runtime.assistant.response import AssistantResponse
    from runtime.context import ApplicationContext

DEFAULT_LOGGER_NAME = "zenith.assistant.memory_capture"
MAX_CAPTURED_LENGTH = 500


class MemoryCaptureHook(AssistantHook):
    """Stores salient user statements as memories after a request succeeds.

    Captures the user's *own words* rather than a model-generated
    summary. That is a deliberate limitation: a summary would read
    better and could merge related facts, but it costs an extra provider
    call per turn and can silently invent detail the user never said.
    Verbatim capture is cheap, deterministic, and never wrong about what
    was actually said — an extraction pass (as Mem0 and Stanford's
    original design both use) is the natural refinement, and slots in
    behind this same hook.
    """

    def __init__(
        self,
        *,
        consolidator: MemoryConsolidator | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        """Create the hook.

        Args:
            consolidator: How captured memories are written. Goes through
                a `MemoryConsolidator` rather than the store directly so
                repeated statements strengthen what is already known
                instead of accumulating near-duplicates (ADR 0028).
            logger: Defaults to a module logger.
        """
        self._consolidator = consolidator or MemoryConsolidator()
        self._logger = logger or logging.getLogger(DEFAULT_LOGGER_NAME)

    def after_request(
        self,
        request: AssistantRequest,
        response: AssistantResponse,
        application_context: ApplicationContext,
    ) -> None:
        """Store `request.text` as a memory if it is worth remembering.

        Skipped entirely for failed requests: whatever went wrong, the
        exchange did not happen the way the user intended, and recording
        it as something Zeni "knows" would be recording a
        misunderstanding.
        """
        if not response.success or is_trivial(request.text):
            return

        text = request.text.strip()
        if len(text) > MAX_CAPTURED_LENGTH:
            text = text[:MAX_CAPTURED_LENGTH].rstrip() + "…"

        kind = classify(text)
        explicit = has_explicit_marker(text)
        memory = Memory(
            content=text,
            kind=kind,
            importance=score_importance(text, kind),
            pinned=explicit,
            source="conversation",
            metadata={"conversation_id": str(request.conversation_id)},
        )
        try:
            decision = self._consolidator.store(memory, application_context)
        except Exception:
            self._logger.warning("Failed to capture memory.", exc_info=True)
            return
        self._logger.debug(
            "Captured %s memory (%s): %s", kind.name.lower(), decision.action.name.lower(), text
        )

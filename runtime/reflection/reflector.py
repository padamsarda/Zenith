"""Reflector: turning a body of memories into an insight.

The one part of reflection that needs a model, isolated behind an ABC so
everything else — when to reflect, what to reflect over, how to store
provenance — stays testable without one, and so a deployment can supply
a cheaper model here than it uses for conversation (ADR 0029).

`ProviderReflector` performs reflection through the existing
`AssistantProvider` contract (ADR 0011) rather than inventing a second
path to a model: a reflection is one turn, given instructions and
material, producing text. No tools, no loop, no conversation.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING

from runtime.capabilities.catalog import CapabilityCatalog
from runtime.conversation.message import Message, MessageRole
from runtime.memory.memory import Memory
from runtime.providers.base import TurnBrief
from runtime.reflection.prompts import NOTHING_MARKER, render_memories
from shared.utils.time_utils import utc_now
from shared.utils.uuid_utils import generate_id

if TYPE_CHECKING:
    from runtime.providers.base import AssistantProvider

DEFAULT_LOGGER_NAME = "zenith.reflection"


class Reflector(ABC):
    """Produces the text of a reflection from memories and instructions.

    Storage-independent by construction: it receives `Memory` objects and
    returns a string, never touching a store. That is what lets the same
    reflector work over any `MemoryStore` backend, and lets every other
    part of the reflection layer be tested with a stub reflector and no
    model at all.
    """

    @abstractmethod
    def reflect(
        self,
        memories: Sequence[Memory],
        instructions: str,
        *,
        now: datetime | None = None,
    ) -> str | None:
        """Return the insight drawn from `memories`, or None if there is none.

        Returning `None` is a first-class outcome, not a failure: a
        reflector that cannot find a real pattern must be able to say so,
        or every scheduled run manufactures one (ADR 0029).
        """

    @property
    def model(self) -> str | None:
        """The model this reflector used, recorded on reflections for traceability."""
        return None


class ProviderReflector(Reflector):
    """Reflects by asking an `AssistantProvider` for a single turn.

    The provider is injected rather than resolved from configuration, so
    a deployment can point reflection at a smaller, cheaper model than it
    talks to — reflection runs unattended and its latency is invisible,
    which is exactly when a cheaper model is worth using.
    """

    def __init__(
        self,
        provider: AssistantProvider,
        *,
        model: str | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._provider = provider
        self._model = model
        self._logger = logger or logging.getLogger(DEFAULT_LOGGER_NAME)

    @property
    def model(self) -> str | None:
        return self._model or self._provider.provider_id

    def reflect(
        self,
        memories: Sequence[Memory],
        instructions: str,
        *,
        now: datetime | None = None,
    ) -> str | None:
        """Ask the provider to reflect over `memories`.

        Never raises: a provider failure means no reflection this time,
        which is a strictly better outcome than a failed conversation or
        a crashed startup. Returns `None` for a failure, an empty turn,
        or the model's own `NOTHING` verdict.
        """
        if not memories:
            return None

        material = render_memories(memories, now or utc_now())
        brief = TurnBrief(
            conversation_id=generate_id(),
            messages=(Message(role=MessageRole.USER, content=material),),
            instructions=instructions,
            catalog=CapabilityCatalog(tools=(), skills=()),
            metadata={"purpose": "reflection"},
        )

        try:
            turn = self._provider.generate_turn(brief)
        except Exception:
            self._logger.warning("Reflection provider failed.", exc_info=True)
            return None

        text = (turn.text or "").strip()
        if not text or text.upper().startswith(NOTHING_MARKER):
            return None
        return text

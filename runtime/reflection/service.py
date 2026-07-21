"""ReflectionService: the three levels of reflection, and when each runs.

One object owning all three triggers (ADR 0029), because they differ
only in *when* they fire and *what* they read — the machinery beneath
(gather memories, reflect, store with provenance) is identical, and
duplicating it three times would let the three drift apart.

| Level | Trigger | Reads | Stored as |
|---|---|---|---|
| Session | A meaningful conversation ended | That conversation's memories | `SESSION` |
| Deep | Due by schedule, checked at startup | Everything accumulated | `DEEP`, generation N+1 |
| On demand | The user asked | Memories relevant to the question | `ON_DEMAND` |

Every level is best-effort: reflection is derived, optional value on top
of a system that works without it, so a failure anywhere here degrades
to "no reflection" and never to a failed request, a failed archive, or a
failed startup.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from runtime.memory.memory import Memory
from runtime.reflection.events import ReflectionSkipped
from runtime.reflection.prompts import (
    DEEP_INSTRUCTIONS,
    SESSION_INSTRUCTIONS,
    on_demand_instructions,
)
from runtime.reflection.reflection import FIRST_GENERATION, Reflection, ReflectionKind
from runtime.reflection.store import SOURCE
from shared.utils.time_utils import utc_now

if TYPE_CHECKING:
    from runtime.context import ApplicationContext
    from runtime.reflection.reflector import Reflector

DEFAULT_LOGGER_NAME = "zenith.reflection"

# A conversation must have produced at least this many memories before it
# is worth a model call. "Open Spotify, thanks" produces none and must
# not trigger reflection; the threshold is what makes level one
# "meaningful conversations, not every chat".
DEFAULT_MIN_SESSION_MEMORIES = 3

# Deep reflection needs enough accumulated material for a pattern to be
# real rather than manufactured from three data points.
DEFAULT_MIN_DEEP_MEMORIES = 15

DEFAULT_DEEP_INTERVAL_HOURS = 24.0
DEFAULT_DEEP_MEMORY_LIMIT = 300
DEFAULT_ON_DEMAND_LIMIT = 60


class ReflectionService:
    """Runs and stores the three levels of reflection."""

    def __init__(
        self,
        reflector: Reflector,
        *,
        min_session_memories: int = DEFAULT_MIN_SESSION_MEMORIES,
        min_deep_memories: int = DEFAULT_MIN_DEEP_MEMORIES,
        deep_interval_hours: float = DEFAULT_DEEP_INTERVAL_HOURS,
        deep_memory_limit: int = DEFAULT_DEEP_MEMORY_LIMIT,
        on_demand_limit: int = DEFAULT_ON_DEMAND_LIMIT,
        logger: logging.Logger | None = None,
    ) -> None:
        """Create the service.

        Args:
            reflector: Produces the insight text. Injected, so every
                level is testable without a model.
            min_session_memories: Below this, a conversation is not worth
                reflecting on.
            min_deep_memories: Below this, there is not enough material
                for a deep reflection to find anything real.
            deep_interval_hours: How long between deep reflections.
            deep_memory_limit: How many memories a deep reflection reads.
            on_demand_limit: How many memories an on-demand reflection
                reads.
            logger: Defaults to a module logger.
        """
        self._reflector = reflector
        self._min_session_memories = min_session_memories
        self._min_deep_memories = min_deep_memories
        self._deep_interval_hours = deep_interval_hours
        self._deep_memory_limit = deep_memory_limit
        self._on_demand_limit = on_demand_limit
        self._logger = logger or logging.getLogger(DEFAULT_LOGGER_NAME)

    # --- level one: session ------------------------------------------------

    def reflect_on_session(
        self,
        conversation_id: UUID,
        application_context: ApplicationContext,
        *,
        now: datetime | None = None,
    ) -> Reflection | None:
        """Summarize one finished conversation, if it produced enough to be worth it.

        Reads only the memories captured *from that conversation*, which
        `MemoryCaptureHook` stamps with its ID — so a session reflection
        is genuinely about that session rather than about whatever the
        store happens to hold.
        """
        moment = now or utc_now()
        memories = self._memories_from_conversation(conversation_id, application_context)
        if len(memories) < self._min_session_memories:
            self._skip(
                application_context,
                ReflectionKind.SESSION,
                f"only {len(memories)} memories from this conversation",
            )
            return None
        return self._perform(
            memories, SESSION_INSTRUCTIONS, ReflectionKind.SESSION, application_context, moment
        )

    def on_conversation_archived(
        self, conversation_id: UUID, application_context: ApplicationContext
    ) -> None:
        """Event-facing entry point for level one; never raises.

        Subscribed to `ConversationArchived`. Archiving a conversation
        must succeed whether or not reflection does, so everything here
        is swallowed and logged.
        """
        try:
            self.reflect_on_session(conversation_id, application_context)
        except Exception:
            self._logger.warning("Session reflection failed.", exc_info=True)

    # --- level two: deep ------------------------------------------------

    def is_deep_reflection_due(
        self, application_context: ApplicationContext, *, now: datetime | None = None
    ) -> bool:
        """Return whether enough time has passed since the last deep reflection."""
        moment = now or utc_now()
        latest = application_context.reflections.latest(ReflectionKind.DEEP)
        if latest is None:
            return True
        return moment - latest.created_at >= timedelta(hours=self._deep_interval_hours)

    def reflect_deeply(
        self,
        application_context: ApplicationContext,
        *,
        force: bool = False,
        now: datetime | None = None,
    ) -> Reflection | None:
        """Synthesize across everything accumulated, if due and there is enough.

        The new reflection is stored as the next `generation`, pointing
        at the one it supersedes. Nothing is overwritten: the whole
        series stays readable, so how Zeni's understanding changed is
        itself inspectable (ADR 0029).
        """
        moment = now or utc_now()
        if not force and not self.is_deep_reflection_due(application_context, now=moment):
            self._skip(application_context, ReflectionKind.DEEP, "not due yet")
            return None

        memories = application_context.memory.list()[: self._deep_memory_limit]
        if len(memories) < self._min_deep_memories:
            self._skip(
                application_context,
                ReflectionKind.DEEP,
                f"only {len(memories)} memories accumulated",
            )
            return None

        previous = application_context.reflections.latest(ReflectionKind.DEEP)
        return self._perform(
            memories,
            DEEP_INSTRUCTIONS,
            ReflectionKind.DEEP,
            application_context,
            moment,
            generation=(previous.generation + 1) if previous else FIRST_GENERATION,
            supersedes=previous.reflection_id if previous else None,
        )

    # --- level three: on demand ------------------------------------------------

    def reflect_on_demand(
        self,
        question: str,
        application_context: ApplicationContext,
        *,
        now: datetime | None = None,
    ) -> Reflection | None:
        """Answer `question` with a fresh reflection over the relevant memories.

        Retrieval is the ordinary memory search, so the question itself
        selects the material — "what have you learned about me" reads
        broadly, "what did I decide about the battery" reads narrowly.
        """
        moment = now or utc_now()
        candidates = application_context.memory.search(question, limit=self._on_demand_limit)
        memories = [candidate.memory for candidate in candidates]
        if not memories:
            # Nothing matched the question; fall back to what is most
            # recent, since a broad question ("what patterns do you see")
            # frequently shares no words with any specific memory.
            memories = application_context.memory.list()[: self._on_demand_limit]
        if not memories:
            self._skip(application_context, ReflectionKind.ON_DEMAND, "nothing remembered yet")
            return None

        return self._perform(
            memories,
            on_demand_instructions(question),
            ReflectionKind.ON_DEMAND,
            application_context,
            moment,
            metadata={"question": question},
        )

    # --- shared ------------------------------------------------

    def _perform(
        self,
        memories: list[Memory],
        instructions: str,
        kind: ReflectionKind,
        application_context: ApplicationContext,
        now: datetime,
        *,
        generation: int = FIRST_GENERATION,
        supersedes: UUID | None = None,
        metadata: dict[str, object] | None = None,
    ) -> Reflection | None:
        """Reflect over `memories` and store the result with its provenance."""
        content = self._reflector.reflect(memories, instructions, now=now)
        if content is None:
            self._skip(application_context, kind, "no insight produced")
            return None

        reflection = Reflection(
            content=content,
            kind=kind,
            source_memory_ids=tuple(memory.memory_id for memory in memories),
            generation=generation,
            supersedes=supersedes,
            model=self._reflector.model,
            metadata=dict(metadata or {}),
            created_at=now,
        )
        stored = application_context.reflections.add(reflection, application_context)
        self._logger.info(
            "Stored %s reflection (generation %d) from %d memories.",
            kind.name.lower(),
            generation,
            len(memories),
        )
        return stored

    def _memories_from_conversation(
        self, conversation_id: UUID, application_context: ApplicationContext
    ) -> list[Memory]:
        """Return the memories captured from one conversation, oldest first."""
        wanted = str(conversation_id)
        found = [
            memory
            for memory in application_context.memory.list()
            if memory.metadata.get("conversation_id") == wanted
        ]
        found.reverse()
        return found

    def _skip(
        self, application_context: ApplicationContext, kind: ReflectionKind, reason: str
    ) -> None:
        """Announce that reflection was considered and declined."""
        self._logger.debug("Skipped %s reflection: %s", kind.name.lower(), reason)
        application_context.events.emit(
            ReflectionSkipped(source=SOURCE, payload={"kind": kind.name, "reason": reason})
        )

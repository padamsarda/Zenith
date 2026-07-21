"""MemoryRecaller: turning a user's message into the memories it needs.

The piece that makes memory *automatic* rather than something the model
must think to ask for. `AssistantContextAssembler` calls `recall` while
composing every brief, so relevant memories are already present when the
provider produces its turn — a question never has to be answered with
"let me check my notes first", and no turn is spent on a tool call to
retrieve what could simply have been there (ADR 0027).

Three steps, each in a module of its own: resolve any relative time
expression to an absolute window (`temporal`), ask the store for
candidates in that window (`MemoryStore.search`), and rank them
(`MemoryRetrievalPolicy`).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from runtime.memory.events import MemoriesRecalled
from runtime.memory.retrieval import (
    MemoryRetrievalPolicy,
    RecencyImportanceRelevancePolicy,
    ScoredMemory,
)
from runtime.memory.store import SOURCE
from runtime.memory.temporal import parse_temporal_query
from shared.utils.time_utils import utc_now

if TYPE_CHECKING:
    from runtime.context import ApplicationContext

DEFAULT_RECALL_LIMIT = 6
DEFAULT_CANDIDATE_LIMIT = 50


class MemoryRecaller:
    """Recalls the memories relevant to a piece of user text.

    Holds no state beyond its policy and limits: every recall is
    computed from the store and the query at the moment it is needed,
    never cached, so what Zeni remembers can never go stale relative to
    what it has been told (ADR 0010's principle, applied to memory).
    """

    def __init__(
        self,
        *,
        policy: MemoryRetrievalPolicy | None = None,
        recall_limit: int = DEFAULT_RECALL_LIMIT,
        candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    ) -> None:
        """Create a MemoryRecaller.

        Args:
            policy: How candidates are ranked. Defaults to
                `RecencyImportanceRelevancePolicy`.
            recall_limit: How many memories reach the brief. Small on
                purpose — a brief crowded with marginal memories is worse
                than one with none, since every entry competes for the
                model's attention with the actual conversation.
            candidate_limit: How many candidates the store returns for
                ranking, before the policy narrows them to `recall_limit`.
        """
        self._policy = policy or RecencyImportanceRelevancePolicy()
        self._recall_limit = recall_limit
        self._candidate_limit = candidate_limit

    def recall(
        self,
        text: str,
        application_context: ApplicationContext,
        *,
        now: datetime | None = None,
    ) -> tuple[ScoredMemory, ...]:
        """Return the memories most worth having in context for `text`.

        Records the recall against each returned memory (`touch`), so
        recency reflects what actually gets used. Emits
        `MemoriesRecalled`. Never raises: a memory subsystem that fails
        must degrade to an assistant with no memory, not a failed
        request.
        """
        moment = now or utc_now()
        store = application_context.memory
        try:
            parsed = parse_temporal_query(text, moment)
            window = parsed.window
            candidates = store.search(
                parsed.subject, window=window, limit=self._candidate_limit
            )
            # A question that named a period deserves an answer about
            # that period. If nothing in the window matched the subject
            # lexically, fall back to the window itself rather than
            # reporting nothing — "what was I doing yesterday" should
            # surface yesterday's work even when no word overlaps.
            if not candidates and window is not None:
                candidates = store.search("", window=window, limit=self._candidate_limit)
            recalled = self._policy.rank(candidates, moment, self._recall_limit)
            if recalled:
                store.touch(tuple(scored.memory for scored in recalled), application_context)
        except Exception:
            application_context.logger.warning("Memory recall failed.", exc_info=True)
            return ()

        application_context.events.emit(
            MemoriesRecalled(
                source=SOURCE,
                payload={
                    "query": text,
                    "count": len(recalled),
                    "window": None if window is None else window.start.isoformat(),
                },
            )
        )
        return recalled


def render_memories(recalled: tuple[ScoredMemory, ...], now: datetime) -> str | None:
    """Render recalled memories as a brief section, or None if there are none.

    Each line carries how long ago the thing happened, in the vocabulary
    a person uses. Without it the model sees a bare list of facts with no
    way to answer "when did we decide that?", which is half of what makes
    memory feel like memory rather than a lookup table.
    """
    if not recalled:
        return None
    lines = [
        f"- ({describe_age(scored.memory.occurred_at, now)}) {scored.memory.content}"
        for scored in recalled
    ]
    return (
        "[What you remember]\n"
        "Relevant things you already know about this user. Use them when they "
        "help; do not mention them if they are not relevant.\n" + "\n".join(lines)
    )


def describe_age(moment: datetime, now: datetime) -> str:
    """Describe how long before `now` `moment` was, the way a person would."""
    delta = now - moment
    days = delta.days
    if days < 0:
        return "just now"
    if days == 0:
        hours = delta.seconds // 3600
        if hours == 0:
            return "minutes ago"
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    if days < 30:
        weeks = days // 7
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"
    if days < 365:
        months = days // 30
        return f"{months} month{'s' if months != 1 else ''} ago"
    years = days // 365
    return f"{years} year{'s' if years != 1 else ''} ago"

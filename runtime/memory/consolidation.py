"""Keeping the memory store from filling with near-duplicates and stale facts.

Automatic capture (ADR 0027) writes something every time the user says
anything substantive, which is what makes memory work unprompted — and
also what makes it degrade. Say "the CubeSat battery is lithium" three
times across a month and, without this module, there are three memories
saying it, all competing for the same handful of slots in a brief. Say
"actually we switched to LiFePO4" and both the old and new fact persist,
with recency alone deciding which one Zeni believes.

Consolidation is the write-side answer, run before a memory is stored:
look for what is already known, and decide whether this is genuinely new
(ADD), the same thing again (REINFORCE), or a correction of it
(SUPERSEDE). Pruning is the long-run answer, dropping what has proven
worthless. See ADR 0028.

**Deliberately conservative about deletion.** Reinforcing costs nothing
if wrong — the fact stays, slightly stronger. Superseding destroys a
real memory, so it fires only on an explicit correction marker
("actually", "no longer", "we switched"), never on similarity alone.
Semantic contradiction with no such marker ("battery is lithium" then
"battery is LiFePO4", stated flatly) is left for a future model-assisted
policy behind this same seam.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum, auto
from typing import TYPE_CHECKING

from runtime.memory.matching import similarity, subject_overlap
from runtime.memory.memory import Memory
from runtime.memory.salience import has_correction_marker
from shared.utils.time_utils import utc_now

if TYPE_CHECKING:
    from runtime.context import ApplicationContext

DEFAULT_LOGGER_NAME = "zenith.memory.consolidation"

# How alike two statements must be before they are treated as the same
# thing. Tuned high: merging two genuinely different facts loses one of
# them, while failing to merge two similar ones merely wastes a slot.
DEFAULT_REINFORCE_THRESHOLD = 0.85

# Supersession asks a different question than reinforcement, and so uses
# a different measure (`subject_overlap`, not `similarity`): not "is this
# the same statement" but "is this about the same thing". A correction
# necessarily says something new, so judging it by statement-similarity
# would rule out exactly the case it exists to catch. The lower bar is
# safe *only* because an explicit correction marker is also required.
DEFAULT_SUPERSEDE_THRESHOLD = 0.35

# How many existing memories to compare a new one against. Comparison is
# lexical and cheap, but unbounded comparison would make writes scale
# with the size of the whole store.
DEFAULT_COMPARISON_LIMIT = 25


class ConsolidationAction(Enum):
    """What to do with a candidate memory, given what is already known."""

    ADD = auto()
    """Genuinely new. Store it."""

    REINFORCE = auto()
    """Already known. Strengthen the existing memory instead of duplicating."""

    SUPERSEDE = auto()
    """Corrects something known. Replace the old memory with this one."""


@dataclass(frozen=True)
class ConsolidationDecision:
    """What to do, and which existing memory it concerns.

    `existing` is `None` only for `ADD`. Keeping the matched memory on
    the decision lets a caller log or explain a merge rather than
    silently observing that a write did not produce a new row.
    """

    action: ConsolidationAction
    existing: Memory | None = None
    similarity: float = 0.0


class ConsolidationPolicy(ABC):
    """Decides whether a new memory is new, a repeat, or a correction.

    The memory subsystem's write-side policy seam, matching
    `MemoryRetrievalPolicy` on the read side: swap the class to change
    how aggressively memories merge, without touching the store, the
    capture hook, or the tool.
    """

    @abstractmethod
    def decide(self, candidate: Memory, existing: tuple[Memory, ...]) -> ConsolidationDecision:
        """Return what to do with `candidate` given the `existing` memories it resembles."""


class LexicalConsolidationPolicy(ConsolidationPolicy):
    """Merges by lexical similarity, and supersedes only on an explicit correction.

    The deterministic counterpart to the LLM-driven reconciliation step
    production memory systems use. It cannot detect that two differently
    worded statements contradict each other — that genuinely needs
    semantics — but it costs nothing per write, never varies between
    identical inputs, and cannot hallucinate a contradiction that was
    not there.
    """

    def __init__(
        self,
        *,
        reinforce_threshold: float = DEFAULT_REINFORCE_THRESHOLD,
        supersede_threshold: float = DEFAULT_SUPERSEDE_THRESHOLD,
    ) -> None:
        self._reinforce_threshold = reinforce_threshold
        self._supersede_threshold = supersede_threshold

    def decide(self, candidate: Memory, existing: tuple[Memory, ...]) -> ConsolidationDecision:
        """Compare `candidate` against `existing` and choose an action."""
        if not existing:
            return ConsolidationDecision(action=ConsolidationAction.ADD)

        if has_correction_marker(candidate.content):
            score, best = self._best(candidate, existing, subject_overlap)
            if score >= self._supersede_threshold:
                return ConsolidationDecision(
                    action=ConsolidationAction.SUPERSEDE, existing=best, similarity=score
                )
            return ConsolidationDecision(action=ConsolidationAction.ADD, similarity=score)

        score, best = self._best(candidate, existing, similarity)
        if score >= self._reinforce_threshold:
            return ConsolidationDecision(
                action=ConsolidationAction.REINFORCE, existing=best, similarity=score
            )
        return ConsolidationDecision(action=ConsolidationAction.ADD, similarity=score)

    @staticmethod
    def _best(
        candidate: Memory,
        existing: tuple[Memory, ...],
        measure: Callable[[str, str], float],
    ) -> tuple[float, Memory]:
        """Return the highest-scoring existing memory under `measure`, and its score."""
        return max(
            ((measure(candidate.content, other.content), other) for other in existing),
            key=lambda pair: pair[0],
        )


class MemoryConsolidator:
    """Writes memories through a `ConsolidationPolicy`, and prunes on request.

    Every path that stores a memory goes through `store` rather than
    calling `MemoryStore.remember` directly, so consolidation cannot be
    bypassed by adding a new writer later. The store itself stays a
    dumb persistence layer — deciding what is a duplicate is policy, and
    would otherwise have to be reimplemented in every backend.
    """

    def __init__(
        self,
        *,
        policy: ConsolidationPolicy | None = None,
        comparison_limit: int = DEFAULT_COMPARISON_LIMIT,
        logger: logging.Logger | None = None,
    ) -> None:
        self._policy = policy or LexicalConsolidationPolicy()
        self._comparison_limit = comparison_limit
        self._logger = logger or logging.getLogger(DEFAULT_LOGGER_NAME)

    def store(
        self,
        candidate: Memory,
        application_context: ApplicationContext,
        *,
        now: datetime | None = None,
    ) -> ConsolidationDecision:
        """Store `candidate`, merging it into what is already known if appropriate.

        Returns the decision taken, so a caller can report a merge rather
        than a write. Never raises for a policy or comparison failure:
        the fallback is to store the memory plainly, since an
        un-consolidated memory is a much smaller problem than a lost one.
        """
        moment = now or utc_now()
        memory_store = application_context.memory

        try:
            neighbours = tuple(
                candidate_memory.memory
                for candidate_memory in memory_store.search(
                    candidate.content, limit=self._comparison_limit
                )
            )
            decision = self._policy.decide(candidate, neighbours)
        except Exception:
            self._logger.warning("Consolidation failed; storing plainly.", exc_info=True)
            memory_store.remember(candidate, application_context)
            return ConsolidationDecision(action=ConsolidationAction.ADD)

        if decision.action is ConsolidationAction.REINFORCE and decision.existing is not None:
            memory_store.update(decision.existing.reinforced(moment), application_context)
            self._logger.debug("Reinforced existing memory: %s", decision.existing.content)
            return decision

        if decision.action is ConsolidationAction.SUPERSEDE and decision.existing is not None:
            memory_store.forget(decision.existing.memory_id, application_context)
            memory_store.remember(candidate, application_context)
            self._logger.info(
                "Superseded %r with %r", decision.existing.content, candidate.content
            )
            return decision

        memory_store.remember(candidate, application_context)
        return decision

    def prune(
        self,
        application_context: ApplicationContext,
        *,
        older_than_days: float = 90.0,
        max_importance: int = 4,
        now: datetime | None = None,
    ) -> tuple[Memory, ...]:
        """Delete memories that have proven worthless, and return what was deleted.

        A memory is prunable only when *every* one of these holds: it is
        not pinned, its importance is at or below `max_importance`, it
        has never been recalled (`access_count == 0`), and it is older
        than `older_than_days`. Requiring all four is what makes this
        safe to offer at all — anything the user deliberately committed,
        rated important, or that has ever actually proven useful is out
        of reach by construction.

        Never called automatically. Deleting memories is exactly the kind
        of thing that must be asked for, so this runs only when invoked
        (`MemoryTool`'s `prune`, itself behind `ConfirmationHook`).
        """
        moment = now or utc_now()
        cutoff = moment - timedelta(days=older_than_days)
        memory_store = application_context.memory

        doomed = tuple(
            memory
            for memory in memory_store.list()
            if not memory.pinned
            and memory.importance <= max_importance
            and memory.access_count == 0
            and memory.created_at < cutoff
        )
        for memory in doomed:
            memory_store.forget(memory.memory_id, application_context)
        if doomed:
            self._logger.info("Pruned %d memories.", len(doomed))
        return doomed

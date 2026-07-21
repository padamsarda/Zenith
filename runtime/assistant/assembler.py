"""AssistantContextAssembler: composes the provider's brief deterministically."""

from __future__ import annotations

from typing import TYPE_CHECKING

from runtime.capabilities.catalog import build_catalog
from runtime.exceptions import RequestValidationError
from runtime.memory.recall import MemoryRecaller, render_memories
from runtime.providers.base import TurnBrief
from shared.utils.time_utils import utc_now

if TYPE_CHECKING:
    from runtime.assistant.request import AssistantRequest
    from runtime.capabilities.skill import Skill
    from runtime.context import ApplicationContext
    from runtime.conversation.conversation import Conversation


class AssistantContextAssembler:
    """Builds the `TurnBrief` a provider receives for each turn.

    The Engineering Manager's context-assembly principle (ADR 0010)
    applied to the assistant: a brief is composed from durable state —
    the conversation's messages, the current capability catalog, active
    skills' instructions, and the memories relevant to what was just
    asked — at the moment it is needed, and nothing is cached or stored.
    Recomposing a brief from the same state yields the same brief, so
    context can never go stale and survives restarts by construction once
    conversations are durable.

    Memory is recalled here, on every turn, rather than through a tool
    the model chooses to call: what Zeni already knows should simply be
    present when it answers, not something it must first think to look up
    (ADR 0027).
    """

    def __init__(self, recaller: MemoryRecaller | None = None) -> None:
        """Create an assembler.

        Args:
            recaller: How memories are recalled into each brief. Defaults
                to a `MemoryRecaller` with the standard retrieval policy.
        """
        self._recaller = recaller or MemoryRecaller()

    def assemble(
        self,
        request: AssistantRequest,
        conversation: Conversation,
        application_context: ApplicationContext,
    ) -> TurnBrief:
        """Compose the brief for the next provider turn serving `request`.

        Raises:
            RequestValidationError: If `request.metadata["skills"]` is
                present but not a list of skill IDs.
            SkillNotFoundError: If a skill named by the request is not
                registered.
        """
        catalog = build_catalog(application_context.tools, application_context.skills)
        instructions = self._compose_instructions(request, application_context)
        return TurnBrief(
            conversation_id=conversation.conversation_id,
            messages=conversation.messages,
            instructions=instructions,
            catalog=catalog,
            metadata=dict(request.metadata),
        )

    def _active_skills(
        self, request: AssistantRequest, application_context: ApplicationContext
    ) -> list[Skill]:
        """Resolve the skills active for `request`, ordered by skill ID.

        A skill is active if the request names it in
        `metadata["skills"]` or its own `applies_to(request)` opts in.
        """
        named = request.metadata.get("skills", [])
        if not isinstance(named, (list, tuple)):
            raise RequestValidationError(
                f"Request metadata 'skills' must be a list of skill IDs, got {named!r}"
            )
        active: dict[str, Skill] = {
            skill_id: application_context.skills.get(skill_id) for skill_id in named
        }
        for skill in application_context.skills.list():
            if skill.skill_id not in active and skill.applies_to(request):
                active[skill.skill_id] = skill
        return [active[skill_id] for skill_id in sorted(active)]

    def _compose_instructions(
        self, request: AssistantRequest, application_context: ApplicationContext
    ) -> str | None:
        """Join recalled memories and active skills into one brief section, or None.

        Memories come first: they are context the model reads before
        deciding anything, where a skill is instruction about how to act.
        """
        sections: list[str] = []

        now = utc_now()
        recalled = self._recaller.recall(request.text, application_context, now=now)
        remembered = render_memories(recalled, now)
        if remembered is not None:
            sections.append(remembered)

        sections.extend(
            f"[Skill: {skill.name}]\n{skill.instructions(request)}"
            for skill in self._active_skills(request, application_context)
        )
        return "\n\n".join(sections) if sections else None

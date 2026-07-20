"""ScriptedProvider: the reference implementation and universal test double."""

from __future__ import annotations

from collections import deque

from runtime.exceptions import AssistantProviderError
from runtime.providers.base import AssistantProvider, AssistantTurn, TurnBrief


class ScriptedProvider(AssistantProvider):
    """Plays back a fixed sequence of turns, one per `generate_turn` call.

    The assistant-side counterpart of the Engineering Manager's
    `InMemoryProvider`: tests script exactly the turns a scenario needs
    (text, tool calls, or both) and assert on the briefs the pipeline
    composed, which `briefs` records in order. Running out of scripted
    turns raises `AssistantProviderError` — the honest-failure behavior
    the contract requires, which conveniently also exercises the
    engine's failure path.
    """

    def __init__(
        self, turns: list[AssistantTurn] | None = None, provider_id: str = "scripted"
    ) -> None:
        self._provider_id = provider_id
        self._turns: deque[AssistantTurn] = deque(turns or [])
        self.briefs: list[TurnBrief] = []

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def name(self) -> str:
        return "Scripted"

    def add_turn(self, turn: AssistantTurn) -> None:
        """Append `turn` to the script."""
        self._turns.append(turn)

    def generate_turn(self, brief: TurnBrief) -> AssistantTurn:
        """Record `brief` and return the next scripted turn.

        Raises:
            AssistantProviderError: If the script is exhausted.
        """
        self.briefs.append(brief)
        if not self._turns:
            raise AssistantProviderError(
                f"ScriptedProvider '{self._provider_id}' has no turns left."
            )
        return self._turns.popleft()

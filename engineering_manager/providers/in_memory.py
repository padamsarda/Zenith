"""InMemoryProvider: the deterministic reference implementation of Provider.

Exists for two real purposes — it is the test double every orchestration
test runs against, and it is the executable specification of the
`Provider` contract for anyone writing a real integration. It performs
no I/O: sessions are records in a dict, and tests script what
`check_session` reports via `script_status`.
"""

from __future__ import annotations

import json

from engineering_manager.exceptions import ProviderSessionError
from engineering_manager.providers.base import (
    Provider,
    ProviderSessionState,
    ProviderSessionStatus,
    SessionHandle,
    SessionSpec,
)

DEFAULT_PROVIDER_ID = "in-memory"

# Mirrors what `PlanningSessionRunner` puts on a planning session's spec.
PLANNING_PURPOSE = "planning"
PLANNING_TITLE_PREFIX = "Plan: "


class InMemoryProvider(Provider):
    """A Provider whose sessions exist only in memory.

    Every started session begins as `RUNNING`. `resume_session` issues a
    fresh `external_ref` on purpose: real providers may do the same, so
    orchestration code exercised against this implementation is forced
    to handle a handle that changes across a resume.

    `finish_after_checks` makes sessions complete on their own after
    that many `check_session` calls. Tests do not need it — they script
    outcomes precisely — but it lets the full workflow (`workflow
    --provider in-memory`) be driven end to end with no external
    process, credentials, or network, so the documented lifecycle is
    something a new contributor can actually run.
    """

    def __init__(
        self,
        provider_id: str = DEFAULT_PROVIDER_ID,
        *,
        finish_after_checks: int | None = None,
    ) -> None:
        self._provider_id = provider_id
        self._statuses: dict[str, ProviderSessionStatus] = {}
        self._specs: dict[str, SessionSpec] = {}
        self._checks: dict[str, int] = {}
        self._finish_after_checks = finish_after_checks
        self._counter = 0

    @property
    def provider_id(self) -> str:
        """Stable identifier for this provider."""
        return self._provider_id

    @property
    def name(self) -> str:
        """Human-readable display name."""
        return "In-Memory Provider"

    @property
    def started_specs(self) -> list[SessionSpec]:
        """Every SessionSpec this provider has been asked to start, in order."""
        return list(self._specs.values())

    def start_session(self, spec: SessionSpec) -> SessionHandle:
        """Record `spec` and return a handle to a RUNNING in-memory session."""
        self._counter += 1
        external_ref = f"{self._provider_id}/session-{self._counter}"
        self._specs[external_ref] = spec
        self._statuses[external_ref] = ProviderSessionStatus(
            state=ProviderSessionState.RUNNING
        )
        return SessionHandle(provider_id=self._provider_id, external_ref=external_ref)

    def check_session(self, handle: SessionHandle) -> ProviderSessionStatus:
        """Return the scripted status of the session behind `handle`.

        With `finish_after_checks` set, a session nobody has scripted
        finishes on its own once it has been checked that many times.
        A scripted status always wins, so tests that drive this provider
        explicitly are unaffected.

        Raises:
            ProviderSessionError: If `handle` is unknown to this provider.
        """
        status = self._statuses.get(handle.external_ref) or self._unknown(handle)
        if self._finish_after_checks is None or status.state is not ProviderSessionState.RUNNING:
            return status
        checks = self._checks.get(handle.external_ref, 0) + 1
        self._checks[handle.external_ref] = checks
        if checks < self._finish_after_checks:
            return status
        finished = ProviderSessionStatus(
            state=ProviderSessionState.FINISHED,
            detail=_simulated_detail(self._specs[handle.external_ref], checks),
        )
        self._statuses[handle.external_ref] = finished
        return finished

    def resume_session(self, handle: SessionHandle) -> SessionHandle:
        """Resume a session under a deliberately fresh external_ref.

        Raises:
            ProviderSessionError: If `handle` is unknown to this provider.
        """
        if handle.external_ref not in self._statuses:
            self._unknown(handle)
        self._counter += 1
        new_ref = f"{handle.external_ref}/resumed-{self._counter}"
        self._specs[new_ref] = self._specs.pop(handle.external_ref)
        del self._statuses[handle.external_ref]
        self._checks.pop(handle.external_ref, None)
        self._statuses[new_ref] = ProviderSessionStatus(state=ProviderSessionState.RUNNING)
        return SessionHandle(provider_id=self._provider_id, external_ref=new_ref)

    def stop_session(self, handle: SessionHandle) -> None:
        """Mark the session behind `handle` as FINISHED.

        Raises:
            ProviderSessionError: If `handle` is unknown to this provider.
        """
        if handle.external_ref not in self._statuses:
            self._unknown(handle)
        self._statuses[handle.external_ref] = ProviderSessionStatus(
            state=ProviderSessionState.FINISHED
        )

    def script_status(self, handle: SessionHandle, status: ProviderSessionStatus) -> None:
        """Set what `check_session` reports for the session behind `handle`.

        Raises:
            ProviderSessionError: If `handle` is unknown to this provider.
        """
        if handle.external_ref not in self._statuses:
            self._unknown(handle)
        self._statuses[handle.external_ref] = status

    def _unknown(self, handle: SessionHandle) -> ProviderSessionStatus:
        """Raise the standard error for a handle this provider doesn't know."""
        raise ProviderSessionError(
            f"Provider '{self._provider_id}' has no session {handle.external_ref!r}."
        )


def _simulated_detail(spec: SessionSpec, checks: int) -> str:
    """Compose the output a self-finishing session reports.

    A planning session (`metadata["purpose"] == "planning"`, set by
    `PlanningSessionRunner`) must answer in the JSON decomposition
    format `parse_decomposition` reads, or the simulated workflow would
    stop at its first step. The three-task chain below is deliberately
    dependent rather than flat, so a simulated run still exercises
    dependency waves, ordering, and the graph — the parts most worth
    seeing work.
    """
    if spec.metadata.get("purpose") != PLANNING_PURPOSE:
        return f"Simulated completion of {spec.task.title!r} after {checks} check(s)."
    goal = spec.task.title.removeprefix(PLANNING_TITLE_PREFIX)
    return json.dumps(
        [
            {
                "title": f"Investigate: {goal}",
                "description": "Survey the affected code and record the approach.",
                "priority": 2,
            },
            {
                "title": f"Implement: {goal}",
                "description": "Make the change the investigation settled on.",
                "priority": 1,
                "depends_on": [0],
            },
            {
                "title": f"Verify: {goal}",
                "description": "Cover the change with tests and update the docs.",
                "priority": 0,
                "depends_on": [1],
            },
        ]
    )

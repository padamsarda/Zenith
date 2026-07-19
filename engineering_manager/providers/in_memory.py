"""InMemoryProvider: the deterministic reference implementation of Provider.

Exists for two real purposes — it is the test double every orchestration
test runs against, and it is the executable specification of the
`Provider` contract for anyone writing a real integration. It performs
no I/O: sessions are records in a dict, and tests script what
`check_session` reports via `script_status`.
"""

from __future__ import annotations

from engineering_manager.exceptions import ProviderSessionError
from engineering_manager.providers.base import (
    Provider,
    ProviderSessionState,
    ProviderSessionStatus,
    SessionHandle,
    SessionSpec,
)

DEFAULT_PROVIDER_ID = "in-memory"


class InMemoryProvider(Provider):
    """A Provider whose sessions exist only in memory.

    Every started session begins as `RUNNING`. `resume_session` issues a
    fresh `external_ref` on purpose: real providers may do the same, so
    orchestration code exercised against this implementation is forced
    to handle a handle that changes across a resume.
    """

    def __init__(self, provider_id: str = DEFAULT_PROVIDER_ID) -> None:
        self._provider_id = provider_id
        self._statuses: dict[str, ProviderSessionStatus] = {}
        self._specs: dict[str, SessionSpec] = {}
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

        Raises:
            ProviderSessionError: If `handle` is unknown to this provider.
        """
        return self._statuses.get(handle.external_ref) or self._unknown(handle)

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

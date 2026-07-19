"""Provider: the abstract contract every AI provider integration implements.

This is the seam that keeps orchestration provider-agnostic. The
orchestrator never talks to Claude, Gemini, Codex, or any other service
directly — it only ever holds a `Provider` and speaks this small,
session-oriented vocabulary: start work, check on it, resume it after an
interruption, stop it. Anything provider-specific (APIs, CLIs,
credentials, prompt formats) lives inside a concrete implementation.

The contract is deliberately minimal and synchronous: the orchestrator
polls via `check_session` rather than being called back. Providers that
are internally asynchronous adapt to this surface. Extending the
vocabulary (streaming output, richer capability discovery, push
notifications) is expected to happen additively as real integrations
demand it — see `docs/engineering_manager.md`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from engineering_manager.domain.project import Project
    from engineering_manager.domain.task import Task


@dataclass(frozen=True)
class SessionSpec:
    """Everything a provider needs to begin work on a task.

    `instructions` is the work description handed to the provider (for
    v1, derived from the task's title and description). `metadata`
    carries provider-specific options (model parameters, sandbox flags,
    workspace hints) without the core contract having to know about
    them — the same extension pattern `Command.metadata` uses.
    """

    session_id: UUID
    project: Project
    task: Task
    account_id: str
    model: str | None = None
    instructions: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SessionHandle:
    """A provider-side reference to a running session.

    `external_ref` is opaque to the orchestrator: a conversation ID, a
    process ID, a URL — whatever the provider can later use to check,
    resume, or stop the session it refers to.
    """

    provider_id: str
    external_ref: str


class ProviderSessionState(Enum):
    """A provider's view of one of its sessions.

    `LIMIT_REACHED` is distinct from `FAILED` because it is the one
    interruption the orchestrator is expected to recover from
    automatically — wait until the limit resets, then resume. This
    mirrors the real behavior the `engineering_tools/watchdog` utility
    was built to handle manually.
    """

    RUNNING = auto()
    AWAITING_INPUT = auto()
    LIMIT_REACHED = auto()
    FINISHED = auto()
    FAILED = auto()


@dataclass(frozen=True)
class ProviderSessionStatus:
    """What a provider reports when asked about a session.

    `resume_at` is only meaningful with `LIMIT_REACHED`: the moment the
    provider expects the session to become resumable, if known.
    """

    state: ProviderSessionState
    detail: str | None = None
    resume_at: datetime | None = None


class Provider(ABC):
    """Base class for every AI provider integration.

    Implementations must be honest about failure: any operation that
    cannot be carried out raises `ProviderSessionError` rather than
    returning a misleading status. A handle returned by `start_session`
    or `resume_session` must carry this provider's own `provider_id`.
    """

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Stable identifier for this provider (e.g. "claude", "gemini")."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable display name."""

    @abstractmethod
    def start_session(self, spec: SessionSpec) -> SessionHandle:
        """Begin work described by `spec` and return a handle to it.

        Raises:
            ProviderSessionError: If the session cannot be started.
        """

    @abstractmethod
    def check_session(self, handle: SessionHandle) -> ProviderSessionStatus:
        """Report the current state of the session behind `handle`.

        Raises:
            ProviderSessionError: If `handle` is unknown to this provider.
        """

    @abstractmethod
    def resume_session(self, handle: SessionHandle) -> SessionHandle:
        """Resume an interrupted session, returning its (possibly new) handle.

        Raises:
            ProviderSessionError: If `handle` is unknown or the session
                cannot be resumed.
        """

    @abstractmethod
    def stop_session(self, handle: SessionHandle) -> None:
        """Stop the session behind `handle`.

        Raises:
            ProviderSessionError: If `handle` is unknown to this provider.
        """

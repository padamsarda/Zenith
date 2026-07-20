"""Session: one engagement of a provider account on a task."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from engineering_manager.domain.states import TERMINAL_SESSION_STATUSES, SessionStatus
from engineering_manager.domain.validation import (
    validate_resume_at,
    validate_session_status_transition,
)
from engineering_manager.exceptions import DomainValidationError
from shared.utils.time_utils import utc_now
from shared.utils.uuid_utils import generate_id


@dataclass(frozen=True)
class Session:
    """A continuous stretch of provider work on one task.

    `external_ref` is the provider-side reference (a conversation ID, a
    process handle, a workspace URL — whatever the provider uses) that
    lets an `INTERRUPTED` session be resumed instead of started over.
    It may be updated via `update_external_ref` because resuming can
    yield a fresh provider-side reference.

    `resume_at` is only meaningful while `INTERRUPTED`: it is the
    moment the execution engine may resume the session automatically.
    An interrupted session with no `resume_at` is waiting on a human
    (for example, the provider reported `AWAITING_INPUT`) and is never
    auto-resumed.

    Like `Command`, a `Session` is frozen and mutated only through
    validated methods: `transition_to` for `status`,
    `update_external_ref` for the provider reference, `set_resume_at`
    for the auto-resume moment, and `close` to stamp
    `ended_at`/`summary` once the session has reached a terminal
    status. Construction does not validate; that happens at the
    framework boundary, in
    `engineering_manager.domain.validation.validate_session`.
    """

    task_id: UUID
    project_id: str
    provider_id: str
    account_id: str
    model: str | None = None
    external_ref: str | None = None
    summary: str | None = None
    resume_at: datetime | None = None
    session_id: UUID = field(default_factory=generate_id)
    started_at: datetime = field(default_factory=utc_now)
    ended_at: datetime | None = None
    status: SessionStatus = SessionStatus.ACTIVE

    def transition_to(self, new_status: SessionStatus) -> None:
        """Move this session to `new_status`.

        Raises:
            DomainValidationError: If the transition from the current
                status to `new_status` is not permitted.
        """
        validate_session_status_transition(self.status, new_status)
        object.__setattr__(self, "status", new_status)

    def update_external_ref(self, external_ref: str) -> None:
        """Record the provider-side reference for this session.

        Raises:
            DomainValidationError: If `external_ref` is not a string, or
                the session has already ended.
        """
        if not isinstance(external_ref, str):
            raise DomainValidationError(
                f"Session external_ref must be a str, got {type(external_ref).__name__}"
            )
        if self.ended_at is not None:
            raise DomainValidationError(
                f"Session {self.session_id} has ended; external_ref can no longer change."
            )
        object.__setattr__(self, "external_ref", external_ref)

    def set_resume_at(self, resume_at: datetime | None) -> None:
        """Set (or clear, with None) when this session may auto-resume.

        Raises:
            DomainValidationError: If `resume_at` is not a datetime or
                None, or the session has already ended.
        """
        validate_resume_at(resume_at)
        if self.ended_at is not None:
            raise DomainValidationError(
                f"Session {self.session_id} has ended; resume_at can no longer change."
            )
        object.__setattr__(self, "resume_at", resume_at)

    def close(self, summary: str | None = None) -> None:
        """Stamp `ended_at` (and optionally `summary`) on a finished session.

        Raises:
            DomainValidationError: If the session is not in a terminal
                status, or has already been closed.
        """
        if self.status not in TERMINAL_SESSION_STATUSES:
            raise DomainValidationError(
                f"Session {self.session_id} cannot close while {self.status.name}."
            )
        if self.ended_at is not None:
            raise DomainValidationError(f"Session {self.session_id} is already closed.")
        object.__setattr__(self, "ended_at", utc_now())
        if summary is not None:
            object.__setattr__(self, "summary", summary)

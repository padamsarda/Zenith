"""AssistantRequest: an immutable description of one user request."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from runtime.assistant.status import RequestStatus
from runtime.assistant.validation import validate_status_transition
from shared.utils.time_utils import utc_now
from shared.utils.uuid_utils import generate_id


@dataclass(frozen=True)
class AssistantRequest:
    """One user request for the assistant to serve.

    Every field is fixed at creation except `status`, which may only
    change through `transition_to` — the exact pattern `Command`
    follows. Construction does not validate `text` or `metadata`; that
    happens at the pipeline boundary, in
    `runtime.assistant.validation.validate_request`.

    `metadata` is the request-scoped extension point. Two keys are
    understood by the pipeline itself: `"provider"` (a provider ID
    overriding the configured default) and `"skills"` (a list of skill
    IDs to activate for this request).
    """

    conversation_id: UUID
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    request_id: UUID = field(default_factory=generate_id)
    created_at: datetime = field(default_factory=utc_now)
    status: RequestStatus = RequestStatus.RECEIVED

    def transition_to(self, new_status: RequestStatus) -> None:
        """Move this request to `new_status`.

        Raises:
            RequestValidationError: If the transition from the current
                status to `new_status` is not permitted.
        """
        validate_status_transition(self.status, new_status)
        object.__setattr__(self, "status", new_status)

"""Project: a repository under Engineering Manager management."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from engineering_manager.domain.states import ProjectStatus
from engineering_manager.domain.validation import validate_project_status_transition
from shared.utils.time_utils import utc_now


@dataclass(frozen=True)
class Project:
    """A codebase the Engineering Manager coordinates work on.

    `project_id` is an author-chosen, stable slug (like
    `PluginManifest.plugin_id`) — it is how the same project is
    recognized run over run, not a per-instance identifier. Every field
    is fixed at creation except `status`, which may only change through
    `transition_to`. Construction does not validate; that happens at the
    framework boundary, in
    `engineering_manager.domain.validation.validate_project`, mirroring
    how `Config`, `Command`, and `PluginManifest` are validated
    separately from construction.
    """

    project_id: str
    name: str
    root_path: Path
    description: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    status: ProjectStatus = ProjectStatus.ACTIVE

    def transition_to(self, new_status: ProjectStatus) -> None:
        """Move this project to `new_status`.

        Raises:
            DomainValidationError: If the transition from the current
                status to `new_status` is not permitted.
        """
        validate_project_status_transition(self.status, new_status)
        object.__setattr__(self, "status", new_status)

"""Exception hierarchy for the Engineering Manager.

Mirrors the structure of `runtime.exceptions`: every class roots at
`shared.exceptions.ZenithError`, grouped by subsystem (domain, provider
abstraction, persistence, orchestration) so callers can catch at
whatever granularity they need.
"""

from __future__ import annotations

from shared.exceptions import ZenithError


class EngineeringManagerError(ZenithError):
    """Base class for all Engineering Manager errors."""


class DomainValidationError(EngineeringManagerError):
    """Raised when a domain object fails validation.

    Covers structural issues (identifiers, titles, priorities,
    dependency sets) and invalid lifecycle state transitions for
    projects, tasks, and sessions.
    """


class ProviderError(EngineeringManagerError):
    """Base class for provider abstraction errors."""


class ProviderNotFoundError(ProviderError):
    """Raised when looking up or unregistering a provider ID that isn't
    registered.
    """


class ProviderAlreadyRegisteredError(ProviderError):
    """Raised when registering a provider ID that is already in use."""


class ProviderSessionError(ProviderError):
    """Raised by a Provider when it cannot start, check, resume, or stop
    a session it is asked to manage.
    """


class StoreError(EngineeringManagerError):
    """Base class for persistence errors."""


class ProjectNotFoundError(StoreError):
    """Raised when a project ID does not exist in the store."""


class TaskNotFoundError(StoreError):
    """Raised when a task ID does not exist in the store."""


class SessionNotFoundError(StoreError):
    """Raised when a session ID does not exist in the store."""


class AccountNotFoundError(StoreError):
    """Raised when a (provider_id, account_id) pair does not exist in
    the store.
    """


class DuplicateEntityError(StoreError):
    """Raised when adding an entity whose ID already exists in the store."""


class OrchestrationError(EngineeringManagerError):
    """Raised when a dispatch or session-lifecycle operation cannot be
    carried out — for example, dispatching a task that is not eligible,
    or resuming a session that has no external reference.
    """

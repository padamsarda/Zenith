"""AssignmentPolicy: the seam for deciding which account runs a task.

Replacing the human's "which AI should do this?" judgment is a policy
decision that will keep evolving (cost, capability, past performance,
rate limits), so it is isolated behind one small abstract class instead
of being buried in the dispatcher. The dispatcher supplies the facts —
the task, the usable accounts, and the currently open sessions — and
the policy only chooses.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence

from engineering_manager.domain.account import ProviderAccount
from engineering_manager.domain.session import Session
from engineering_manager.domain.task import Task
from engineering_manager.exceptions import OrchestrationError


class AssignmentPolicy(ABC):
    """Chooses the provider account that should work on a task."""

    @abstractmethod
    def choose_account(
        self,
        task: Task,
        accounts: Sequence[ProviderAccount],
        open_sessions: Sequence[Session],
    ) -> ProviderAccount | None:
        """Return the account `task` should run on, or None if none can.

        Args:
            task: The task to be dispatched.
            accounts: Accounts whose provider is registered — already
                filtered by the dispatcher, so every entry is usable.
            open_sessions: Sessions currently ACTIVE or INTERRUPTED,
                across all accounts.
        """


class FirstAvailablePolicy(AssignmentPolicy):
    """Picks the first account that has no open session.

    One open session per account is a deliberately conservative default:
    it mirrors how provider session limits behave in practice. Smarter
    policies (per-provider concurrency, capability matching, cost
    awareness) replace this class without touching the dispatcher.
    """

    def choose_account(
        self,
        task: Task,
        accounts: Sequence[ProviderAccount],
        open_sessions: Sequence[Session],
    ) -> ProviderAccount | None:
        """Return the first account not occupied by an open session."""
        busy = {(session.provider_id, session.account_id) for session in open_sessions}
        for account in accounts:
            if (account.provider_id, account.account_id) not in busy:
                return account
        return None


class ConcurrencyLimitedPolicy(AssignmentPolicy):
    """Picks the first account whose *provider* is under its concurrency limit.

    Generalizes `FirstAvailablePolicy`'s "one open session per account"
    (correct for providers where an account is a single exclusive
    session, like an interactive CLI login) to a configurable cap per
    `provider_id`, counted across every account on that provider — some
    providers can genuinely run several sessions at once (separate API
    keys, separate working directories), others exactly one. A
    `provider_id` absent from `limits` falls back to `default_limit`.

    Accounts are still tried in the order given, so the caller's
    ordering (e.g. preferred account first) is preserved; this policy
    only changes *whether* an account is skipped, not the order.
    """

    def __init__(
        self, limits: Mapping[str, int] | None = None, *, default_limit: int = 1
    ) -> None:
        """Create the policy.

        Args:
            limits: Per-`provider_id` concurrency caps. A provider not
                named here uses `default_limit`.
            default_limit: The concurrency cap for any provider not in
                `limits`.

        Raises:
            OrchestrationError: If `default_limit` or any value in
                `limits` is not a positive int.
        """
        _validate_positive_int("default_limit", default_limit)
        for provider_id, limit in (limits or {}).items():
            _validate_positive_int(f"limits[{provider_id!r}]", limit)
        self._limits = dict(limits or {})
        self._default_limit = default_limit

    def choose_account(
        self,
        task: Task,
        accounts: Sequence[ProviderAccount],
        open_sessions: Sequence[Session],
    ) -> ProviderAccount | None:
        """Return the first account whose provider has spare concurrency."""
        open_counts: dict[str, int] = {}
        for session in open_sessions:
            open_counts[session.provider_id] = open_counts.get(session.provider_id, 0) + 1
        for account in accounts:
            limit = self._limits.get(account.provider_id, self._default_limit)
            if open_counts.get(account.provider_id, 0) < limit:
                return account
        return None


def _validate_positive_int(label: str, value: object) -> None:
    """Raise OrchestrationError unless `value` is a positive int (not bool)."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise OrchestrationError(f"{label} must be an int, got {value!r}")
    if value < 1:
        raise OrchestrationError(f"{label} must be at least 1, got {value}")

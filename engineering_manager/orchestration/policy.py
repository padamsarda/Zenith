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
from collections.abc import Sequence

from engineering_manager.domain.account import ProviderAccount
from engineering_manager.domain.session import Session
from engineering_manager.domain.task import Task


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

"""ProviderAccount: a usable account on an AI provider."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderAccount:
    """One account on one provider — an execution resource.

    Purely declarative, like `PluginManifest`: the pair
    `(provider_id, account_id)` identifies the account; `label` is an
    optional human-readable note (e.g. "personal", "work"). Credentials
    are deliberately not stored here or anywhere in the Engineering
    Manager — each provider implementation resolves its own credentials
    (environment, keychain, CLI login) from the account ID.
    Construction does not validate; that happens at the framework
    boundary, in `engineering_manager.domain.validation.validate_account`.
    """

    provider_id: str
    account_id: str
    label: str | None = None

"""AssistantProviderRegistry: the assistant providers available to the runtime."""

from __future__ import annotations

from typing import TYPE_CHECKING

from runtime.exceptions import (
    AssistantProviderNotFoundError,
    AssistantProviderRegistrationError,
)
from shared.exceptions import ValidationError
from shared.utils.text_utils import is_blank_or_padded

if TYPE_CHECKING:
    from runtime.providers.base import AssistantProvider


class AssistantProviderRegistry:
    """Stores and retrieves assistant providers by their `provider_id`.

    Mirrors the Engineering Manager's `ProviderRegistry` and the
    runtime's `ServiceRegistry`: explicit `register`/`get`/`has`/`list`,
    no discovery, no magic, and — like both — no event emission;
    providers are wired once at startup, not registered and unregistered
    as the runtime runs.
    """

    def __init__(self) -> None:
        self._providers: dict[str, AssistantProvider] = {}

    def register(self, provider: AssistantProvider) -> None:
        """Register `provider` under its `provider_id`.

        Raises:
            ValidationError: If `provider.provider_id` is not a usable
                identifier.
            AssistantProviderRegistrationError: If the ID is already
                registered.
        """
        if is_blank_or_padded(provider.provider_id):
            raise ValidationError(f"Invalid provider identifier: {provider.provider_id!r}")
        if provider.provider_id in self._providers:
            raise AssistantProviderRegistrationError(
                f"Assistant provider '{provider.provider_id}' is already registered."
            )
        self._providers[provider.provider_id] = provider

    def get(self, provider_id: str) -> AssistantProvider:
        """Return the provider registered under `provider_id`.

        Raises:
            AssistantProviderNotFoundError: If `provider_id` is not registered.
        """
        try:
            return self._providers[provider_id]
        except KeyError:
            raise AssistantProviderNotFoundError(
                f"Assistant provider '{provider_id}' is not registered."
            ) from None

    def has(self, provider_id: str) -> bool:
        """Return True if a provider is registered under `provider_id`."""
        return provider_id in self._providers

    def list(self) -> list[AssistantProvider]:
        """Return a snapshot list of registered providers, in registration order."""
        return list(self._providers.values())

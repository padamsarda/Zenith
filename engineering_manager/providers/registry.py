"""ProviderRegistry: the lookup table of available provider integrations."""

from __future__ import annotations

from engineering_manager.domain.validation import validate_identifier
from engineering_manager.exceptions import (
    ProviderAlreadyRegisteredError,
    ProviderNotFoundError,
)
from engineering_manager.providers.base import Provider


class ProviderRegistry:
    """Stores Provider implementations by ID.

    Mirrors `runtime.registry.ServiceRegistry`: a simple, explicit
    lookup table with no construction, wiring, or auto-discovery.
    Providers are interchangeable behind their IDs — orchestration code
    resolves `session.provider_id` through this registry and never
    imports a concrete provider.
    """

    def __init__(self) -> None:
        self._providers: dict[str, Provider] = {}

    def register(self, provider: Provider) -> None:
        """Register `provider` under its own `provider_id`.

        Raises:
            DomainValidationError: If the provider's ID is not a valid
                identifier.
            ProviderAlreadyRegisteredError: If the ID is already taken.
        """
        validate_identifier(provider.provider_id, kind="provider id")
        if provider.provider_id in self._providers:
            raise ProviderAlreadyRegisteredError(
                f"Provider '{provider.provider_id}' is already registered."
            )
        self._providers[provider.provider_id] = provider

    def unregister(self, provider_id: str) -> None:
        """Remove the provider registered under `provider_id`.

        Raises:
            ProviderNotFoundError: If `provider_id` is not registered.
        """
        if provider_id not in self._providers:
            raise ProviderNotFoundError(f"Provider '{provider_id}' is not registered.")
        del self._providers[provider_id]

    def get(self, provider_id: str) -> Provider:
        """Return the provider registered under `provider_id`.

        Raises:
            ProviderNotFoundError: If `provider_id` is not registered.
        """
        try:
            return self._providers[provider_id]
        except KeyError:
            raise ProviderNotFoundError(
                f"Provider '{provider_id}' is not registered."
            ) from None

    def has(self, provider_id: str) -> bool:
        """Return True if a provider is registered under `provider_id`."""
        return provider_id in self._providers

    def list(self) -> list[Provider]:
        """Return a snapshot list of all registered providers."""
        return list(self._providers.values())

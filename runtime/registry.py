"""A lightweight, named registry for shared service instances.

`ServiceRegistry` is intentionally simple: it is not a dependency-injection
framework. It does not construct services, resolve constructor arguments,
or perform any wiring. It only lets one part of the application register
an already-built object under a name, and another part look it up later.
"""

from __future__ import annotations

from runtime.exceptions import ServiceAlreadyRegisteredError, ServiceNotFoundError
from runtime.validation import validate_service_name


class ServiceRegistry:
    """Stores and retrieves shared service objects by name."""

    def __init__(self) -> None:
        self._services: dict[str, object] = {}

    def register(self, name: str, service: object) -> None:
        """Register `service` under `name`.

        Args:
            name: A non-empty, non-whitespace-padded identifier.
            service: The object to store.

        Raises:
            ValidationError: If `name` is not a valid service name.
            ServiceAlreadyRegisteredError: If `name` is already registered.
        """
        validate_service_name(name)
        if name in self._services:
            raise ServiceAlreadyRegisteredError(
                f"Service '{name}' is already registered."
            )
        self._services[name] = service

    def unregister(self, name: str) -> None:
        """Remove the service registered under `name`.

        Raises:
            ServiceNotFoundError: If `name` is not registered.
        """
        if name not in self._services:
            raise ServiceNotFoundError(f"Service '{name}' is not registered.")
        del self._services[name]

    def get(self, name: str) -> object:
        """Return the service registered under `name`.

        Raises:
            ServiceNotFoundError: If `name` is not registered.
        """
        try:
            return self._services[name]
        except KeyError:
            raise ServiceNotFoundError(f"Service '{name}' is not registered.") from None

    def has(self, name: str) -> bool:
        """Return True if a service is registered under `name`."""
        return name in self._services

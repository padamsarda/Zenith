"""Concrete events emitted by the plugin framework."""

from __future__ import annotations

from dataclasses import dataclass

from runtime.events.event import Event


@dataclass(frozen=True)
class PluginRegistered(Event):
    """Emitted when a Plugin is successfully registered via PluginRegistry.register."""


@dataclass(frozen=True)
class PluginEnabled(Event):
    """Emitted when a Plugin transitions to ENABLED via PluginRegistry.enable."""


@dataclass(frozen=True)
class PluginDisabled(Event):
    """Emitted when a Plugin transitions to DISABLED via PluginRegistry.disable."""


@dataclass(frozen=True)
class PluginUnregistered(Event):
    """Emitted when a Plugin is successfully removed via PluginRegistry.unregister."""


@dataclass(frozen=True)
class PluginFailed(Event):
    """Emitted when a Plugin's hook raises during registration or unregistration."""

"""PluginContext: what a Plugin's lifecycle hooks can see."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from runtime.plugins.manifest import PluginManifest

if TYPE_CHECKING:
    from runtime.context import ApplicationContext
    from runtime.plugins.registry import PluginRegistry


@dataclass(frozen=True)
class PluginContext:
    """Bundles what a plugin's `initialize`/`shutdown` hooks need.

    Built fresh by `PluginRegistry` for each `register`/`unregister`
    call — never shared across plugins, and holds no global state.
    """

    application_context: ApplicationContext
    manifest: PluginManifest
    registry: PluginRegistry

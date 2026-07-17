"""Plugin: abstract base class every Zenith plugin implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from runtime.plugins.manifest import PluginManifest
from runtime.plugins.state import PluginState
from runtime.plugins.validation import validate_state_transition

if TYPE_CHECKING:
    from runtime.plugins.context import PluginContext
    from runtime.plugins.registry import PluginRegistry


class Plugin(ABC):
    """Base class for every Zenith plugin.

    A `Plugin` pairs a fixed `PluginManifest` with a mutable
    `PluginState`. `id`, `name`, `version`, `description`, and `author`
    are read-only, delegating to `manifest`; `state` can only change
    through `transition_to`, which validates the transition first.
    `enabled` is a convenience for `state is PluginState.ENABLED`.

    Subclasses implement the four lifecycle hooks. `PluginRegistry`
    calls them: `initialize` and `register` during
    `PluginRegistry.register`, `unregister` and `shutdown` (in that
    order — undoing registration before undoing setup) during
    `PluginRegistry.unregister`. See `docs/plugins.md` for the full
    sequence.
    """

    def __init__(self, manifest: PluginManifest) -> None:
        self._manifest = manifest
        self._state = PluginState.CREATED

    @property
    def manifest(self) -> PluginManifest:
        """The plugin's fixed metadata."""
        return self._manifest

    @property
    def id(self) -> str:
        """The plugin's unique, author-chosen identifier."""
        return self._manifest.plugin_id

    @property
    def name(self) -> str:
        """The plugin's display name."""
        return self._manifest.name

    @property
    def version(self) -> str:
        """The plugin's version string."""
        return self._manifest.version

    @property
    def description(self) -> str | None:
        """The plugin's optional human-readable description."""
        return self._manifest.description

    @property
    def author(self) -> str | None:
        """The plugin's optional author attribution."""
        return self._manifest.author

    @property
    def state(self) -> PluginState:
        """The plugin's current lifecycle state."""
        return self._state

    @property
    def enabled(self) -> bool:
        """Whether the plugin is currently enabled."""
        return self._state is PluginState.ENABLED

    def transition_to(self, new_state: PluginState) -> None:
        """Move this plugin to `new_state`.

        Raises:
            PluginValidationError: If the transition from the current
                state to `new_state` is not permitted.
        """
        validate_state_transition(self._state, new_state)
        self._state = new_state

    @abstractmethod
    def initialize(self, context: PluginContext) -> None:
        """Set up the plugin's own resources.

        Called by `PluginRegistry.register`, before `register`.
        """

    @abstractmethod
    def shutdown(self, context: PluginContext) -> None:
        """Tear down the plugin's own resources.

        Called by `PluginRegistry.unregister`, after `unregister`.
        """

    @abstractmethod
    def register(self, registry: PluginRegistry) -> None:
        """Perform the plugin's own registration work against `registry`.

        Called by `PluginRegistry.register`, after `initialize`.
        """

    @abstractmethod
    def unregister(self, registry: PluginRegistry) -> None:
        """Reverse `register` against `registry`.

        Called by `PluginRegistry.unregister`, before `shutdown`.
        """

"""PluginRegistry: bookkeeping and lifecycle orchestration for Plugins."""

from __future__ import annotations

from typing import TYPE_CHECKING

from runtime.exceptions import PluginLifecycleError, PluginNotFoundError, PluginRegistrationError
from runtime.plugins.context import PluginContext
from runtime.plugins.events import (
    PluginDisabled,
    PluginEnabled,
    PluginFailed,
    PluginRegistered,
    PluginUnregistered,
)
from runtime.plugins.state import TERMINAL_STATES, PluginState
from runtime.plugins.validation import validate_plugin

if TYPE_CHECKING:
    from runtime.context import ApplicationContext
    from runtime.plugins.plugin import Plugin

SOURCE = "plugin_registry"


class PluginRegistry:
    """Stores Plugins by ID and orchestrates their registration lifecycle.

    Mirrors `ServiceRegistry`'s role as a simple, explicit lookup table,
    extended with the lifecycle-hook invocation and event emission
    plugins additionally need: `register`/`unregister` call a plugin's
    own `initialize`/`register`/`unregister`/`shutdown` hooks and drive
    its `PluginState`; `enable`/`disable` are pure state transitions
    with no hook calls, since `Plugin` exposes no `enable`/`disable`
    hooks. `register`/`unregister`/`enable`/`disable` take the `Plugin`
    object itself (matching `Plugin`'s own hook signatures); `get`/`has`
    take a plugin ID string.
    """

    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}

    def register(self, plugin: Plugin, application_context: ApplicationContext) -> None:
        """Validate, initialize, and store `plugin`.

        Runs, in order: structural validation, a duplicate-ID check,
        `plugin.transition_to(INITIALIZED)` + `plugin.initialize(context)`,
        then `plugin.transition_to(REGISTERED)` + `plugin.register(self)`.
        `plugin` is only stored once every step succeeds — a failed
        registration never leaves a partially registered plugin behind.

        Raises:
            PluginValidationError: If the plugin's manifest is invalid.
            PluginRegistrationError: If a plugin with the same ID is
                already registered.
            PluginLifecycleError: If `initialize` or `register` raises.
        """
        validate_plugin(plugin)
        if self.has(plugin.id):
            raise PluginRegistrationError(f"Plugin '{plugin.id}' is already registered.")

        context = PluginContext(
            application_context=application_context, manifest=plugin.manifest, registry=self
        )

        try:
            plugin.transition_to(PluginState.INITIALIZED)
            plugin.initialize(context)
            plugin.transition_to(PluginState.REGISTERED)
            plugin.register(self)
        except Exception as exc:
            self._fail(plugin, application_context, exc)
            raise PluginLifecycleError(
                f"Plugin '{plugin.id}' failed during registration: {exc}"
            ) from exc

        self._plugins[plugin.id] = plugin
        application_context.events.emit(
            PluginRegistered(source=SOURCE, payload={"plugin_id": plugin.id, "name": plugin.name})
        )

    def unregister(self, plugin: Plugin, application_context: ApplicationContext) -> None:
        """Run `plugin`'s teardown hooks and remove it from the registry.

        Runs, in order: `plugin.unregister(self)`, `plugin.shutdown(context)`,
        `plugin.transition_to(STOPPED)` — the reverse of `register`'s
        order, undoing registration before undoing setup. `plugin` stays
        registered if any step raises.

        Raises:
            PluginNotFoundError: If `plugin.id` is not registered.
            PluginLifecycleError: If `unregister` or `shutdown` raises.
        """
        if not self.has(plugin.id):
            raise PluginNotFoundError(f"Plugin '{plugin.id}' is not registered.")

        context = PluginContext(
            application_context=application_context, manifest=plugin.manifest, registry=self
        )

        try:
            plugin.unregister(self)
            plugin.shutdown(context)
            plugin.transition_to(PluginState.STOPPED)
        except Exception as exc:
            self._fail(plugin, application_context, exc)
            raise PluginLifecycleError(
                f"Plugin '{plugin.id}' failed during unregistration: {exc}"
            ) from exc

        del self._plugins[plugin.id]
        application_context.events.emit(
            PluginUnregistered(
                source=SOURCE, payload={"plugin_id": plugin.id, "name": plugin.name}
            )
        )

    def enable(self, plugin: Plugin, application_context: ApplicationContext) -> None:
        """Transition `plugin` to ENABLED.

        A pure state transition — no lifecycle hook is called, since
        `Plugin` exposes no `enable` hook.

        Raises:
            PluginNotFoundError: If `plugin.id` is not registered.
            PluginValidationError: If `plugin` is not in a state that
                can transition to ENABLED (REGISTERED or DISABLED).
        """
        if not self.has(plugin.id):
            raise PluginNotFoundError(f"Plugin '{plugin.id}' is not registered.")

        plugin.transition_to(PluginState.ENABLED)
        application_context.events.emit(
            PluginEnabled(source=SOURCE, payload={"plugin_id": plugin.id, "name": plugin.name})
        )

    def disable(self, plugin: Plugin, application_context: ApplicationContext) -> None:
        """Transition `plugin` to DISABLED.

        A pure state transition — no lifecycle hook is called, since
        `Plugin` exposes no `disable` hook.

        Raises:
            PluginNotFoundError: If `plugin.id` is not registered.
            PluginValidationError: If `plugin` is not ENABLED.
        """
        if not self.has(plugin.id):
            raise PluginNotFoundError(f"Plugin '{plugin.id}' is not registered.")

        plugin.transition_to(PluginState.DISABLED)
        application_context.events.emit(
            PluginDisabled(source=SOURCE, payload={"plugin_id": plugin.id, "name": plugin.name})
        )

    def get(self, plugin_id: str) -> Plugin:
        """Return the registered plugin with `plugin_id`.

        Raises:
            PluginNotFoundError: If `plugin_id` is not registered.
        """
        try:
            return self._plugins[plugin_id]
        except KeyError:
            raise PluginNotFoundError(f"Plugin '{plugin_id}' is not registered.") from None

    def has(self, plugin_id: str) -> bool:
        """Return True if a plugin is registered under `plugin_id`."""
        return plugin_id in self._plugins

    def list(self) -> list[Plugin]:
        """Return a snapshot list of all registered plugins."""
        return list(self._plugins.values())

    def _fail(
        self, plugin: Plugin, application_context: ApplicationContext, exc: BaseException
    ) -> None:
        """Transition `plugin` to FAILED (if not already terminal) and emit PluginFailed."""
        if plugin.state not in TERMINAL_STATES:
            plugin.transition_to(PluginState.FAILED)
        application_context.events.emit(
            PluginFailed(source=SOURCE, payload={"plugin_id": plugin.id, "reason": str(exc)})
        )

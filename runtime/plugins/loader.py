"""PluginLoader: discovers and imports Plugins from disk into a PluginRegistry."""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from runtime.exceptions import PluginLifecycleError, PluginLoadError, PluginRegistrationError
from runtime.plugins.events import PluginLoadFailed
from runtime.plugins.plugin import Plugin

if TYPE_CHECKING:
    from runtime.context import ApplicationContext
    from runtime.plugins.registry import PluginRegistry

ENTRY_POINT_FILENAME = "plugin.py"
FACTORY_FUNCTION_NAME = "create_plugin"
SOURCE = "plugin_loader"


class PluginLoader:
    """Discovers plugins under a directory and registers them into a PluginRegistry.

    This is the loading strategy `docs/plugins.md` deliberately deferred:
    `PluginRegistry` never discovers or imports plugins itself, only
    stores and drives ones it is handed. Convention over configuration,
    matching the framework's "no magic" rule: each plugin is an
    immediate subdirectory of `plugins_dir` containing a `plugin.py`
    module with a module-level `create_plugin() -> Plugin` function.
    Nothing is a decorator or a metaclass hook — `create_plugin` is
    called explicitly, once, by `load_all`.

    A plugin directory that fails to import, has no `create_plugin`,
    whose factory raises, or whose factory returns something other than
    a `Plugin` is logged and skipped, never raised — one broken plugin
    must not prevent the rest, or the runtime itself, from starting.
    Failures that occur once a `Plugin` object exists (validation,
    lifecycle hooks) are `PluginRegistry.register`'s own concern and
    already emit `PluginFailed`; this loader only additionally emits
    `PluginLoadFailed` for failures before a `Plugin` exists to hand it.
    """

    def __init__(self, plugins_dir: Path, logger: logging.Logger | None = None) -> None:
        """Create a PluginLoader that discovers plugins under `plugins_dir`.

        Args:
            plugins_dir: Directory whose immediate subdirectories are
                candidate plugins. Need not exist — `load_all` then
                discovers nothing.
            logger: Defaults to a module logger.
        """
        self._plugins_dir = plugins_dir
        self._logger = logger or logging.getLogger("zenith.plugins.loader")

    def load_all(
        self, registry: PluginRegistry, application_context: ApplicationContext
    ) -> list[Plugin]:
        """Discover, import, and register every plugin under `plugins_dir`.

        Returns the plugins successfully registered, in directory-name
        order. Never raises for an individual plugin's failure; each is
        logged and, for a pre-registration failure, reported as
        `PluginLoadFailed` on `application_context.events`.
        """
        loaded: list[Plugin] = []
        for entry_point in self._discover():
            plugin = self._load_one(entry_point, application_context)
            if plugin is None:
                continue
            try:
                registry.register(plugin, application_context)
            except (PluginRegistrationError, PluginLifecycleError) as exc:
                self._logger.warning("Plugin at '%s' failed to register: %s", entry_point, exc)
                continue
            loaded.append(plugin)
        return loaded

    def _discover(self) -> list[Path]:
        """Return the sorted `plugin.py` entry points found directly under `plugins_dir`."""
        if not self._plugins_dir.is_dir():
            return []
        return sorted(
            path / ENTRY_POINT_FILENAME
            for path in self._plugins_dir.iterdir()
            if path.is_dir() and (path / ENTRY_POINT_FILENAME).is_file()
        )

    def _load_one(
        self, entry_point: Path, application_context: ApplicationContext
    ) -> Plugin | None:
        """Import `entry_point` and call its `create_plugin` factory.

        Returns None (after logging and emitting `PluginLoadFailed`) if
        the module cannot be imported, has no factory, the factory
        raises, or the factory's return value is not a `Plugin`.
        """
        try:
            plugin = self._build_plugin(entry_point)
        except PluginLoadError as exc:
            self._logger.warning(str(exc))
            application_context.events.emit(
                PluginLoadFailed(
                    source=SOURCE, payload={"path": str(entry_point), "reason": str(exc)}
                )
            )
            return None
        return plugin

    def _build_plugin(self, entry_point: Path) -> Plugin:
        """Import `entry_point` and call its factory, or raise PluginLoadError."""
        module_name = f"zenith_plugins.{entry_point.parent.name}"
        spec = importlib.util.spec_from_file_location(module_name, entry_point)
        if spec is None or spec.loader is None:
            raise PluginLoadError(f"Could not build an import spec for '{entry_point}'.")

        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            raise PluginLoadError(f"Plugin module '{entry_point}' raised on import: {exc}") from exc

        factory = getattr(module, FACTORY_FUNCTION_NAME, None)
        if factory is None:
            raise PluginLoadError(
                f"Plugin module '{entry_point}' has no '{FACTORY_FUNCTION_NAME}' function."
            )

        try:
            plugin = factory()
        except Exception as exc:
            raise PluginLoadError(
                f"Plugin module '{entry_point}' factory raised: {exc}"
            ) from exc

        if not isinstance(plugin, Plugin):
            raise PluginLoadError(
                f"Plugin module '{entry_point}' factory returned {plugin!r}, not a Plugin."
            )
        return plugin

"""Zenith plugins.

Each immediate subdirectory here is a candidate plugin: a `plugin.py`
module exposing a module-level `create_plugin() -> Plugin` factory.
`runtime.plugins.loader.PluginLoader` discovers and imports them by file
path, so nothing in `runtime/` imports this package or any plugin under
it — see `docs/plugins.md`.
"""

from __future__ import annotations

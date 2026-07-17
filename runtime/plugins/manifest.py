"""PluginManifest: immutable, declarative metadata describing a plugin."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PluginManifest:
    """Metadata identifying a plugin — nothing behavioral.

    Every field is fixed at creation; a `PluginManifest` carries no
    lifecycle state of its own (that lives on `Plugin.state`). Unlike
    `Command`, a plugin's ID is author-chosen, not auto-generated: it is
    a stable slug a plugin keeps across every run, not a per-instance
    identifier. Construction does not validate any field; that happens
    at the framework boundary, in
    `runtime.plugins.validation.validate_plugin_manifest`, mirroring how
    `configs.config.Config` and `runtime.commands.command.Command` are
    validated separately from construction.
    """

    plugin_id: str
    name: str
    version: str
    description: str | None = None
    author: str | None = None

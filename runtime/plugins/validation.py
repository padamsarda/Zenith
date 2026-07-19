"""Validation helpers for the plugin framework.

Mirrors `runtime.validation` and `runtime.commands.validation`: small,
explicit guard functions that raise on failure rather than returning a
boolean, used at the boundaries of the plugin framework (manifest
construction, state transitions, registration).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from shared.exceptions import PluginValidationError
from runtime.plugins.state import PluginState
from shared.utils.text_utils import is_blank_or_padded

if TYPE_CHECKING:
    from runtime.plugins.manifest import PluginManifest
    from runtime.plugins.plugin import Plugin

# Basic MAJOR.MINOR.PATCH semantic version, with optional
# hyphen-prefixed pre-release and plus-prefixed build metadata. Format
# only — no precedence comparison, which this milestone does not need.
_SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")

_VALID_TRANSITIONS: dict[PluginState, frozenset[PluginState]] = {
    PluginState.CREATED: frozenset({PluginState.INITIALIZED, PluginState.FAILED}),
    PluginState.INITIALIZED: frozenset(
        {PluginState.REGISTERED, PluginState.FAILED, PluginState.STOPPED}
    ),
    PluginState.REGISTERED: frozenset(
        {PluginState.ENABLED, PluginState.FAILED, PluginState.STOPPED}
    ),
    PluginState.ENABLED: frozenset(
        {PluginState.DISABLED, PluginState.FAILED, PluginState.STOPPED}
    ),
    PluginState.DISABLED: frozenset(
        {PluginState.ENABLED, PluginState.FAILED, PluginState.STOPPED}
    ),
    PluginState.STOPPED: frozenset(),
    PluginState.FAILED: frozenset(),
}


def validate_state_transition(current: PluginState, new: PluginState) -> None:
    """Raise PluginValidationError if `current` -> `new` is not an allowed transition.

    `STOPPED` and `FAILED` are terminal and accept no further
    transitions; every other state can reach `FAILED`.
    """
    if new not in _VALID_TRANSITIONS[current]:
        raise PluginValidationError(
            f"Invalid plugin state transition: {current.name} -> {new.name}"
        )


def validate_plugin_id(plugin_id: str) -> None:
    """Raise PluginValidationError if `plugin_id` is not a usable identifier.

    A valid plugin ID is a non-empty string with no leading or trailing
    whitespace.
    """
    if is_blank_or_padded(plugin_id):
        raise PluginValidationError(f"Invalid plugin id: {plugin_id!r}")


def validate_plugin_name(name: str) -> None:
    """Raise PluginValidationError if `name` is not a usable plugin name.

    A valid plugin name is a non-empty string with no leading or
    trailing whitespace.
    """
    if is_blank_or_padded(name):
        raise PluginValidationError(f"Invalid plugin name: {name!r}")


def validate_plugin_version(version: str) -> None:
    """Raise PluginValidationError if `version` is not a basic semantic version.

    Expects `MAJOR.MINOR.PATCH`, with optional `-prerelease` and
    `+build` suffixes (e.g. `1.0.0`, `2.3.4-beta.1`, `1.0.0+build.5`).
    """
    if not isinstance(version, str) or not _SEMVER_PATTERN.match(version):
        raise PluginValidationError(f"Invalid plugin version: {version!r}")


def validate_plugin_manifest(manifest: PluginManifest) -> None:
    """Raise PluginValidationError if `manifest` fails structural validation.

    Checks the required fields (`plugin_id`, `name`, `version`) and, if
    present, that `description` and `author` are strings.
    """
    validate_plugin_id(manifest.plugin_id)
    validate_plugin_name(manifest.name)
    validate_plugin_version(manifest.version)
    if manifest.description is not None and not isinstance(manifest.description, str):
        raise PluginValidationError(
            f"Plugin description must be a str or None, got {type(manifest.description).__name__}"
        )
    if manifest.author is not None and not isinstance(manifest.author, str):
        raise PluginValidationError(
            f"Plugin author must be a str or None, got {type(manifest.author).__name__}"
        )


def validate_plugin(plugin: Plugin) -> None:
    """Raise PluginValidationError if `plugin`'s manifest fails structural validation.

    Does not check for duplicate IDs — detecting a duplicate requires
    tracking plugins across calls, which is the `PluginRegistry`'s
    responsibility, not a stateless validation function's.
    """
    validate_plugin_manifest(plugin.manifest)

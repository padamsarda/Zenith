"""Tests for runtime.plugins.validation helpers."""

from __future__ import annotations

import pytest

from runtime.exceptions import PluginValidationError
from runtime.plugins.manifest import PluginManifest
from runtime.plugins.state import PluginState
from runtime.plugins.validation import (
    validate_plugin,
    validate_plugin_id,
    validate_plugin_manifest,
    validate_plugin_name,
    validate_plugin_version,
    validate_state_transition,
)


class MinimalPlugin:
    """A bare object with a `.manifest` attribute — enough for `validate_plugin`."""

    def __init__(self, manifest: PluginManifest) -> None:
        self.manifest = manifest


# --- validate_plugin_id --------------------------------------------------


@pytest.mark.parametrize("plugin_id", ["plugin", "my-plugin", "my_plugin_1", "com.example.p"])
def test_validate_plugin_id_accepts_valid_ids(plugin_id: str) -> None:
    validate_plugin_id(plugin_id)


@pytest.mark.parametrize("plugin_id", ["", "   ", " padded", "padded "])
def test_validate_plugin_id_rejects_invalid_ids(plugin_id: str) -> None:
    with pytest.raises(PluginValidationError):
        validate_plugin_id(plugin_id)


def test_validate_plugin_id_rejects_non_string() -> None:
    with pytest.raises(PluginValidationError):
        validate_plugin_id(123)  # type: ignore[arg-type]


# --- validate_plugin_name ------------------------------------------------


@pytest.mark.parametrize("name", ["My Plugin", "plugin-name"])
def test_validate_plugin_name_accepts_valid_names(name: str) -> None:
    validate_plugin_name(name)


@pytest.mark.parametrize("name", ["", "   ", " padded", "padded "])
def test_validate_plugin_name_rejects_invalid_names(name: str) -> None:
    with pytest.raises(PluginValidationError):
        validate_plugin_name(name)


# --- validate_plugin_version ----------------------------------------------


@pytest.mark.parametrize(
    "version",
    [
        "0.0.1",
        "1.0.0",
        "12.34.56",
        "1.0.0-beta",
        "1.0.0-beta.1",
        "1.0.0+build.5",
        "1.0.0-rc.1+build.9",
    ],
)
def test_validate_plugin_version_accepts_valid_versions(version: str) -> None:
    validate_plugin_version(version)


@pytest.mark.parametrize(
    "version", ["1.0", "1", "1.0.0.0", "v1.0.0", "1.0.0-", "", "latest", "1.a.0"]
)
def test_validate_plugin_version_rejects_invalid_versions(version: str) -> None:
    with pytest.raises(PluginValidationError):
        validate_plugin_version(version)


def test_validate_plugin_version_rejects_non_string() -> None:
    with pytest.raises(PluginValidationError):
        validate_plugin_version(100)  # type: ignore[arg-type]


# --- validate_plugin_manifest ---------------------------------------------


def test_validate_plugin_manifest_passes_for_valid_manifest() -> None:
    validate_plugin_manifest(PluginManifest(plugin_id="p", name="P", version="1.0.0"))


def test_validate_plugin_manifest_passes_with_description_and_author() -> None:
    validate_plugin_manifest(
        PluginManifest(plugin_id="p", name="P", version="1.0.0", description="d", author="a")
    )


def test_validate_plugin_manifest_rejects_invalid_id() -> None:
    with pytest.raises(PluginValidationError):
        validate_plugin_manifest(PluginManifest(plugin_id="", name="P", version="1.0.0"))


def test_validate_plugin_manifest_rejects_invalid_name() -> None:
    with pytest.raises(PluginValidationError):
        validate_plugin_manifest(PluginManifest(plugin_id="p", name="", version="1.0.0"))


def test_validate_plugin_manifest_rejects_invalid_version() -> None:
    with pytest.raises(PluginValidationError):
        validate_plugin_manifest(PluginManifest(plugin_id="p", name="P", version="bad"))


def test_validate_plugin_manifest_rejects_non_string_description() -> None:
    manifest = PluginManifest(
        plugin_id="p", name="P", version="1.0.0", description=123  # type: ignore[arg-type]
    )

    with pytest.raises(PluginValidationError):
        validate_plugin_manifest(manifest)


def test_validate_plugin_manifest_rejects_non_string_author() -> None:
    manifest = PluginManifest(
        plugin_id="p", name="P", version="1.0.0", author=123  # type: ignore[arg-type]
    )

    with pytest.raises(PluginValidationError):
        validate_plugin_manifest(manifest)


# --- validate_plugin -------------------------------------------------------


def test_validate_plugin_passes_for_valid_plugin() -> None:
    validate_plugin(MinimalPlugin(PluginManifest(plugin_id="p", name="P", version="1.0.0")))


def test_validate_plugin_rejects_invalid_manifest() -> None:
    with pytest.raises(PluginValidationError):
        validate_plugin(MinimalPlugin(PluginManifest(plugin_id="", name="P", version="1.0.0")))


# --- validate_state_transition ---------------------------------------------


@pytest.mark.parametrize(
    ("current", "new"),
    [
        (PluginState.CREATED, PluginState.INITIALIZED),
        (PluginState.CREATED, PluginState.FAILED),
        (PluginState.INITIALIZED, PluginState.REGISTERED),
        (PluginState.INITIALIZED, PluginState.FAILED),
        (PluginState.INITIALIZED, PluginState.STOPPED),
        (PluginState.REGISTERED, PluginState.ENABLED),
        (PluginState.REGISTERED, PluginState.FAILED),
        (PluginState.REGISTERED, PluginState.STOPPED),
        (PluginState.ENABLED, PluginState.DISABLED),
        (PluginState.ENABLED, PluginState.FAILED),
        (PluginState.ENABLED, PluginState.STOPPED),
        (PluginState.DISABLED, PluginState.ENABLED),
        (PluginState.DISABLED, PluginState.FAILED),
        (PluginState.DISABLED, PluginState.STOPPED),
    ],
)
def test_validate_state_transition_accepts_valid_transitions(
    current: PluginState, new: PluginState
) -> None:
    validate_state_transition(current, new)


@pytest.mark.parametrize(
    ("current", "new"),
    [
        (PluginState.CREATED, PluginState.REGISTERED),
        (PluginState.CREATED, PluginState.ENABLED),
        (PluginState.INITIALIZED, PluginState.ENABLED),
        (PluginState.REGISTERED, PluginState.DISABLED),
        (PluginState.STOPPED, PluginState.ENABLED),
        (PluginState.FAILED, PluginState.ENABLED),
        (PluginState.CREATED, PluginState.CREATED),
        (PluginState.ENABLED, PluginState.REGISTERED),
    ],
)
def test_validate_state_transition_rejects_invalid_transitions(
    current: PluginState, new: PluginState
) -> None:
    with pytest.raises(PluginValidationError):
        validate_state_transition(current, new)

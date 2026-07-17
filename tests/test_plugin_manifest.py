"""Tests for the PluginManifest dataclass."""

from __future__ import annotations

import pytest

from runtime.plugins.manifest import PluginManifest


def test_manifest_carries_required_fields() -> None:
    manifest = PluginManifest(plugin_id="my-plugin", name="My Plugin", version="1.0.0")

    assert manifest.plugin_id == "my-plugin"
    assert manifest.name == "My Plugin"
    assert manifest.version == "1.0.0"


def test_description_defaults_to_none() -> None:
    manifest = PluginManifest(plugin_id="p", name="P", version="1.0.0")

    assert manifest.description is None


def test_author_defaults_to_none() -> None:
    manifest = PluginManifest(plugin_id="p", name="P", version="1.0.0")

    assert manifest.author is None


def test_description_and_author_can_be_set() -> None:
    manifest = PluginManifest(
        plugin_id="p", name="P", version="1.0.0", description="does things", author="me"
    )

    assert manifest.description == "does things"
    assert manifest.author == "me"


def test_manifest_is_immutable() -> None:
    manifest = PluginManifest(plugin_id="p", name="P", version="1.0.0")

    with pytest.raises(AttributeError):
        manifest.name = "other"  # type: ignore[misc]


def test_two_manifests_with_same_fields_are_equal() -> None:
    first = PluginManifest(plugin_id="p", name="P", version="1.0.0")
    second = PluginManifest(plugin_id="p", name="P", version="1.0.0")

    assert first == second


def test_construction_does_not_validate_id() -> None:
    manifest = PluginManifest(plugin_id="", name="P", version="not-a-version")

    assert manifest.plugin_id == ""
    assert manifest.version == "not-a-version"

"""Tests for the Plugin abstract base class."""

from __future__ import annotations

import pytest

from runtime.exceptions import PluginValidationError
from runtime.plugins.manifest import PluginManifest
from runtime.plugins.plugin import Plugin
from runtime.plugins.state import PluginState


class RecordingPlugin(Plugin):
    """A minimal concrete Plugin that records lifecycle hook calls."""

    def __init__(self, manifest: PluginManifest) -> None:
        super().__init__(manifest)
        self.calls: list[str] = []

    def initialize(self, context: object) -> None:
        self.calls.append("initialize")

    def shutdown(self, context: object) -> None:
        self.calls.append("shutdown")

    def register(self, registry: object) -> None:
        self.calls.append("register")

    def unregister(self, registry: object) -> None:
        self.calls.append("unregister")


def make_manifest(**overrides: object) -> PluginManifest:
    fields = {"plugin_id": "test-plugin", "name": "Test Plugin", "version": "1.0.0"}
    fields.update(overrides)
    return PluginManifest(**fields)  # type: ignore[arg-type]


def test_plugin_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        Plugin(make_manifest())  # type: ignore[abstract]


def test_incomplete_subclass_cannot_be_instantiated() -> None:
    class IncompletePlugin(Plugin):
        def initialize(self, context: object) -> None:
            pass

    with pytest.raises(TypeError):
        IncompletePlugin(make_manifest())  # type: ignore[abstract]


def test_plugin_exposes_manifest() -> None:
    manifest = make_manifest()
    plugin = RecordingPlugin(manifest)

    assert plugin.manifest is manifest


def test_plugin_exposes_id_from_manifest() -> None:
    plugin = RecordingPlugin(make_manifest(plugin_id="my-id"))

    assert plugin.id == "my-id"


def test_plugin_exposes_name_from_manifest() -> None:
    plugin = RecordingPlugin(make_manifest(name="My Name"))

    assert plugin.name == "My Name"


def test_plugin_exposes_version_from_manifest() -> None:
    plugin = RecordingPlugin(make_manifest(version="2.3.4"))

    assert plugin.version == "2.3.4"


def test_plugin_exposes_description_from_manifest() -> None:
    plugin = RecordingPlugin(make_manifest(description="does things"))

    assert plugin.description == "does things"


def test_plugin_exposes_author_from_manifest() -> None:
    plugin = RecordingPlugin(make_manifest(author="me"))

    assert plugin.author == "me"


def test_plugin_description_defaults_to_none() -> None:
    plugin = RecordingPlugin(make_manifest())

    assert plugin.description is None


def test_plugin_author_defaults_to_none() -> None:
    plugin = RecordingPlugin(make_manifest())

    assert plugin.author is None


def test_plugin_starts_in_created_state() -> None:
    plugin = RecordingPlugin(make_manifest())

    assert plugin.state is PluginState.CREATED


def test_plugin_starts_not_enabled() -> None:
    plugin = RecordingPlugin(make_manifest())

    assert plugin.enabled is False


def test_plugin_enabled_true_only_when_state_is_enabled() -> None:
    plugin = RecordingPlugin(make_manifest())
    plugin.transition_to(PluginState.INITIALIZED)
    plugin.transition_to(PluginState.REGISTERED)
    plugin.transition_to(PluginState.ENABLED)

    assert plugin.enabled is True


def test_plugin_enabled_false_after_disable() -> None:
    plugin = RecordingPlugin(make_manifest())
    plugin.transition_to(PluginState.INITIALIZED)
    plugin.transition_to(PluginState.REGISTERED)
    plugin.transition_to(PluginState.ENABLED)
    plugin.transition_to(PluginState.DISABLED)

    assert plugin.enabled is False


def test_transition_to_updates_state() -> None:
    plugin = RecordingPlugin(make_manifest())

    plugin.transition_to(PluginState.INITIALIZED)

    assert plugin.state is PluginState.INITIALIZED


def test_transition_to_invalid_state_raises() -> None:
    plugin = RecordingPlugin(make_manifest())

    with pytest.raises(PluginValidationError):
        plugin.transition_to(PluginState.ENABLED)


def test_transition_to_invalid_state_leaves_state_unchanged() -> None:
    plugin = RecordingPlugin(make_manifest())

    with pytest.raises(PluginValidationError):
        plugin.transition_to(PluginState.ENABLED)

    assert plugin.state is PluginState.CREATED


def test_transition_from_terminal_state_raises() -> None:
    plugin = RecordingPlugin(make_manifest())
    plugin.transition_to(PluginState.FAILED)

    with pytest.raises(PluginValidationError):
        plugin.transition_to(PluginState.INITIALIZED)


def test_full_lifecycle_transition_sequence_succeeds() -> None:
    plugin = RecordingPlugin(make_manifest())

    plugin.transition_to(PluginState.INITIALIZED)
    plugin.transition_to(PluginState.REGISTERED)
    plugin.transition_to(PluginState.ENABLED)
    plugin.transition_to(PluginState.DISABLED)
    plugin.transition_to(PluginState.ENABLED)
    plugin.transition_to(PluginState.STOPPED)

    assert plugin.state is PluginState.STOPPED


def test_id_cannot_be_reassigned() -> None:
    plugin = RecordingPlugin(make_manifest())

    with pytest.raises(AttributeError):
        plugin.id = "other"  # type: ignore[misc]


def test_manifest_cannot_be_reassigned() -> None:
    plugin = RecordingPlugin(make_manifest())

    with pytest.raises(AttributeError):
        plugin.manifest = make_manifest()  # type: ignore[misc]


def test_state_cannot_be_directly_assigned() -> None:
    plugin = RecordingPlugin(make_manifest())

    with pytest.raises(AttributeError):
        plugin.state = PluginState.ENABLED  # type: ignore[misc]


def test_concrete_hooks_are_callable_directly() -> None:
    plugin = RecordingPlugin(make_manifest())

    plugin.initialize(context=None)
    plugin.register(registry=None)
    plugin.unregister(registry=None)
    plugin.shutdown(context=None)

    assert plugin.calls == ["initialize", "register", "unregister", "shutdown"]

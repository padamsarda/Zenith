"""Tests for the PluginRegistry."""

from __future__ import annotations

import logging

import pytest

from configs.config import Config
from runtime.context import ApplicationContext
from runtime.events.event import Event
from runtime.exceptions import (
    PluginLifecycleError,
    PluginNotFoundError,
    PluginRegistrationError,
    PluginValidationError,
)
from runtime.plugins.context import PluginContext
from runtime.plugins.events import (
    PluginDisabled,
    PluginEnabled,
    PluginFailed,
    PluginRegistered,
    PluginUnregistered,
)
from runtime.plugins.manifest import PluginManifest
from runtime.plugins.plugin import Plugin
from runtime.plugins.registry import PluginRegistry
from runtime.plugins.state import PluginState

ALL_PLUGIN_EVENT_TYPES = (
    PluginRegistered,
    PluginEnabled,
    PluginDisabled,
    PluginUnregistered,
    PluginFailed,
)


class RecordingPlugin(Plugin):
    """A concrete Plugin that records lifecycle hook calls and the contexts/registries it saw."""

    def __init__(self, manifest: PluginManifest) -> None:
        super().__init__(manifest)
        self.calls: list[str] = []
        self.contexts_seen: list[PluginContext] = []
        self.registries_seen: list[PluginRegistry] = []

    def initialize(self, context: PluginContext) -> None:
        self.calls.append("initialize")
        self.contexts_seen.append(context)

    def shutdown(self, context: PluginContext) -> None:
        self.calls.append("shutdown")
        self.contexts_seen.append(context)

    def register(self, registry: PluginRegistry) -> None:
        self.calls.append("register")
        self.registries_seen.append(registry)

    def unregister(self, registry: PluginRegistry) -> None:
        self.calls.append("unregister")
        self.registries_seen.append(registry)


class FailingInitializePlugin(Plugin):
    """Raises from initialize()."""

    def initialize(self, context: PluginContext) -> None:
        raise ValueError("initialize boom")

    def shutdown(self, context: PluginContext) -> None:
        pass

    def register(self, registry: PluginRegistry) -> None:
        pass

    def unregister(self, registry: PluginRegistry) -> None:
        pass


class FailingRegisterPlugin(Plugin):
    """Raises from register()."""

    def initialize(self, context: PluginContext) -> None:
        pass

    def shutdown(self, context: PluginContext) -> None:
        pass

    def register(self, registry: PluginRegistry) -> None:
        raise ValueError("register boom")

    def unregister(self, registry: PluginRegistry) -> None:
        pass


class FailingUnregisterPlugin(Plugin):
    """Raises from unregister()."""

    def initialize(self, context: PluginContext) -> None:
        pass

    def shutdown(self, context: PluginContext) -> None:
        pass

    def register(self, registry: PluginRegistry) -> None:
        pass

    def unregister(self, registry: PluginRegistry) -> None:
        raise ValueError("unregister boom")


class FailingShutdownPlugin(Plugin):
    """Raises from shutdown()."""

    def initialize(self, context: PluginContext) -> None:
        pass

    def shutdown(self, context: PluginContext) -> None:
        raise ValueError("shutdown boom")

    def register(self, registry: PluginRegistry) -> None:
        pass

    def unregister(self, registry: PluginRegistry) -> None:
        pass


def make_application_context() -> ApplicationContext:
    return ApplicationContext(config=Config(), logger=logging.getLogger("test.plugin_registry"))


def make_manifest(**overrides: object) -> PluginManifest:
    fields = {"plugin_id": "test-plugin", "name": "Test Plugin", "version": "1.0.0"}
    fields.update(overrides)
    return PluginManifest(**fields)  # type: ignore[arg-type]


def subscribe_all(app_context: ApplicationContext) -> list[Event]:
    received: list[Event] = []
    for event_type in ALL_PLUGIN_EVENT_TYPES:
        app_context.events.subscribe(event_type, received.append)
    return received


# --- register(): success ---------------------------------------------------


def test_register_transitions_plugin_to_registered() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = RecordingPlugin(make_manifest())

    registry.register(plugin, app_context)

    assert plugin.state is PluginState.REGISTERED


def test_register_calls_initialize_then_register_in_order() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = RecordingPlugin(make_manifest())

    registry.register(plugin, app_context)

    assert plugin.calls == ["initialize", "register"]


def test_register_passes_plugin_context_to_initialize() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = RecordingPlugin(make_manifest())

    registry.register(plugin, app_context)

    assert len(plugin.contexts_seen) == 1
    assert isinstance(plugin.contexts_seen[0], PluginContext)


def test_register_context_carries_application_context() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = RecordingPlugin(make_manifest())

    registry.register(plugin, app_context)

    assert plugin.contexts_seen[0].application_context is app_context


def test_register_context_carries_matching_manifest() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    manifest = make_manifest()
    plugin = RecordingPlugin(manifest)

    registry.register(plugin, app_context)

    assert plugin.contexts_seen[0].manifest is manifest


def test_register_context_carries_registry() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = RecordingPlugin(make_manifest())

    registry.register(plugin, app_context)

    assert plugin.contexts_seen[0].registry is registry


def test_register_passes_registry_to_register_hook() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = RecordingPlugin(make_manifest())

    registry.register(plugin, app_context)

    assert plugin.registries_seen == [registry]


def test_register_stores_plugin() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = RecordingPlugin(make_manifest())

    registry.register(plugin, app_context)

    assert registry.has(plugin.id) is True
    assert registry.get(plugin.id) is plugin


def test_register_emits_plugin_registered() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    received = subscribe_all(app_context)
    plugin = RecordingPlugin(make_manifest())

    registry.register(plugin, app_context)

    names = [event.name for event in received]
    assert names == ["PluginRegistered"]


def test_register_event_carries_plugin_id_and_name() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    received: list[Event] = []
    app_context.events.subscribe(PluginRegistered, received.append)
    plugin = RecordingPlugin(make_manifest(plugin_id="p1", name="P One"))

    registry.register(plugin, app_context)

    assert received[0].payload == {"plugin_id": "p1", "name": "P One"}


def test_register_event_uses_plugin_registry_as_source() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    received: list[Event] = []
    app_context.events.subscribe(PluginRegistered, received.append)

    registry.register(RecordingPlugin(make_manifest()), app_context)

    assert received[0].source == "plugin_registry"


# --- register(): validation and duplicate failures --------------------------


def test_register_invalid_manifest_raises_validation_error() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = RecordingPlugin(make_manifest(plugin_id=""))

    with pytest.raises(PluginValidationError):
        registry.register(plugin, app_context)


def test_register_invalid_manifest_does_not_store_plugin() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = RecordingPlugin(make_manifest(plugin_id=""))

    with pytest.raises(PluginValidationError):
        registry.register(plugin, app_context)

    assert registry.has("") is False


def test_register_invalid_manifest_does_not_call_hooks() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = RecordingPlugin(make_manifest(plugin_id=""))

    with pytest.raises(PluginValidationError):
        registry.register(plugin, app_context)

    assert plugin.calls == []


def test_register_duplicate_id_raises_registration_error() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    registry.register(RecordingPlugin(make_manifest(plugin_id="dup")), app_context)

    with pytest.raises(PluginRegistrationError):
        registry.register(RecordingPlugin(make_manifest(plugin_id="dup")), app_context)


def test_register_duplicate_id_keeps_original_plugin() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    original = RecordingPlugin(make_manifest(plugin_id="dup"))
    registry.register(original, app_context)

    with pytest.raises(PluginRegistrationError):
        registry.register(RecordingPlugin(make_manifest(plugin_id="dup")), app_context)

    assert registry.get("dup") is original


# --- register(): lifecycle hook failures -------------------------------------


def test_register_initialize_failure_raises_lifecycle_error() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = FailingInitializePlugin(make_manifest())

    with pytest.raises(PluginLifecycleError):
        registry.register(plugin, app_context)


def test_register_initialize_failure_sets_state_failed() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = FailingInitializePlugin(make_manifest())

    with pytest.raises(PluginLifecycleError):
        registry.register(plugin, app_context)

    assert plugin.state is PluginState.FAILED


def test_register_initialize_failure_does_not_store_plugin() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = FailingInitializePlugin(make_manifest())

    with pytest.raises(PluginLifecycleError):
        registry.register(plugin, app_context)

    assert registry.has(plugin.id) is False


def test_register_initialize_failure_emits_plugin_failed() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    received = subscribe_all(app_context)
    plugin = FailingInitializePlugin(make_manifest())

    with pytest.raises(PluginLifecycleError):
        registry.register(plugin, app_context)

    names = [event.name for event in received]
    assert names == ["PluginFailed"]


def test_register_failed_event_carries_reason() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    received: list[Event] = []
    app_context.events.subscribe(PluginFailed, received.append)
    plugin = FailingInitializePlugin(make_manifest())

    with pytest.raises(PluginLifecycleError):
        registry.register(plugin, app_context)

    assert received[0].payload["reason"] == "initialize boom"


def test_register_lifecycle_error_wraps_original_exception() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = FailingInitializePlugin(make_manifest())

    with pytest.raises(PluginLifecycleError) as excinfo:
        registry.register(plugin, app_context)

    assert isinstance(excinfo.value.__cause__, ValueError)
    assert str(excinfo.value.__cause__) == "initialize boom"


def test_register_register_hook_failure_raises_lifecycle_error() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = FailingRegisterPlugin(make_manifest())

    with pytest.raises(PluginLifecycleError):
        registry.register(plugin, app_context)


def test_register_register_hook_failure_does_not_store_plugin() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = FailingRegisterPlugin(make_manifest())

    with pytest.raises(PluginLifecycleError):
        registry.register(plugin, app_context)

    assert registry.has(plugin.id) is False


def test_register_register_hook_failure_sets_state_failed() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = FailingRegisterPlugin(make_manifest())

    with pytest.raises(PluginLifecycleError):
        registry.register(plugin, app_context)

    assert plugin.state is PluginState.FAILED


# --- unregister(): success ---------------------------------------------------


def test_unregister_removes_plugin() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = RecordingPlugin(make_manifest())
    registry.register(plugin, app_context)

    registry.unregister(plugin, app_context)

    assert registry.has(plugin.id) is False


def test_unregister_transitions_plugin_to_stopped() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = RecordingPlugin(make_manifest())
    registry.register(plugin, app_context)

    registry.unregister(plugin, app_context)

    assert plugin.state is PluginState.STOPPED


def test_unregister_calls_unregister_then_shutdown_in_order() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = RecordingPlugin(make_manifest())
    registry.register(plugin, app_context)

    registry.unregister(plugin, app_context)

    assert plugin.calls == ["initialize", "register", "unregister", "shutdown"]


def test_unregister_passes_registry_to_unregister_hook() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = RecordingPlugin(make_manifest())
    registry.register(plugin, app_context)

    registry.unregister(plugin, app_context)

    assert plugin.registries_seen == [registry, registry]


def test_unregister_passes_plugin_context_to_shutdown() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = RecordingPlugin(make_manifest())
    registry.register(plugin, app_context)

    registry.unregister(plugin, app_context)

    assert len(plugin.contexts_seen) == 2
    assert isinstance(plugin.contexts_seen[1], PluginContext)


def test_unregister_emits_plugin_unregistered() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = RecordingPlugin(make_manifest())
    registry.register(plugin, app_context)
    received: list[Event] = []
    app_context.events.subscribe(PluginUnregistered, received.append)

    registry.unregister(plugin, app_context)

    assert len(received) == 1
    assert received[0].payload == {"plugin_id": plugin.id, "name": plugin.name}


def test_unregister_missing_plugin_raises_not_found() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = RecordingPlugin(make_manifest())

    with pytest.raises(PluginNotFoundError):
        registry.unregister(plugin, app_context)


# --- unregister(): lifecycle hook failures -----------------------------------


def test_unregister_unregister_hook_failure_raises_lifecycle_error() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = FailingUnregisterPlugin(make_manifest())
    registry.register(plugin, app_context)

    with pytest.raises(PluginLifecycleError):
        registry.unregister(plugin, app_context)


def test_unregister_unregister_hook_failure_keeps_plugin_registered() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = FailingUnregisterPlugin(make_manifest())
    registry.register(plugin, app_context)

    with pytest.raises(PluginLifecycleError):
        registry.unregister(plugin, app_context)

    assert registry.has(plugin.id) is True


def test_unregister_unregister_hook_failure_sets_state_failed() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = FailingUnregisterPlugin(make_manifest())
    registry.register(plugin, app_context)

    with pytest.raises(PluginLifecycleError):
        registry.unregister(plugin, app_context)

    assert plugin.state is PluginState.FAILED


def test_unregister_shutdown_failure_raises_lifecycle_error() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = FailingShutdownPlugin(make_manifest())
    registry.register(plugin, app_context)

    with pytest.raises(PluginLifecycleError):
        registry.unregister(plugin, app_context)


def test_unregister_shutdown_failure_keeps_plugin_registered() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = FailingShutdownPlugin(make_manifest())
    registry.register(plugin, app_context)

    with pytest.raises(PluginLifecycleError):
        registry.unregister(plugin, app_context)

    assert registry.has(plugin.id) is True


def test_unregister_emits_plugin_failed_on_hook_failure() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = FailingShutdownPlugin(make_manifest())
    registry.register(plugin, app_context)
    received: list[Event] = []
    app_context.events.subscribe(PluginFailed, received.append)

    with pytest.raises(PluginLifecycleError):
        registry.unregister(plugin, app_context)

    assert received[0].payload["reason"] == "shutdown boom"


# --- enable() / disable(): success -------------------------------------------


def test_enable_transitions_registered_plugin_to_enabled() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = RecordingPlugin(make_manifest())
    registry.register(plugin, app_context)

    registry.enable(plugin, app_context)

    assert plugin.state is PluginState.ENABLED


def test_enable_emits_plugin_enabled() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = RecordingPlugin(make_manifest())
    registry.register(plugin, app_context)
    received: list[Event] = []
    app_context.events.subscribe(PluginEnabled, received.append)

    registry.enable(plugin, app_context)

    assert len(received) == 1
    assert received[0].payload == {"plugin_id": plugin.id, "name": plugin.name}


def test_enable_does_not_call_any_plugin_hook() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = RecordingPlugin(make_manifest())
    registry.register(plugin, app_context)
    calls_before = list(plugin.calls)

    registry.enable(plugin, app_context)

    assert plugin.calls == calls_before


def test_enable_missing_plugin_raises_not_found() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = RecordingPlugin(make_manifest())

    with pytest.raises(PluginNotFoundError):
        registry.enable(plugin, app_context)


def test_enable_twice_raises_validation_error() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = RecordingPlugin(make_manifest())
    registry.register(plugin, app_context)
    registry.enable(plugin, app_context)

    with pytest.raises(PluginValidationError):
        registry.enable(plugin, app_context)


def test_disable_transitions_enabled_plugin_to_disabled() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = RecordingPlugin(make_manifest())
    registry.register(plugin, app_context)
    registry.enable(plugin, app_context)

    registry.disable(plugin, app_context)

    assert plugin.state is PluginState.DISABLED


def test_disable_emits_plugin_disabled() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = RecordingPlugin(make_manifest())
    registry.register(plugin, app_context)
    registry.enable(plugin, app_context)
    received: list[Event] = []
    app_context.events.subscribe(PluginDisabled, received.append)

    registry.disable(plugin, app_context)

    assert len(received) == 1
    assert received[0].payload == {"plugin_id": plugin.id, "name": plugin.name}


def test_disable_missing_plugin_raises_not_found() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = RecordingPlugin(make_manifest())

    with pytest.raises(PluginNotFoundError):
        registry.disable(plugin, app_context)


def test_disable_never_enabled_plugin_raises_validation_error() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = RecordingPlugin(make_manifest())
    registry.register(plugin, app_context)

    with pytest.raises(PluginValidationError):
        registry.disable(plugin, app_context)


def test_re_enable_after_disable_succeeds() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = RecordingPlugin(make_manifest())
    registry.register(plugin, app_context)
    registry.enable(plugin, app_context)
    registry.disable(plugin, app_context)

    registry.enable(plugin, app_context)

    assert plugin.state is PluginState.ENABLED


# --- get() / has() / list() ---------------------------------------------------


def test_has_returns_false_before_registration() -> None:
    registry = PluginRegistry()

    assert registry.has("missing") is False


def test_has_returns_true_after_registration() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = RecordingPlugin(make_manifest())
    registry.register(plugin, app_context)

    assert registry.has(plugin.id) is True


def test_get_missing_plugin_raises_not_found() -> None:
    registry = PluginRegistry()

    with pytest.raises(PluginNotFoundError):
        registry.get("missing")


def test_get_returns_registered_plugin_instance() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = RecordingPlugin(make_manifest())
    registry.register(plugin, app_context)

    assert registry.get(plugin.id) is plugin


def test_list_empty_registry_returns_empty_list() -> None:
    registry = PluginRegistry()

    assert registry.list() == []


def test_list_returns_all_registered_plugins() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    first = RecordingPlugin(make_manifest(plugin_id="a"))
    second = RecordingPlugin(make_manifest(plugin_id="b"))
    registry.register(first, app_context)
    registry.register(second, app_context)

    plugins = registry.list()

    assert set(plugins) == {first, second}


def test_list_returns_a_snapshot_not_the_live_dict() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = RecordingPlugin(make_manifest())
    registry.register(plugin, app_context)

    snapshot = registry.list()
    registry.unregister(plugin, app_context)

    assert snapshot == [plugin]
    assert registry.list() == []


def test_list_excludes_unregistered_plugins() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    plugin = RecordingPlugin(make_manifest())
    registry.register(plugin, app_context)
    registry.unregister(plugin, app_context)

    assert registry.list() == []


# --- multiple plugins are independent ------------------------------------------


def test_two_registries_track_plugins_independently() -> None:
    first_registry = PluginRegistry()
    second_registry = PluginRegistry()
    app_context = make_application_context()
    plugin = RecordingPlugin(make_manifest())

    first_registry.register(plugin, app_context)

    assert second_registry.has(plugin.id) is False


def test_registry_holds_multiple_independent_plugins() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    first = RecordingPlugin(make_manifest(plugin_id="a", name="A"))
    second = RecordingPlugin(make_manifest(plugin_id="b", name="B"))

    registry.register(first, app_context)
    registry.register(second, app_context)
    registry.enable(first, app_context)

    assert first.state is PluginState.ENABLED
    assert second.state is PluginState.REGISTERED


def test_reregister_after_unregister_succeeds() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()
    first_instance = RecordingPlugin(make_manifest(plugin_id="reused"))
    registry.register(first_instance, app_context)
    registry.unregister(first_instance, app_context)

    second_instance = RecordingPlugin(make_manifest(plugin_id="reused"))
    registry.register(second_instance, app_context)

    assert registry.get("reused") is second_instance

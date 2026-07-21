"""Tests for PluginLoader: discovery and import of plugins from disk."""

from __future__ import annotations

import logging
from pathlib import Path

from configs.config import Config
from runtime.context import ApplicationContext
from runtime.plugins.events import PluginFailed, PluginLoadFailed, PluginRegistered
from runtime.plugins.loader import PluginLoader
from shared.events.event import Event

VALID_PLUGIN_SOURCE = '''\
from __future__ import annotations

from runtime.plugins.manifest import PluginManifest
from runtime.plugins.plugin import Plugin


class {class_name}(Plugin):
    def __init__(self) -> None:
        super().__init__(
            PluginManifest(plugin_id="{plugin_id}", name="{name}", version="1.0.0")
        )

    def initialize(self, context: object) -> None:
        pass

    def shutdown(self, context: object) -> None:
        pass

    def register(self, registry: object) -> None:
        pass

    def unregister(self, registry: object) -> None:
        pass


def create_plugin() -> Plugin:
    return {class_name}()
'''


def make_application_context() -> ApplicationContext:
    return ApplicationContext(config=Config(), logger=logging.getLogger("test.plugin_loader"))


def write_plugin(
    plugins_dir: Path,
    directory_name: str,
    *,
    plugin_id: str | None = None,
    class_name: str = "ExamplePlugin",
    source: str | None = None,
) -> Path:
    """Write a `plugin.py` under `plugins_dir/directory_name` and return its path."""
    plugin_dir = plugins_dir / directory_name
    plugin_dir.mkdir(parents=True)
    entry_point = plugin_dir / "plugin.py"
    text = source if source is not None else VALID_PLUGIN_SOURCE.format(
        class_name=class_name,
        plugin_id=plugin_id or directory_name,
        name=directory_name,
    )
    entry_point.write_text(text)
    return entry_point


# --- discovery and successful loading ---------------------------------------


def test_load_all_on_missing_directory_returns_empty_list(tmp_path: Path) -> None:
    loader = PluginLoader(tmp_path / "does-not-exist")
    app_context = make_application_context()

    loaded = loader.load_all(app_context.plugins, app_context)

    assert loaded == []


def test_load_all_on_empty_directory_returns_empty_list(tmp_path: Path) -> None:
    loader = PluginLoader(tmp_path)
    app_context = make_application_context()

    loaded = loader.load_all(app_context.plugins, app_context)

    assert loaded == []


def test_load_all_ignores_files_directly_under_plugins_dir(tmp_path: Path) -> None:
    (tmp_path / "not_a_plugin_dir.py").write_text("x = 1\n")
    loader = PluginLoader(tmp_path)
    app_context = make_application_context()

    loaded = loader.load_all(app_context.plugins, app_context)

    assert loaded == []


def test_load_all_ignores_directories_without_plugin_py(tmp_path: Path) -> None:
    (tmp_path / "empty_dir").mkdir()
    loader = PluginLoader(tmp_path)
    app_context = make_application_context()

    loaded = loader.load_all(app_context.plugins, app_context)

    assert loaded == []


def test_load_all_loads_a_valid_plugin(tmp_path: Path) -> None:
    write_plugin(tmp_path, "alpha")
    loader = PluginLoader(tmp_path)
    app_context = make_application_context()

    loaded = loader.load_all(app_context.plugins, app_context)

    assert [plugin.id for plugin in loaded] == ["alpha"]


def test_load_all_registers_the_plugin(tmp_path: Path) -> None:
    write_plugin(tmp_path, "alpha")
    loader = PluginLoader(tmp_path)
    app_context = make_application_context()

    loader.load_all(app_context.plugins, app_context)

    assert app_context.plugins.has("alpha") is True


def test_load_all_emits_plugin_registered(tmp_path: Path) -> None:
    write_plugin(tmp_path, "alpha")
    loader = PluginLoader(tmp_path)
    app_context = make_application_context()
    received: list[Event] = []
    app_context.events.subscribe(PluginRegistered, received.append)

    loader.load_all(app_context.plugins, app_context)

    assert len(received) == 1
    assert received[0].payload["plugin_id"] == "alpha"


def test_load_all_loads_multiple_plugins_in_directory_name_order(tmp_path: Path) -> None:
    write_plugin(tmp_path, "zeta", class_name="ZetaPlugin")
    write_plugin(tmp_path, "alpha", class_name="AlphaPlugin")
    loader = PluginLoader(tmp_path)
    app_context = make_application_context()

    loaded = loader.load_all(app_context.plugins, app_context)

    assert [plugin.id for plugin in loaded] == ["alpha", "zeta"]


# --- pre-registration failures: logged and skipped, never raised -----------


def test_load_all_skips_module_with_no_create_plugin_factory(tmp_path: Path) -> None:
    write_plugin(tmp_path, "broken", source="from __future__ import annotations\n")
    loader = PluginLoader(tmp_path)
    app_context = make_application_context()

    loaded = loader.load_all(app_context.plugins, app_context)

    assert loaded == []


def test_load_all_emits_plugin_load_failed_for_missing_factory(tmp_path: Path) -> None:
    write_plugin(tmp_path, "broken", source="from __future__ import annotations\n")
    loader = PluginLoader(tmp_path)
    app_context = make_application_context()
    received: list[Event] = []
    app_context.events.subscribe(PluginLoadFailed, received.append)

    loader.load_all(app_context.plugins, app_context)

    assert len(received) == 1
    assert "create_plugin" in received[0].payload["reason"]


def test_load_all_skips_module_that_raises_on_import(tmp_path: Path) -> None:
    write_plugin(tmp_path, "broken", source="raise ValueError('boom at import time')\n")
    loader = PluginLoader(tmp_path)
    app_context = make_application_context()

    loaded = loader.load_all(app_context.plugins, app_context)

    assert loaded == []


def test_load_all_skips_factory_that_raises(tmp_path: Path) -> None:
    source = """\
from __future__ import annotations


def create_plugin():
    raise RuntimeError("factory boom")
"""
    write_plugin(tmp_path, "broken", source=source)
    loader = PluginLoader(tmp_path)
    app_context = make_application_context()

    loaded = loader.load_all(app_context.plugins, app_context)

    assert loaded == []


def test_load_all_skips_factory_returning_non_plugin(tmp_path: Path) -> None:
    source = """\
from __future__ import annotations


def create_plugin():
    return object()
"""
    write_plugin(tmp_path, "broken", source=source)
    loader = PluginLoader(tmp_path)
    app_context = make_application_context()

    loaded = loader.load_all(app_context.plugins, app_context)

    assert loaded == []


def test_load_all_continues_past_a_broken_plugin(tmp_path: Path) -> None:
    write_plugin(tmp_path, "broken", source="raise ValueError('boom')\n")
    write_plugin(tmp_path, "alpha")
    loader = PluginLoader(tmp_path)
    app_context = make_application_context()

    loaded = loader.load_all(app_context.plugins, app_context)

    assert [plugin.id for plugin in loaded] == ["alpha"]


# --- registration-time failures (registry's own concern) --------------------


def test_load_all_skips_plugin_that_fails_registration(tmp_path: Path) -> None:
    source = """\
from __future__ import annotations

from runtime.plugins.manifest import PluginManifest
from runtime.plugins.plugin import Plugin


class FailingPlugin(Plugin):
    def __init__(self) -> None:
        super().__init__(PluginManifest(plugin_id="failing", name="Failing", version="1.0.0"))

    def initialize(self, context: object) -> None:
        raise ValueError("initialize boom")

    def shutdown(self, context: object) -> None:
        pass

    def register(self, registry: object) -> None:
        pass

    def unregister(self, registry: object) -> None:
        pass


def create_plugin() -> Plugin:
    return FailingPlugin()
"""
    write_plugin(tmp_path, "failing", source=source)
    loader = PluginLoader(tmp_path)
    app_context = make_application_context()

    loaded = loader.load_all(app_context.plugins, app_context)

    assert loaded == []
    assert app_context.plugins.has("failing") is False


def test_load_all_registration_failure_emits_plugin_failed_not_load_failed(
    tmp_path: Path,
) -> None:
    source = """\
from __future__ import annotations

from runtime.plugins.manifest import PluginManifest
from runtime.plugins.plugin import Plugin


class FailingPlugin(Plugin):
    def __init__(self) -> None:
        super().__init__(PluginManifest(plugin_id="failing", name="Failing", version="1.0.0"))

    def initialize(self, context: object) -> None:
        raise ValueError("initialize boom")

    def shutdown(self, context: object) -> None:
        pass

    def register(self, registry: object) -> None:
        pass

    def unregister(self, registry: object) -> None:
        pass


def create_plugin() -> Plugin:
    return FailingPlugin()
"""
    write_plugin(tmp_path, "failing", source=source)
    loader = PluginLoader(tmp_path)
    app_context = make_application_context()
    failed: list[Event] = []
    load_failed: list[Event] = []
    app_context.events.subscribe(PluginFailed, failed.append)
    app_context.events.subscribe(PluginLoadFailed, load_failed.append)

    loader.load_all(app_context.plugins, app_context)

    assert len(failed) == 1
    assert load_failed == []

"""Tests for PluginContext."""

from __future__ import annotations

import logging

import pytest

from configs.config import Config
from runtime.context import ApplicationContext
from runtime.plugins.context import PluginContext
from runtime.plugins.manifest import PluginManifest
from runtime.plugins.registry import PluginRegistry


def make_application_context() -> ApplicationContext:
    return ApplicationContext(config=Config(), logger=logging.getLogger("test.plugin_context"))


def make_manifest() -> PluginManifest:
    return PluginManifest(plugin_id="p", name="P", version="1.0.0")


def test_plugin_context_carries_application_context() -> None:
    app_context = make_application_context()
    registry = PluginRegistry()

    context = PluginContext(
        application_context=app_context, manifest=make_manifest(), registry=registry
    )

    assert context.application_context is app_context


def test_plugin_context_carries_manifest() -> None:
    manifest = make_manifest()

    context = PluginContext(
        application_context=make_application_context(),
        manifest=manifest,
        registry=PluginRegistry(),
    )

    assert context.manifest is manifest


def test_plugin_context_carries_registry() -> None:
    registry = PluginRegistry()

    context = PluginContext(
        application_context=make_application_context(), manifest=make_manifest(), registry=registry
    )

    assert context.registry is registry


def test_plugin_context_is_immutable() -> None:
    context = PluginContext(
        application_context=make_application_context(),
        manifest=make_manifest(),
        registry=PluginRegistry(),
    )

    with pytest.raises(AttributeError):
        context.manifest = make_manifest()  # type: ignore[misc]


def test_two_plugin_contexts_can_share_the_same_registry() -> None:
    registry = PluginRegistry()
    app_context = make_application_context()

    first = PluginContext(
        application_context=app_context, manifest=make_manifest(), registry=registry
    )
    second = PluginContext(
        application_context=app_context, manifest=make_manifest(), registry=registry
    )

    assert first.registry is second.registry

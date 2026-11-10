from __future__ import annotations

from types import SimpleNamespace

import pytest

from ultk.builtins._common import FunctionTool, object_schema
from ultk.exceptions import ConfigurationError, ToolPermissionError
from ultk.plugins import PluginDefinition, PluginManager, PluginManifest
from ultk.registry import ToolRegistry


class FakeEntryPoint:
    name = "weather"
    value = "weather_plugin:create_plugin"
    dist = SimpleNamespace(name="weather-plugin")

    def __init__(self, factory):
        self.factory = factory
        self.loaded = False

    def load(self):
        self.loaded = True
        return self.factory


def weather_tool():
    return FunctionTool(
        "weather.current",
        "Return a sample weather result.",
        object_schema({}),
        "weather:read",
        lambda: {"temperature": 20},
    )


def test_discovery_does_not_import_plugin_code() -> None:
    entry_point = FakeEntryPoint(lambda: None)
    manager = PluginManager(ToolRegistry(), entry_points_provider=lambda: [entry_point])
    descriptors = manager.discover()
    assert descriptors[0].plugin_id == "weather"
    assert descriptors[0].trusted is False
    assert entry_point.loaded is False


def test_plugin_must_be_explicitly_trusted_before_loading() -> None:
    entry_point = FakeEntryPoint(lambda: None)
    manager = PluginManager(ToolRegistry(), entry_points_provider=lambda: [entry_point])
    with pytest.raises(ToolPermissionError, match="not host-trusted"):
        manager.enable("weather")
    assert entry_point.loaded is False


def test_trusted_plugin_registers_and_can_be_disabled() -> None:
    definition = PluginDefinition(
        PluginManifest("weather", "1.0.0", "Weather tools"),
        lambda: [weather_tool()],
    )
    entry_point = FakeEntryPoint(lambda: definition)
    registry = ToolRegistry()
    manager = PluginManager(
        registry,
        trusted_plugins={"weather"},
        entry_points_provider=lambda: [entry_point],
    )
    descriptor = manager.enable("weather")
    assert descriptor.enabled is True
    assert registry.get("weather.current").spec.name == "weather.current"
    assert manager.enabled_plugins() == ("weather",)
    assert manager.disable("weather") is True
    assert len(registry) == 0
    assert manager.disable("weather") is False


def test_plugin_api_version_mismatch_fails_before_registration() -> None:
    definition = PluginDefinition(
        PluginManifest("weather", "1.0.0", "Weather tools", api_version="99.0"),
        lambda: [weather_tool()],
    )
    manager = PluginManager(
        ToolRegistry(),
        trusted_plugins={"weather"},
        entry_points_provider=lambda: [FakeEntryPoint(lambda: definition)],
    )
    with pytest.raises(ConfigurationError, match="API-incompatible"):
        manager.enable("weather")
    assert len(manager.registry) == 0


def test_plugin_tools_must_use_plugin_namespace() -> None:
    wrong_tool = FunctionTool(
        "other.current", "Wrong namespace", object_schema({}),
        "other:read", dict,
    )
    definition = PluginDefinition(
        PluginManifest("weather", "1.0.0", "Weather tools"),
        lambda: [wrong_tool],
    )
    manager = PluginManager(
        ToolRegistry(),
        trusted_plugins={"weather"},
        entry_points_provider=lambda: [FakeEntryPoint(lambda: definition)],
    )
    with pytest.raises(ConfigurationError, match="namespace"):
        manager.enable("weather")
    assert len(manager.registry) == 0

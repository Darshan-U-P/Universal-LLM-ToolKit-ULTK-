"""Explicitly trusted Python entry-point plugin discovery and lifecycle management."""

from __future__ import annotations

import re
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from importlib import metadata
from typing import Any

from ultk.exceptions import (
    ConfigurationError,
    DuplicateToolError,
    ToolNotFoundError,
    ToolPermissionError,
)
from ultk.registry import ToolRegistry
from ultk.tool import Tool

PLUGIN_ENTRY_POINT_GROUP = "ultk.plugins"
PLUGIN_API_VERSION = "0.1"
_PLUGIN_ID = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")


@dataclass(frozen=True, slots=True)
class PluginManifest:
    plugin_id: str
    version: str
    description: str
    api_version: str = PLUGIN_API_VERSION


@dataclass(frozen=True, slots=True)
class PluginDefinition:
    manifest: PluginManifest
    create_tools: Callable[[], Iterable[Tool]]


@dataclass(frozen=True, slots=True)
class PluginDescriptor:
    plugin_id: str
    distribution: str
    entry_point: str
    trusted: bool
    enabled: bool


class PluginManager:
    """Discover metadata without importing code; load only host-trusted plugins."""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        trusted_plugins: set[str] | frozenset[str] = frozenset(),
        entry_points_provider: Callable[[], Iterable[Any]] | None = None,
    ) -> None:
        if any(not _PLUGIN_ID.fullmatch(name) for name in trusted_plugins):
            raise ValueError("Trusted plugin IDs must be lowercase namespaced identifiers.")
        self.registry = registry
        self.trusted_plugins = frozenset(trusted_plugins)
        self.entry_points_provider = entry_points_provider
        self._enabled: dict[str, tuple[str, ...]] = {}
        self._lock = threading.RLock()

    def _entry_points(self) -> dict[str, Any]:
        points = (
            self.entry_points_provider()
            if self.entry_points_provider is not None
            else metadata.entry_points(group=PLUGIN_ENTRY_POINT_GROUP)
        )
        discovered: dict[str, Any] = {}
        for point in points:
            name = str(point.name)
            if not _PLUGIN_ID.fullmatch(name):
                continue
            if name in discovered:
                raise ConfigurationError(f"Duplicate plugin entry point: {name}")
            discovered[name] = point
        return discovered

    def discover(self) -> tuple[PluginDescriptor, ...]:
        """List installed entry-point metadata without importing plugin modules."""
        points = self._entry_points()
        return tuple(
            PluginDescriptor(
                plugin_id=name,
                distribution=str(getattr(getattr(point, "dist", None), "name", "unknown")),
                entry_point=str(getattr(point, "value", "")),
                trusted=name in self.trusted_plugins,
                enabled=name in self._enabled,
            )
            for name, point in sorted(points.items())
        )

    def enable(self, plugin_id: str) -> PluginDescriptor:
        if plugin_id not in self.trusted_plugins:
            raise ToolPermissionError(f"Plugin is not host-trusted: {plugin_id}")
        with self._lock:
            if plugin_id in self._enabled:
                descriptor = next(
                    item for item in self.discover() if item.plugin_id == plugin_id
                )
                return descriptor
            point = self._entry_points().get(plugin_id)
            if point is None:
                raise ToolNotFoundError(f"Plugin entry point is not installed: {plugin_id}")
            try:
                factory = point.load()
                definition = factory() if callable(factory) else factory
                if not isinstance(definition, PluginDefinition):
                    raise ConfigurationError(
                        "Plugin entry point must return a PluginDefinition."
                    )
                manifest = definition.manifest
                if (
                    manifest.plugin_id != plugin_id
                    or not _PLUGIN_ID.fullmatch(manifest.plugin_id)
                    or manifest.api_version != PLUGIN_API_VERSION
                    or not manifest.version
                    or not manifest.description
                ):
                    raise ConfigurationError("Plugin manifest is invalid or API-incompatible.")
                tools = tuple(definition.create_tools())
                if not tools:
                    raise ConfigurationError("Plugin did not provide any tools.")
                staged = ToolRegistry()
                for tool in tools:
                    if not tool.spec.name.startswith(f"{plugin_id}."):
                        raise ConfigurationError(
                            f"Plugin tool must use the '{plugin_id}.' namespace."
                        )
                    staged.register(tool)
                existing = {tool.spec.name for tool in self.registry.list()}
                collisions = existing.intersection(
                    tool.spec.name for tool in staged.list()
                )
                if collisions:
                    raise DuplicateToolError(
                        f"Plugin tool names already exist: {', '.join(sorted(collisions))}"
                    )
                for tool in staged.list():
                    self.registry.register(tool)
            except (ConfigurationError, DuplicateToolError, ToolPermissionError):
                raise
            except Exception as exc:  # noqa: BLE001 - isolate plugin import/factory errors
                raise ConfigurationError(
                    f"Plugin loading failed ({type(exc).__name__})."
                ) from exc
            tool_names = tuple(tool.spec.name for tool in staged.list())
            self._enabled[plugin_id] = tool_names
            return next(item for item in self.discover() if item.plugin_id == plugin_id)

    def disable(self, plugin_id: str) -> bool:
        """Remove future registry visibility; already-running calls are not interrupted."""
        with self._lock:
            tool_names = self._enabled.pop(plugin_id, None)
            if tool_names is None:
                return False
            for name in tool_names:
                self.registry.unregister(name)
            return True

    def enabled_plugins(self) -> tuple[str, ...]:
        return tuple(sorted(self._enabled))

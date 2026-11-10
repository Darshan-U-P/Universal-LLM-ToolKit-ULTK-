# Plugin SDK and Manager

ULTK discovers Python package entry points without importing plugin modules. Loading occurs only after the host explicitly trusts and enables a plugin.

## Plugin author contract

A plugin package exports a factory through the `ultk.plugins` entry-point group:

```toml
[project.entry-points."ultk.plugins"]
weather = "weather_ultk:create_plugin"
```

The factory returns a `PluginDefinition`:

```python
from ultk import PluginDefinition, PluginManifest
from ultk.builtins._common import FunctionTool, object_schema

def create_plugin():
    tool = FunctionTool(
        "weather.current",
        "Get current weather from the configured weather service.",
        object_schema({"city": {"type": "string"}}, ["city"]),
        "weather:read",
        get_weather,
    )
    return PluginDefinition(
        PluginManifest("weather", "1.0.0", "Weather integration tools"),
        lambda: [tool],
    )
```

Every tool name must use the plugin's namespace prefix (for example, `weather.current`). The plugin API version must match the installed ULTK plugin API version.

## Host configuration

```python
manager = engine.configure_plugins(trusted_plugins={"weather"})
installed = manager.discover()  # metadata only; no plugin import
manager.enable("weather")       # imports and registers trusted plugin tools
manager.disable("weather")      # removes tools from future registry discovery
```

Discovery does not execute plugin code. The host trust allowlist is independent of discovery and enablement. Plugins are never installed automatically, and ULTK does not resolve or install their Python dependencies.

## Security boundaries

A trusted plugin executes in the ULTK host process with the host user's privileges. Entry-point loading is arbitrary Python code execution, not a sandbox. Only trust reviewed packages, pin their versions/hashes in deployment, and isolate untrusted plugin code in a separate worker/container with restricted filesystem and network access.

Disabling a plugin removes its tools from the registry but does not interrupt already-running calls or unload imported Python modules. Dependency resolution, hot-reload, signed plugin manifests, marketplace publishing and isolated plugin workers remain future work.

"""In-memory tool registry and provider schema projection."""

from __future__ import annotations

from typing import Iterable

from ultk.exceptions import DuplicateToolError, ToolNotFoundError
from ultk.schemas import validate_schema
from ultk.tool import Tool


class ToolRegistry:
    """Stores enabled tool implementations by stable, namespaced identifier."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        spec = tool.spec
        if not spec.name or "." not in spec.name:
            raise ValueError("Tool names must be namespaced, for example 'web.fetch_url'.")
        if spec.timeout_seconds <= 0 or spec.max_output_chars <= 0:
            raise ValueError("Tool timeout and output limit must be positive.")
        validate_schema(spec.input_schema)
        if spec.name in self._tools:
            raise DuplicateToolError(f"Tool already registered: {spec.name}")
        self._tools[spec.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotFoundError(f"Tool is not registered: {name}") from exc

    def list(self, names: Iterable[str] | None = None) -> tuple[Tool, ...]:
        if names is None:
            return tuple(self._tools[name] for name in sorted(self._tools))
        return tuple(self.get(name) for name in names)

    def provider_schemas(self, names: Iterable[str] | None = None) -> list[dict]:
        """Return OpenAI-compatible function tool definitions."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.spec.name,
                    "description": tool.spec.description,
                    "parameters": dict(tool.spec.input_schema),
                },
            }
            for tool in self.list(names)
        ]

    def __len__(self) -> int:
        return len(self._tools)

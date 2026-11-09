"""Tool authoring contract."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ultk.models import ToolContext, ToolSpec


@runtime_checkable
class Tool(Protocol):
    """An executable capability exposed to an LLM through the runtime."""

    @property
    def spec(self) -> ToolSpec:
        """Return immutable tool metadata and input schema."""

    async def invoke(self, arguments: dict[str, Any], context: ToolContext) -> Any:
        """Execute validated arguments and return a JSON-serializable value."""

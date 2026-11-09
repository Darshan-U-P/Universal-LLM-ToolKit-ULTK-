"""Authorization policies. The default policy denies all tool execution."""

from __future__ import annotations

from typing import Protocol

from ultk.models import ToolContext, ToolSpec


class PermissionPolicy(Protocol):
    async def authorize(self, spec: ToolSpec, context: ToolContext) -> bool:
        """Return True only when this exact tool invocation is permitted."""


class DenyAllPolicy:
    async def authorize(self, spec: ToolSpec, context: ToolContext) -> bool:
        return False


class AllowListPolicy:
    """Allow explicitly named tools whose required capabilities are granted."""

    def __init__(
        self,
        allowed_tools: set[str] | frozenset[str],
        *,
        require_capabilities: bool = True,
    ) -> None:
        self._allowed_tools = frozenset(allowed_tools)
        self._require_capabilities = require_capabilities

    async def authorize(self, spec: ToolSpec, context: ToolContext) -> bool:
        if spec.name not in self._allowed_tools:
            return False
        if not self._require_capabilities:
            return True
        return spec.capabilities.issubset(context.granted_capabilities)

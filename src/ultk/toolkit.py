"""Convenience facade for configuring and running ULTK."""

from __future__ import annotations

from collections.abc import Iterable

from ultk.agents.runtime import AgentRuntime
from ultk.execution import ToolDispatcher
from ultk.permissions import DenyAllPolicy, PermissionPolicy
from ultk.providers.base import ProviderAdapter
from ultk.registry import ToolRegistry
from ultk.tool import Tool


class ToolKit:
    """Compose a provider, registry, policy, and bounded agent runtime.

    Provider credentials are intentionally handled by the provider adapter.
    """

    def __init__(
        self,
        provider: ProviderAdapter,
        *,
        policy: PermissionPolicy | None = None,
        max_steps: int = 8,
    ) -> None:
        self.provider = provider
        self.registry = ToolRegistry()
        self.policy = policy or DenyAllPolicy()
        self.dispatcher = ToolDispatcher(self.registry, self.policy)
        self.runtime = AgentRuntime(
            provider, self.registry, self.dispatcher, max_steps=max_steps
        )

    def register_tool(self, tool: Tool) -> None:
        self.registry.register(tool)

    async def run(
        self,
        prompt: str,
        *,
        session_id: str = "default",
        enabled_tools: Iterable[str] | None = None,
        granted_capabilities: frozenset[str] = frozenset(),
    ) -> str:
        return await self.runtime.run(
            prompt,
            session_id=session_id,
            enabled_tools=enabled_tools,
            granted_capabilities=granted_capabilities,
        )

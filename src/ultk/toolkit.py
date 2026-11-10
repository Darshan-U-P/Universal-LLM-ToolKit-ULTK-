"""Convenience facade for configuring and running ULTK."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from ultk.agents.runtime import AgentEventHandler, AgentRuntime
from ultk.execution import ToolDispatcher
from ultk.permissions import DenyAllPolicy, PermissionPolicy
from ultk.providers.base import ProviderAdapter
from ultk.registry import ToolRegistry
from ultk.tool import Tool


class ToolKit:
    """Compose a provider, registry, policy, audit logger and bounded agent runtime."""

    def __init__(
        self,
        provider: ProviderAdapter,
        *,
        policy: PermissionPolicy | None = None,
        max_steps: int = 8,
        registry: ToolRegistry | None = None,
        audit_logger: Any = None,
    ) -> None:
        self.provider = provider
        self.registry = registry or ToolRegistry()
        self.policy = policy or DenyAllPolicy()
        self.audit_logger = audit_logger
        self.dispatcher = ToolDispatcher(
            self.registry, self.policy, audit_logger=self.audit_logger
        )
        self.runtime = AgentRuntime(
            provider, self.registry, self.dispatcher, max_steps=max_steps
        )

    def register_tool(self, tool: Tool) -> None:
        self.registry.register(tool)

    def register_tools(self, tools: Iterable[Tool]) -> None:
        for tool in tools:
            self.register_tool(tool)

    async def run(
        self,
        prompt: str,
        *,
        session_id: str = "default",
        enabled_tools: Iterable[str] | None = None,
        granted_capabilities: frozenset[str] = frozenset(),
        messages: Sequence[Mapping[str, Any]] | None = None,
        tool_metadata: Mapping[str, Any] | None = None,
        on_event: AgentEventHandler | None = None,
    ) -> str:
        return await self.runtime.run(
            prompt,
            session_id=session_id,
            enabled_tools=enabled_tools,
            granted_capabilities=granted_capabilities,
            messages=messages,
            tool_metadata=tool_metadata,
            on_event=on_event,
        )

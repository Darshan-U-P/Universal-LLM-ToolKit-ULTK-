"""Bounded provider-neutral tool-calling loop."""

from __future__ import annotations

import json
from collections.abc import Iterable

from ultk.exceptions import AgentStepLimitError
from ultk.execution import ToolDispatcher
from ultk.models import ToolResult
from ultk.providers.base import ProviderAdapter
from ultk.registry import ToolRegistry


class AgentRuntime:
    def __init__(
        self,
        provider: ProviderAdapter,
        registry: ToolRegistry,
        dispatcher: ToolDispatcher,
        *,
        max_steps: int = 8,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1.")
        self.provider = provider
        self.registry = registry
        self.dispatcher = dispatcher
        self.max_steps = max_steps

    async def run(
        self,
        prompt: str,
        *,
        session_id: str = "default",
        enabled_tools: Iterable[str] | None = None,
        granted_capabilities: frozenset[str] = frozenset(),
    ) -> str:
        messages: list[dict] = [{"role": "user", "content": prompt}]
        enabled_names = (
            frozenset(enabled_tools)
            if enabled_tools is not None
            else frozenset(tool.spec.name for tool in self.registry.list())
        )
        tool_schemas = self.registry.provider_schemas(enabled_names)
        for _ in range(self.max_steps):
            turn = await self.provider.complete(messages, tool_schemas)
            if not turn.tool_calls:
                return turn.content or ""
            messages.append({
                "role": "assistant",
                "content": turn.content,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(dict(call.arguments)),
                        },
                    }
                    for call in turn.tool_calls
                ],
            })
            for call in turn.tool_calls:
                if call.name not in enabled_names:
                    result = ToolResult(
                        call.id,
                        call.name,
                        f"Tool is not enabled for this run: {call.name}",
                        True,
                    )
                else:
                    result = await self.dispatcher.execute(
                        call,
                        session_id=session_id,
                        granted_capabilities=granted_capabilities,
                    )
                messages.append({
                    "role": "tool",
                    "tool_call_id": result.call_id,
                    "name": result.tool_name,
                    "content": result.content,
                    "is_error": result.is_error,
                })
        raise AgentStepLimitError(
            f"Agent reached the maximum of {self.max_steps} model turns without completion."
        )

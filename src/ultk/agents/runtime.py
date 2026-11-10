"""Bounded provider-neutral tool-calling loop with host context and lifecycle events."""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from typing import Any

from ultk.exceptions import AgentStepLimitError
from ultk.execution import ToolDispatcher
from ultk.models import ToolResult
from ultk.providers.base import ProviderAdapter
from ultk.registry import ToolRegistry

AgentEventHandler = Callable[[Mapping[str, Any]], Awaitable[None] | None]


async def _emit(
    handler: AgentEventHandler | None,
    event: Mapping[str, Any],
) -> None:
    if handler is None:
        return
    result = handler(event)
    if inspect.isawaitable(result):
        await result


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
        messages: Sequence[Mapping[str, Any]] | None = None,
        tool_metadata: Mapping[str, Any] | None = None,
        on_event: AgentEventHandler | None = None,
    ) -> str:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")

        if messages is None:
            conversation: list[dict[str, Any]] = [
                {"role": "user", "content": prompt}
            ]
        else:
            if len(messages) > 100:
                raise ValueError("messages cannot contain more than 100 entries")
            conversation = []
            for message in messages:
                if not isinstance(message, Mapping):
                    raise TypeError("each conversation message must be an object")
                role = message.get("role")
                if role not in {"system", "user", "assistant", "tool"}:
                    raise ValueError("conversation contains an unsupported message role")
                content = message.get("content")
                if content is not None and not isinstance(content, str):
                    raise ValueError("conversation message content must be text or null")
                conversation.append(dict(message))
            latest_user = next(
                (
                    item.get("content")
                    for item in reversed(conversation)
                    if item.get("role") == "user"
                ),
                None,
            )
            if latest_user != prompt:
                conversation.append({"role": "user", "content": prompt})

        enabled_names = (
            frozenset(enabled_tools)
            if enabled_tools is not None
            else frozenset(tool.spec.name for tool in self.registry.list())
        )
        tool_schemas = self.registry.provider_schemas(enabled_names)
        context_metadata = dict(tool_metadata or {})

        for step in range(1, self.max_steps + 1):
            await _emit(on_event, {
                "type": "model_turn_started",
                "session_id": session_id,
                "step": step,
            })
            turn = await self.provider.complete(conversation, tool_schemas)
            await _emit(on_event, {
                "type": "model_turn_completed",
                "session_id": session_id,
                "step": step,
                "tool_call_count": len(turn.tool_calls),
            })
            if not turn.tool_calls:
                answer = turn.content or ""
                await _emit(on_event, {
                    "type": "run_completed",
                    "session_id": session_id,
                    "answer": answer,
                })
                return answer

            conversation.append({
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
                await _emit(on_event, {
                    "type": "tool_call_started",
                    "session_id": session_id,
                    "call_id": call.id,
                    "tool_name": call.name,
                    "arguments": dict(call.arguments),
                })
                if call.name not in enabled_names:
                    result = ToolResult(
                        call.id,
                        call.name,
                        f"Tool is not enabled for this run: {call.name}",
                        True,
                        {"tool_disabled": True},
                    )
                else:
                    result = await self.dispatcher.execute(
                        call,
                        session_id=session_id,
                        granted_capabilities=granted_capabilities,
                        metadata=context_metadata,
                    )
                event = {
                    "type": (
                        "approval_required"
                        if result.metadata.get("approval_required")
                        else "tool_call_completed"
                    ),
                    "session_id": session_id,
                    "call_id": result.call_id,
                    "tool_name": result.tool_name,
                    "content": result.content,
                    "is_error": result.is_error,
                    "metadata": dict(result.metadata),
                }
                await _emit(on_event, event)
                conversation.append({
                    "role": "tool",
                    "tool_call_id": result.call_id,
                    "name": result.tool_name,
                    "content": result.content,
                    "is_error": result.is_error,
                })

        await _emit(on_event, {
            "type": "run_failed",
            "session_id": session_id,
            "reason": "step_limit",
            "max_steps": self.max_steps,
        })
        raise AgentStepLimitError(
            f"Agent reached the maximum of {self.max_steps} model turns without completion."
        )

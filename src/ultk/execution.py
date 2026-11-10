"""Policy-gated, bounded tool execution with optional audit logging."""

from __future__ import annotations

import asyncio
import json

from ultk.exceptions import (
    ToolExecutionError,
    ToolNotFoundError,
    ToolPermissionError,
    ToolSchemaError,
)
from ultk.models import ToolCallRequest, ToolContext, ToolResult
from ultk.permissions import DenyAllPolicy, PermissionPolicy
from ultk.registry import ToolRegistry
from ultk.schemas import validate_arguments


class ToolDispatcher:
    def __init__(
        self,
        registry: ToolRegistry,
        policy: PermissionPolicy | None = None,
    ) -> None:
        self.registry = registry
        self.policy = policy or DenyAllPolicy()

    async def execute(
        self,
        request: ToolCallRequest,
        *,
        session_id: str = "default",
        granted_capabilities: frozenset[str] = frozenset(),
    ) -> ToolResult:
        try:
            tool = self.registry.get(request.name)
        except ToolNotFoundError:
            return ToolResult(
                request.id, request.name, f"Tool is not registered: {request.name}", True
            )

        spec = tool.spec
        context = ToolContext(
            call_id=request.id,
            session_id=session_id,
            granted_capabilities=granted_capabilities,
        )
        try:
            validate_arguments(spec.input_schema, request.arguments)
            if not await self.policy.authorize(spec, context):
                raise ToolPermissionError(f"Execution denied by policy: {spec.name}")
            value = await asyncio.wait_for(
                tool.invoke(dict(request.arguments), context),
                timeout=spec.timeout_seconds,
            )
            content = value if isinstance(value, str) else json.dumps(
                value, ensure_ascii=False, default=str
            )
            if len(content) > spec.max_output_chars:
                content = content[: spec.max_output_chars] + "\n[output truncated]"
            return ToolResult(request.id, spec.name, content)
        except TimeoutError:
            return ToolResult(request.id, spec.name, "Tool execution timed out.", True)
        except (ToolSchemaError, ToolPermissionError, ToolExecutionError) as exc:
            return ToolResult(request.id, spec.name, str(exc), True)
        except Exception as exc:  # noqa: BLE001 - isolate arbitrary tool failures
            # Keep exception details out of model-visible output by default.
            return ToolResult(
                request.id,
                spec.name,
                f"Tool execution failed ({type(exc).__name__}).",
                True,
            )

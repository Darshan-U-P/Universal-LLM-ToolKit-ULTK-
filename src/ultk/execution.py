"""Policy-gated, bounded tool execution with optional audit logging."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

from ultk.exceptions import (
    ApprovalRequiredError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolPermissionError,
    ToolSchemaError,
)
from ultk.models import ToolCallRequest, ToolContext, ToolResult
from ultk.permissions import DenyAllPolicy, PermissionPolicy
from ultk.registry import ToolRegistry


class ToolDispatcher:
    def __init__(self, registry: ToolRegistry, policy: PermissionPolicy | None = None,
                 audit_logger: Any = None) -> None:
        self.registry = registry
        self.policy = policy or DenyAllPolicy()
        self.audit_logger = audit_logger

    async def _audit(self, request: ToolCallRequest, *, session_id: str,
                     granted_capabilities: frozenset[str], result: ToolResult,
                     approval_id: str | None = None) -> ToolResult:
        if self.audit_logger is None:
            return result
        try:
            encoded = json.dumps(dict(request.arguments), sort_keys=True,
                                 separators=(",", ":"), ensure_ascii=False, default=str)
            await asyncio.to_thread(
                self.audit_logger.record,
                call_id=request.id,
                tool_name=request.name,
                session_id=session_id,
                outcome=result.metadata.get("audit_outcome", "error" if result.is_error else "success"),
                is_error=result.is_error,
                argument_sha256=hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
                argument_keys=list(request.arguments),
                granted_capabilities=list(granted_capabilities),
                approval_id=approval_id,
                error_type=result.metadata.get("error_type"),
            )
        except Exception:  # noqa: BLE001 - audit backend failure is surfaced, not hidden
            return ToolResult(
                request.id, request.name,
                "Tool result could not be durably audited; inspect the host audit backend.",
                True, {"audit_failure": True},
            )
        return result

    async def execute(self, request: ToolCallRequest, *, session_id: str = "default",
                      granted_capabilities: frozenset[str] = frozenset()) -> ToolResult:
        try:
            tool = self.registry.get(request.name)
        except ToolNotFoundError:
            result = ToolResult(
                request.id, request.name, f"Tool is not registered: {request.name}", True,
                {"error_type": "ToolNotFoundError"})
            return await self._audit(request, session_id=session_id,
                                     granted_capabilities=granted_capabilities, result=result)

        spec = tool.spec
        context = ToolContext(
            call_id=request.id,
            session_id=session_id,
            granted_capabilities=granted_capabilities,
            arguments=dict(request.arguments),
            metadata={},
        )
        approval_id = None
        try:
            from ultk.schemas import validate_arguments
            validate_arguments(spec.input_schema, request.arguments)
            if not await self.policy.authorize(spec, context):
                raise ToolPermissionError(f"Execution denied by policy: {spec.name}")
            preflight = await self._audit(
                request, session_id=session_id,
                granted_capabilities=granted_capabilities,
                result=ToolResult(request.id, spec.name, "Authorized for execution.",
                                  metadata={"audit_outcome": "authorized"}),
                approval_id=context.metadata.get("approval_id"),
            )
            if preflight.metadata.get("audit_failure"):
                return preflight
            value = await asyncio.wait_for(
                tool.invoke(dict(request.arguments), context),
                timeout=spec.timeout_seconds,
            )
            content = value if isinstance(value, str) else json.dumps(
                value, ensure_ascii=False, default=str)
            if len(content) > spec.max_output_chars:
                content = content[:spec.max_output_chars] + "\n[output truncated]"
            result = ToolResult(request.id, spec.name, content)
        except ApprovalRequiredError as exc:
            approval_id = exc.approval_id
            result = ToolResult(
                request.id, spec.name, str(exc), True,
                {"approval_required": True, "approval_id": approval_id,
                 "error_type": type(exc).__name__})
        except TimeoutError:
            result = ToolResult(request.id, spec.name, "Tool execution timed out.", True,
                                {"error_type": "TimeoutError"})
        except (ToolSchemaError, ToolPermissionError, ToolExecutionError) as exc:
            result = ToolResult(request.id, spec.name, str(exc), True,
                                {"error_type": type(exc).__name__})
        except Exception as exc:  # noqa: BLE001 - isolate arbitrary tool failures
            result = ToolResult(
                request.id, spec.name,
                f"Tool execution failed ({type(exc).__name__}).", True,
                {"error_type": type(exc).__name__})
        return await self._audit(
            request, session_id=session_id, granted_capabilities=granted_capabilities,
            result=result, approval_id=approval_id)

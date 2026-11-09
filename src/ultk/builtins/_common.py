"""Helpers shared by optional built-in tool packs."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from ultk.exceptions import ToolExecutionError
from ultk.models import ToolContext, ToolSpec


class FunctionTool:
    """Adapt a bounded synchronous function to the ULTK asynchronous Tool protocol."""

    def __init__(self, name: str, description: str, schema: dict[str, Any],
                 capability: str, function: Callable[..., Any], *,
                 timeout: float = 20.0, output_limit: int = 12000) -> None:
        self.spec = ToolSpec(name=name, description=description, input_schema=schema,
                             capabilities=frozenset({capability}),
                             timeout_seconds=timeout, max_output_chars=output_limit)
        self._function = function

    async def invoke(self, arguments: dict[str, Any], context: ToolContext) -> Any:
        try:
            return await asyncio.wait_for(asyncio.to_thread(self._function, **arguments),
                                          timeout=self.spec.timeout_seconds)
        except TimeoutError as exc:
            raise ToolExecutionError("Operation exceeded its time limit.") from exc
        except ToolExecutionError:
            raise
        except Exception as exc:
            raise ToolExecutionError(f"Operation failed ({type(exc).__name__}).") from exc


def object_schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"type": "object", "properties": properties,
                              "additionalProperties": False}
    if required:
        result["required"] = required
    return result

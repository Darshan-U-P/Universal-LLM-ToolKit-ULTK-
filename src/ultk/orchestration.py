"""Dependency-aware workflow execution with bounded parallel ready steps."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ultk.exceptions import WorkflowError
from ultk.execution import ToolDispatcher
from ultk.models import ToolCallRequest, ToolResult


@dataclass(frozen=True, slots=True)
class WorkflowStep:
    step_id: str
    tool_name: str
    arguments: Mapping[str, Any]
    depends_on: tuple[str, ...] = ()


def _resolve_references(value: Any, outputs: Mapping[str, Any]) -> Any:
    if isinstance(value, dict):
        if set(value) == {"$ref"}:
            reference = value["$ref"]
            if not isinstance(reference, str) or not reference:
                raise WorkflowError("Workflow $ref must be a non-empty string.")
            step_id, separator, pointer = reference.partition("#")
            if step_id not in outputs:
                raise WorkflowError(f"Workflow reference is not available: {step_id}")
            resolved = outputs[step_id]
            if separator and pointer:
                if not pointer.startswith("/"):
                    raise WorkflowError("JSON Pointer references must start with '/'.")
                for token in pointer[1:].split("/"):
                    token = token.replace("~1", "/").replace("~0", "~")
                    try:
                        resolved = resolved[int(token)] if isinstance(resolved, list) else resolved[token]
                    except (KeyError, IndexError, ValueError, TypeError) as exc:
                        raise WorkflowError(f"Workflow reference path does not exist: {reference}") from exc
            return resolved
        return {key: _resolve_references(item, outputs) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_references(item, outputs) for item in value]
    return value


class WorkflowEngine:
    """Execute a static DAG; references are explicit data, never evaluated code."""

    def __init__(self, dispatcher: ToolDispatcher, *, max_steps: int = 50,
                 max_concurrency: int = 4) -> None:
        if max_steps < 1 or max_concurrency < 1:
            raise ValueError("Workflow limits must be positive.")
        self.dispatcher = dispatcher
        self.max_steps = max_steps
        self.max_concurrency = max_concurrency

    @staticmethod
    def _validate(steps: Sequence[WorkflowStep]) -> dict[str, WorkflowStep]:
        if not steps or len(steps) > 500:
            raise WorkflowError("A workflow must contain between 1 and 500 steps.")
        by_id: dict[str, WorkflowStep] = {}
        for step in steps:
            if not step.step_id or len(step.step_id) > 100 or step.step_id in by_id:
                raise WorkflowError("Workflow step IDs must be unique, non-empty and at most 100 chars.")
            if not step.tool_name or not isinstance(step.arguments, Mapping):
                raise WorkflowError(f"Invalid tool or arguments in step {step.step_id}.")
            by_id[step.step_id] = step
        for step in steps:
            if step.step_id in step.depends_on or any(dep not in by_id for dep in step.depends_on):
                raise WorkflowError(f"Invalid dependency list in step {step.step_id}.")
        visited: set[str] = set()
        active: set[str] = set()

        def visit(step_id: str) -> None:
            if step_id in active:
                raise WorkflowError("Workflow dependency graph contains a cycle.")
            if step_id in visited:
                return
            active.add(step_id)
            for dependency in by_id[step_id].depends_on:
                visit(dependency)
            active.remove(step_id)
            visited.add(step_id)

        for step_id in by_id:
            visit(step_id)
        return by_id

    async def run(self, steps: Sequence[WorkflowStep], *, session_id: str = "default",
                  granted_capabilities: frozenset[str] = frozenset(),
                  fail_fast: bool = False) -> dict[str, Any]:
        by_id = self._validate(steps)
        if len(by_id) > self.max_steps:
            raise WorkflowError(f"Workflow exceeds the configured {self.max_steps}-step limit.")
        pending, completed = set(by_id), {}
        results: dict[str, ToolResult] = {}
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def execute(step: WorkflowStep) -> ToolResult:
            arguments = _resolve_references(dict(step.arguments), completed)
            async with semaphore:
                return await self.dispatcher.execute(
                    ToolCallRequest(uuid.uuid4().hex, step.tool_name, arguments),
                    session_id=session_id, granted_capabilities=granted_capabilities)

        while pending:
            ready = sorted(step_id for step_id in pending
                           if all(dep in results for dep in by_id[step_id].depends_on))
            if not ready:
                raise WorkflowError("Workflow cannot make progress; unresolved dependencies remain.")
            runnable = [sid for sid in ready
                        if not any(results[dep].is_error for dep in by_id[sid].depends_on)]
            for step_id in set(ready) - set(runnable):
                results[step_id] = ToolResult(
                    uuid.uuid4().hex, by_id[step_id].tool_name,
                    "Skipped because a dependency failed.", True, {"skipped": True})
                pending.remove(step_id)
            if not runnable:
                continue
            batch = await asyncio.gather(*(execute(by_id[sid]) for sid in runnable))
            for step_id, result in zip(runnable, batch, strict=True):
                results[step_id] = result
                pending.remove(step_id)
                if not result.is_error:
                    try:
                        completed[step_id] = json.loads(result.content)
                    except json.JSONDecodeError:
                        completed[step_id] = result.content
            if fail_fast and any(result.is_error for result in batch):
                for step_id in pending:
                    results[step_id] = ToolResult(
                        uuid.uuid4().hex, by_id[step_id].tool_name,
                        "Cancelled after an earlier workflow step failed.", True,
                        {"cancelled": True})
                pending.clear()
        return {
            "steps": {sid: {"tool_name": result.tool_name, "content": result.content,
                            "is_error": result.is_error, "metadata": dict(result.metadata)}
                      for sid, result in results.items()},
            "succeeded": sum(not result.is_error for result in results.values()),
            "failed_or_skipped": sum(result.is_error for result in results.values()),
        }

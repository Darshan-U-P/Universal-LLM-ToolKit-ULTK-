"""Shared immutable data contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: Mapping[str, Any]
    version: str = "1.0.0"
    capabilities: frozenset[str] = frozenset()
    timeout_seconds: float = 30.0
    max_output_chars: int = 12_000


@dataclass(frozen=True, slots=True)
class ToolContext:
    call_id: str
    session_id: str = "default"
    granted_capabilities: frozenset[str] = frozenset()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolCallRequest:
    id: str
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    tool_name: str
    content: str
    is_error: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AssistantTurn:
    content: str | None = None
    tool_calls: tuple[ToolCallRequest, ...] = ()

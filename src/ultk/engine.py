"""Direct, LLM-independent tool execution engine."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ultk.execution import ToolDispatcher
from ultk.models import ToolCallRequest, ToolResult
from ultk.permissions import DenyAllPolicy, PermissionPolicy
from ultk.registry import ToolRegistry
from ultk.tool import Tool


class ToolEngine:
    """Register and execute tools directly, without configuring an LLM provider."""

    def __init__(
        self,
        *,
        registry: ToolRegistry | None = None,
        policy: PermissionPolicy | None = None,
    ) -> None:
        self.registry = registry or ToolRegistry()
        self.policy = policy or DenyAllPolicy()
        self.dispatcher = ToolDispatcher(self.registry, self.policy)

    def register_tool(self, tool: Tool) -> None:
        self.registry.register(tool)

    def register_tools(self, tools: Iterable[Tool]) -> None:
        for tool in tools:
            self.register_tool(tool)

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        session_id: str = "default",
        granted_capabilities: frozenset[str] = frozenset(),
    ) -> ToolResult:
        """Execute one registered tool through the normal validation and policy path."""
        request = ToolCallRequest(id=uuid.uuid4().hex, name=name, arguments=arguments)
        return await self.dispatcher.execute(
            request,
            session_id=session_id,
            granted_capabilities=granted_capabilities,
        )

    def install_filesystem_tools(
        self, root_dir: str | Path, *, max_file_bytes: int = 2_000_000
    ) -> None:
        """Install the built-in filesystem tools, confined to root_dir."""
        from ultk.builtins.filesystem import create_filesystem_tools

        self.register_tools(create_filesystem_tools(root_dir, max_file_bytes=max_file_bytes))

    def install_system_tools(self) -> None:
        """Install read-only operating-system and process inspection tools."""
        from ultk.builtins.system import create_system_tools

        self.register_tools(create_system_tools())

    def install_terminal_tools(
        self,
        working_root: str | Path,
        allowed_executables: Mapping[str, str | Path],
        **options: Any,
    ) -> None:
        """Install command execution for explicitly allowlisted executable paths."""
        from ultk.builtins.terminal import create_terminal_tools

        self.register_tools(create_terminal_tools(working_root, allowed_executables, **options))

    def install_process_management_tools(self) -> None:
        """Install PID-verified terminate, suspend, and resume operations."""
        from ultk.builtins.process_management import create_process_management_tools

        self.register_tools(create_process_management_tools())

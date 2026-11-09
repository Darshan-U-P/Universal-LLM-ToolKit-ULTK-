"""Direct, LLM-independent tool execution engine."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ultk.execution import ToolDispatcher
from ultk.models import ToolCallRequest, ToolResult
from ultk.permissions import DenyAllPolicy, PermissionPolicy
from ultk.registry import ToolRegistry


class ToolEngine:
    """Register, govern and execute tools without requiring an LLM provider."""

    def __init__(self, *, registry: ToolRegistry | None = None,
                 policy: PermissionPolicy | None = None,
                 audit_logger: Any = None) -> None:
        self.registry = registry or ToolRegistry()
        self.policy = policy or DenyAllPolicy()
        self.audit_logger = audit_logger
        self.dispatcher = ToolDispatcher(self.registry, self.policy, self.audit_logger)

    def configure_plugins(
        self,
        *,
        trusted_plugins: set[str] | frozenset[str] = frozenset(),
    ) -> Any:
        from ultk.plugins import PluginManager
        self.plugin_manager = PluginManager(
            self.registry, trusted_plugins=trusted_plugins
        )
        return self.plugin_manager

    def enable_audit(self, database: str | Path) -> Any:
        from ultk.audit import SQLiteAuditLogger
        self.audit_logger = SQLiteAuditLogger(database)
        self.dispatcher.audit_logger = self.audit_logger
        return self.audit_logger

    def require_approval(self, database: str | Path, *,
                         approval_capabilities: set[str] | frozenset[str],
                         ttl_seconds: int = 600,
                         on_request: Any = None) -> Any:
        from ultk.approvals import ApprovalPolicy, SQLiteApprovalStore
        store = SQLiteApprovalStore(database, ttl_seconds=ttl_seconds)
        self.policy = ApprovalPolicy(
            self.policy, store, approval_capabilities=approval_capabilities,
            on_request=on_request)
        self.dispatcher.policy = self.policy
        return store

    def create_workflow_engine(self, *, max_steps: int = 50,
                               max_concurrency: int = 4) -> Any:
        from ultk.orchestration import WorkflowEngine
        return WorkflowEngine(self.dispatcher, max_steps=max_steps,
                              max_concurrency=max_concurrency)

    def register_tool(self, tool: Any) -> None:
        self.registry.register(tool)

    def register_tools(self, tools: Iterable[Any]) -> None:
        for tool in tools:
            self.register_tool(tool)

    async def execute(self, name: str, arguments: dict[str, Any], *,
                      session_id: str = "default",
                      granted_capabilities: frozenset[str] = frozenset()) -> ToolResult:
        request = ToolCallRequest(id=uuid.uuid4().hex, name=name, arguments=arguments)
        return await self.dispatcher.execute(
            request, session_id=session_id, granted_capabilities=granted_capabilities)

    async def execute_many(self, calls: Iterable[ToolCallRequest], *,
                           session_id: str = "default",
                           granted_capabilities: frozenset[str] = frozenset(),
                           max_concurrency: int = 4) -> tuple[ToolResult, ...]:
        """Execute independent calls concurrently while preserving input order."""
        requests = tuple(calls)
        if max_concurrency < 1 or max_concurrency > 64:
            raise ValueError("max_concurrency must be between 1 and 64.")
        semaphore = asyncio.Semaphore(max_concurrency)

        async def run(request: ToolCallRequest) -> ToolResult:
            async with semaphore:
                return await self.dispatcher.execute(
                    request, session_id=session_id,
                    granted_capabilities=granted_capabilities)

        return tuple(await asyncio.gather(*(run(request) for request in requests)))

    def install_data_tools(
        self,
        *,
        root_dir: str | Path,
        sqlite_database: str | Path | None = None,
        allow_database_writes: bool = False,
        max_file_bytes: int = 5_000_000,
        max_rows: int = 1000,
    ) -> None:
        from ultk.builtins.data import create_data_tools
        self.register_tools(create_data_tools(
            root_dir=root_dir,
            sqlite_database=sqlite_database,
            allow_database_writes=allow_database_writes,
            max_file_bytes=max_file_bytes,
            max_rows=max_rows,
        ))

    def install_email_tools(self, **configuration: Any) -> None:
        from ultk.builtins.communications import create_email_tools
        self.register_tools(create_email_tools(**configuration))

    def install_media_tools(
        self,
        *,
        root_dir: str | Path,
        ffmpeg_binary: str | None = None,
        ffprobe_binary: str | None = None,
        max_input_bytes: int = 1_000_000_000,
        max_output_bytes: int = 1_000_000_000,
        max_pixels: int = 40_000_000,
    ) -> None:
        from ultk.builtins.media import create_media_tools
        self.register_tools(create_media_tools(
            root_dir=root_dir,
            ffmpeg_binary=ffmpeg_binary,
            ffprobe_binary=ffprobe_binary,
            max_input_bytes=max_input_bytes,
            max_output_bytes=max_output_bytes,
            max_pixels=max_pixels,
        ))

    def install_rest_tools(
        self,
        endpoints: Mapping[str, Mapping[str, Any]],
        *,
        allow_writes: bool = False,
        max_response_bytes: int = 1_000_000,
        timeout_seconds: int = 20,
    ) -> None:
        from ultk.builtins.integrations import create_rest_tools
        self.register_tools(create_rest_tools(
            endpoints,
            allow_writes=allow_writes,
            max_response_bytes=max_response_bytes,
            timeout_seconds=timeout_seconds,
        ))

    def install_rest_tools(
        self,
        endpoints: Mapping[str, Mapping[str, Any]],
        *,
        allow_writes: bool = False,
        max_response_bytes: int = 1_000_000,
        timeout_seconds: int = 20,
    ) -> None:
        from ultk.builtins.integrations import create_rest_tools
        self.register_tools(create_rest_tools(
            endpoints,
            allow_writes=allow_writes,
            max_response_bytes=max_response_bytes,
            timeout_seconds=timeout_seconds,
        ))

    def install_document_tools(
        self,
        *,
        root_dir: str | Path,
        max_file_bytes: int = 20_000_000,
        max_output_chars: int = 50_000,
    ) -> None:
        from ultk.builtins.documents import create_document_tools
        self.register_tools(create_document_tools(
            root_dir=root_dir,
            max_file_bytes=max_file_bytes,
            max_output_chars=max_output_chars,
        ))

    def install_filesystem_tools(self, root_dir: str | Path, *,
                                 max_file_bytes: int = 2_000_000) -> None:
        from ultk.builtins.filesystem import create_filesystem_tools
        self.register_tools(create_filesystem_tools(root_dir, max_file_bytes=max_file_bytes))

    def install_system_tools(self) -> None:
        from ultk.builtins.system import create_system_tools
        self.register_tools(create_system_tools())

    def install_terminal_tools(self, working_root: str | Path,
                               allowed_executables: Mapping[str, str | Path],
                               **options: Any) -> None:
        from ultk.builtins.terminal import create_terminal_tools
        self.register_tools(create_terminal_tools(working_root, allowed_executables, **options))

    def install_process_management_tools(self) -> None:
        from ultk.builtins.process_management import create_process_management_tools
        self.register_tools(create_process_management_tools())

    def install_computer_os_tools(
        self,
        *,
        filesystem_root: str | Path = ".",
        state_database: str | Path = "./ultk_computer_os.sqlite3",
        allowed_services: frozenset[str] = frozenset(),
        allow_posix_chmod: bool = True,
        allow_posix_chown: bool = False,
        max_output_bytes: int = 200_000,
    ) -> None:
        """Install persistent desktop context and cross-platform OS administration tools."""
        from ultk.builtins.computer_os import create_computer_os_tools
        self.register_tools(create_computer_os_tools(
            filesystem_root=filesystem_root,
            state_database=state_database,
            allowed_services=allowed_services,
            allow_posix_chmod=allow_posix_chmod,
            allow_posix_chown=allow_posix_chown,
            max_output_bytes=max_output_bytes,
        ))

    def install_computer_tools(self, *, image_root: str | Path = "./screenshots",
                               allowed_apps: dict[str, str] | None = None,
                               allowed_environment_names: tuple[str, ...] = ()) -> None:
        from ultk.builtins.computer import create_computer_tools
        self.register_tools(create_computer_tools(
            image_root=image_root, allowed_apps=allowed_apps,
            allowed_environment_names=allowed_environment_names))

    def install_advanced_computer_tools(self, *, image_root: str | Path = "./screenshots") -> None:
        from ultk.builtins.computer_advanced import create_advanced_computer_tools
        self.register_tools(create_advanced_computer_tools(image_root=image_root))

    def install_scheduler_tools(self, database: str | Path,
                                handlers: dict[str, Any]) -> None:
        from ultk.builtins.scheduler import create_scheduler_tools
        self.register_tools(create_scheduler_tools(database, handlers))

    def install_web_tools(self, *, download_root: str | Path = "./downloads") -> None:
        from ultk.builtins.web import create_web_tools
        self.register_tools(create_web_tools(download_root=str(download_root)))

    def install_advanced_browser_tools(self, *, session_root: str | Path = "./browser_sessions",
                                       monitor_database: str | Path = "./site_monitors.sqlite3",
                                       notifier: Any = None) -> None:
        from ultk.builtins.browser_automation import create_advanced_browser_tools
        self.register_tools(create_advanced_browser_tools(
            session_root=session_root, monitor_database=monitor_database, notifier=notifier))

    def install_git_tools(
        self,
        *,
        repository_root: str | Path,
        allowed_remote_hosts: set[str] | frozenset[str] = frozenset(),
        timeout_seconds: int = 30,
        max_output_bytes: int = 200_000,
    ) -> None:
        """Install repository-scoped Git tools with explicit HTTPS remote allowlisting."""
        from ultk.builtins.git import create_git_tools
        self.register_tools(create_git_tools(
            repository_root=repository_root,
            allowed_remote_hosts=allowed_remote_hosts,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        ))

    def install_powershell_tools(
        self,
        *,
        executable: str | Path | None = None,
        working_root: str | Path = ".",
        timeout_seconds: int = 20,
        max_output_bytes: int = 200_000,
        allowed_script_hashes: Mapping[str, str] | None = None,
        script_root: str | Path | None = None,
        allowed_modules: frozenset[str] = frozenset(),
        allowed_computers: frozenset[str] = frozenset(),
        allowed_environment_names: frozenset[str] = frozenset(),
    ) -> None:
        """Install dedicated PowerShell-native tools with host-defined trust policies."""
        from ultk.builtins.powershell import create_powershell_tools
        self.register_tools(create_powershell_tools(
            executable=executable,
            working_root=working_root,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
            allowed_script_hashes=allowed_script_hashes,
            script_root=script_root,
            allowed_modules=allowed_modules,
            allowed_computers=allowed_computers,
            allowed_environment_names=allowed_environment_names,
        ))

    def install_development_tools(self, *, project_root: str | Path,
                                  allowed_executables: dict[str, str] | None = None) -> None:
        from ultk.builtins.development import create_development_tools
        self.register_tools(create_development_tools(
            project_root=project_root, allowed_executables=allowed_executables))

    def install_advanced_development_tools(self, *, project_root: str | Path,
                                           **configuration: Any) -> None:
        from ultk.builtins.development_advanced import create_advanced_development_tools
        self.register_tools(create_advanced_development_tools(
            project_root=project_root, **configuration))

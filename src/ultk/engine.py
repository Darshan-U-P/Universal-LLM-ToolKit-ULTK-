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
        self.plugin_manager = None

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

    def require_approval(
        self,
        database: str | Path,
        *,
        approval_capabilities: set[str] | frozenset[str],
        ttl_seconds: int = 600,
        on_request: Any = None,
    ) -> Any:
        from ultk.approvals import ApprovalPolicy, SQLiteApprovalStore
        store = SQLiteApprovalStore(database, ttl_seconds=ttl_seconds)
        self.policy = ApprovalPolicy(
            self.policy,
            store,
            approval_capabilities=approval_capabilities,
            on_request=on_request,
        )
        self.dispatcher.policy = self.policy
        return store

    def create_workflow_engine(
        self,
        database: str | Path = "./ultk_workflows.sqlite3",
        *,
        max_steps: int = 100,
        max_concurrency: int = 4,
    ) -> Any:
        """Create a persistent workflow engine sharing this engine's policy-gated dispatcher."""
        from ultk.orchestration import WorkflowEngine
        return WorkflowEngine(
            self.dispatcher, database, max_steps=max_steps,
            max_concurrency=max_concurrency,
        )

    def register_tool(self, tool: Any) -> None:
        self.registry.register(tool)

    def register_tools(self, tools: Iterable[Any]) -> None:
        for tool in tools:
            self.register_tool(tool)

    async def execute(self, name: str, arguments: dict[str, Any], *,
                      session_id: str = "default",
                      granted_capabilities: frozenset[str] = frozenset(),
                      metadata: Mapping[str, Any] | None = None) -> ToolResult:
        request = ToolCallRequest(id=uuid.uuid4().hex, name=name, arguments=arguments)
        return await self.dispatcher.execute(
            request, session_id=session_id,
            granted_capabilities=granted_capabilities, metadata=metadata)

    async def execute_many(self, calls: Iterable[ToolCallRequest], *,
                           session_id: str = "default",
                           granted_capabilities: frozenset[str] = frozenset(),
                           max_concurrency: int = 4,
                           metadata: Mapping[str, Any] | None = None) -> tuple[ToolResult, ...]:
        """Execute independent calls concurrently while preserving input order."""
        requests = tuple(calls)
        if max_concurrency < 1 or max_concurrency > 64:
            raise ValueError("max_concurrency must be between 1 and 64.")
        semaphore = asyncio.Semaphore(max_concurrency)

        async def run(request: ToolCallRequest) -> ToolResult:
            async with semaphore:
                return await self.dispatcher.execute(
                    request, session_id=session_id,
                    granted_capabilities=granted_capabilities,
                    metadata=metadata)

        return tuple(await asyncio.gather(*(run(request) for request in requests)))

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
        allowed_acl_sids: frozenset[str] = frozenset(),
        allowed_eject_devices: frozenset[str] = frozenset(),
        allow_windows_acl_changes: bool = False,
        allow_posix_chmod: bool = True,
        allow_posix_chown: bool = False,
        max_output_bytes: int = 200_000,
    ) -> None:
        """Install multi-display desktop automation and cross-platform computer/OS tools."""
        from ultk.builtins.computer_os import create_computer_os_tools
        self.register_tools(create_computer_os_tools(
            filesystem_root=filesystem_root,
            state_database=state_database,
            allowed_services=allowed_services,
            allowed_acl_sids=allowed_acl_sids,
            allowed_eject_devices=allowed_eject_devices,
            allow_windows_acl_changes=allow_windows_acl_changes,
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


    def install_computer_visual_tools(
        self,
        *,
        allowed_ocr_languages: tuple[str, ...] = ("eng",),
        max_ocr_lines: int = 100,
    ) -> None:
        """Install OCR-backed visual desktop interaction tools.

        The host must install the Tesseract executable and selected language data
        separately; the Python OCR wrapper is an optional dependency.
        """
        from ultk.builtins.computer_visual import create_computer_visual_tools
        self.register_tools(create_computer_visual_tools(
            allowed_ocr_languages=allowed_ocr_languages,
            max_ocr_lines=max_ocr_lines,
        ))

    def install_computer_vision_tools(
        self,
        *,
        template_root: str | Path = "./computer_templates",
        max_template_bytes: int = 2_000_000,
        max_template_pixels: int = 2_000_000,
    ) -> None:
        """Install bounded image-template recognition and desktop targeting tools."""
        from ultk.builtins.computer_vision import create_computer_vision_tools
        self.register_tools(create_computer_vision_tools(
            template_root=template_root,
            max_template_bytes=max_template_bytes,
            max_template_pixels=max_template_pixels,
        ))

    def install_computer_grounding_tools(
        self,
        *,
        grounder: Any,
        max_screenshot_pixels: int = 16_000_000,
        max_screenshot_bytes: int = 12_000_000,
        max_candidates: int = 10,
    ) -> None:
        """Install natural-language visual grounding with a host-provided model adapter.

        The grounder receives PNG screenshot bytes and a target description, and
        returns validated candidate boxes. ULTK does not choose or bundle a model.
        """
        from ultk.builtins.computer_grounding import create_computer_grounding_tools
        self.register_tools(create_computer_grounding_tools(
            grounder=grounder,
            max_screenshot_pixels=max_screenshot_pixels,
            max_screenshot_bytes=max_screenshot_bytes,
            max_candidates=max_candidates,
        ))

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

    def install_comprehensive_browser_tools(
        self,
        *,
        profile_root: str | Path = "./browser_profiles",
        headless: bool = True,
        extension_dirs: tuple[str | Path, ...] = (),
        notifier: Any = None,
        download_root: str | Path | None = None,
        max_download_bytes: int = 25_000_000,
    ) -> None:
        """Install persistent-profile browser automation, monitoring and guarded form submission.

        Extension directories and download roots are trusted host configuration and are never
        selected by model input.
        """
        from ultk.builtins.browser_comprehensive import create_comprehensive_browser_tools
        self.register_tools(create_comprehensive_browser_tools(
            profile_root=profile_root,
            headless=headless,
            extension_dirs=extension_dirs,
            notifier=notifier,
            download_root=download_root,
            max_download_bytes=max_download_bytes,
        ))

    def install_semantic_browser_tools(
        self, *, session_root: str | Path = "./browser_sessions"
    ) -> None:
        """Install accessibility-oriented browser inspection and interaction tools."""
        from ultk.builtins.browser_semantic import create_semantic_browser_tools
        self.register_tools(create_semantic_browser_tools(session_root=session_root))

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

    def install_advanced_git_tools(
        self,
        *,
        project_root: str | Path,
        worktree_root: str | Path | None = None,
        allowed_submodule_hosts: tuple[str, ...] = (),
        pull_request_adapter: Any = None,
    ) -> None:
        """Install repository-confined advanced Git operations.

        The optional PR adapter is trusted host code with signature
        adapter(action: str, payload: dict) -> dict. Credentials and network access
        remain the host application's responsibility.
        """
        from ultk.builtins.git_operations import create_advanced_git_tools
        self.register_tools(create_advanced_git_tools(
            project_root=project_root,
            worktree_root=worktree_root,
            allowed_submodule_hosts=allowed_submodule_hosts,
            pull_request_adapter=pull_request_adapter,
        ))


    def install_document_tools(
        self,
        *,
        root_dir: str | Path,
        max_file_bytes: int = 25_000_000,
        max_output_chars: int = 50_000,
        max_pdf_pages: int = 500,
    ) -> None:
        """Install bounded document discovery, extraction and PDF operations.

        The root directory is trusted host configuration. Parser dependencies are optional.
        """
        from ultk.builtins.documents import create_document_tools
        self.register_tools(create_document_tools(
            root_dir=root_dir,
            max_file_bytes=max_file_bytes,
            max_output_chars=max_output_chars,
            max_pdf_pages=max_pdf_pages,
        ))

    def install_structured_data_tools(
        self,
        *,
        root_dir: str | Path,
        max_file_bytes: int = 25_000_000,
        max_rows: int = 50_000,
        max_columns: int = 500,
        max_operations: int = 30,
    ) -> None:
        """Install bounded CSV/JSON/XML/XLSX I/O, validation and declarative ETL."""
        from ultk.builtins.structured_data import create_structured_data_tools
        self.register_tools(create_structured_data_tools(
            root_dir=root_dir,
            max_file_bytes=max_file_bytes,
            max_rows=max_rows,
            max_columns=max_columns,
            max_operations=max_operations,
        ))


    def install_database_tools(
        self,
        profiles: dict[str, dict[str, Any]],
        *,
        max_rows: int = 500,
        max_result_bytes: int = 100_000,
        max_batch: int = 100,
    ) -> None:
        """Install optional SQL, MongoDB and Redis tools.

        Profiles are trusted host configuration. Keep credentials in a secret manager
        or inject them from environment-backed configuration; never expose them to a model.
        """
        from ultk.builtins.database import create_database_tools
        self.register_tools(create_database_tools(
            profiles,
            max_rows=max_rows,
            max_result_bytes=max_result_bytes,
            max_batch=max_batch,
        ))

    def install_memory_tools(
        self,
        *,
        database: str | Path = "./ultk_memory.sqlite3",
        namespace: str,
        embedder: Any = None,
        extractor: Any = None,
        summarizer: Any = None,
        max_items: int = 100_000,
        max_context_entries: int = 100,
        max_candidates: int = 30,
        auto_extract_every: int | None = 4,
        auto_summarize_every: int | None = 20,
    ) -> None:
        """Install persistent memory with optional automatic host-adapted intelligence.

        When adapters are supplied, user context appends trigger extraction and summaries
        at the configured user-message intervals. Set either interval to None to disable
        that automatic hook; the explicit memory intelligence tools remain available.
        """
        import sqlite3

        from ultk.builtins.memory import PersistentMemory, create_memory_tools
        from ultk.builtins.memory_intelligence import (
            MemoryIntelligence,
            create_memory_intelligence_tools,
        )
        from ultk.exceptions import ToolExecutionError

        for name, interval in (
            ("auto_extract_every", auto_extract_every),
            ("auto_summarize_every", auto_summarize_every),
        ):
            if interval is not None and (isinstance(interval, bool) or not isinstance(interval, int) or interval < 1):
                raise ValueError(f"{name} must be a positive integer or None.")

        store = PersistentMemory(
            database, namespace=namespace, embedder=embedder, max_items=max_items,
        )
        intelligence = MemoryIntelligence(
            store,
            extractor=extractor,
            summarizer=summarizer,
            max_context_entries=max_context_entries,
            max_candidates=max_candidates,
        )

        def after_context_append(*, session_id: str, role: str, content: str) -> dict[str, Any]:
            if role != "user":
                return {}
            with store.db() as connection:
                row = connection.execute(
                    "SELECT user_messages FROM memory_session_stats WHERE ns=? AND sid=?",
                    (store.namespace, session_id),
                ).fetchone()
            user_messages = int(row["user_messages"]) if row is not None else 0
            outcome: dict[str, Any] = {}
            if extractor is not None and auto_extract_every and user_messages % auto_extract_every == 0:
                try:
                    outcome["extraction"] = intelligence.extract_context(
                        session_id=session_id, limit=min(max_context_entries, 200),
                    )
                except (ToolExecutionError, sqlite3.Error) as exc:
                    outcome["extraction_error"] = type(exc).__name__
            if summarizer is not None and auto_summarize_every and user_messages % auto_summarize_every == 0:
                try:
                    outcome["summary"] = intelligence.summarize_context(
                        session_id=session_id, limit=min(max_context_entries, 200),
                    )
                except (ToolExecutionError, sqlite3.Error) as exc:
                    outcome["summary_error"] = type(exc).__name__
            return outcome

        self.register_tools(create_memory_tools(
            database,
            namespace=namespace,
            embedder=embedder,
            max_items=max_items,
            store=store,
            after_context_append=after_context_append,
        ))
        self.register_tools(create_memory_intelligence_tools(
            store,
            extractor=extractor,
            summarizer=summarizer,
            max_context_entries=max_context_entries,
            max_candidates=max_candidates,
        ))

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

    def install_email_tools(self, **configuration: Any) -> None:
        from ultk.builtins.communications import create_email_tools
        self.register_tools(create_email_tools(**configuration))

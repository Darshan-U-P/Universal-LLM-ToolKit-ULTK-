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
                 policy: PermissionPolicy | None = None) -> None:
        self.registry = registry or ToolRegistry()
        self.policy = policy or DenyAllPolicy()
        self.dispatcher = ToolDispatcher(self.registry, self.policy)

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
    ) -> None:
        """Install persistent memory plus optional host-adapted intelligence.

        The namespace must come from authenticated host identity, never model input.
        Embedding, extraction and summarization adapters are trusted host callables;
        provider credentials and model configuration are not exposed to tools.
        """
        from ultk.builtins.memory import PersistentMemory, create_memory_tools
        from ultk.builtins.memory_intelligence import create_memory_intelligence_tools

        self.register_tools(create_memory_tools(
            database, namespace=namespace, embedder=embedder, max_items=max_items,
        ))
        store = PersistentMemory(
            database, namespace=namespace, embedder=embedder, max_items=max_items,
        )
        self.register_tools(create_memory_intelligence_tools(
            store,
            extractor=extractor,
            summarizer=summarizer,
            max_context_entries=max_context_entries,
            max_candidates=max_candidates,
        ))

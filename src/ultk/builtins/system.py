"""Cross-platform, read-only operating-system and process inspection tools."""

from __future__ import annotations

import asyncio
import platform
from typing import Any

import psutil

from ultk.exceptions import ToolExecutionError
from ultk.models import ToolContext, ToolSpec


class PlatformInfoTool:
    spec = ToolSpec(
        name="system.get_platform_info",
        description="Return basic operating-system, Python, CPU, and memory information.",
        input_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        capabilities=frozenset({"system:read"}),
    )

    async def invoke(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return await asyncio.to_thread(self._collect)

    @staticmethod
    def _collect() -> dict[str, Any]:
        memory = psutil.virtual_memory()
        return {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
            "logical_cpu_count": psutil.cpu_count(logical=True),
            "physical_cpu_count": psutil.cpu_count(logical=False),
            "memory_total_bytes": memory.total,
            "memory_available_bytes": memory.available,
        }


class ListProcessesTool:
    spec = ToolSpec(
        name="system.list_processes",
        description=(
            "List running processes with PID, name, status, and resident memory. "
            "Does not return command lines, environment variables, or user data."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name_contains": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "additionalProperties": False,
        },
        capabilities=frozenset({"system:read"}),
        max_output_chars=20_000,
    )

    async def invoke(self, arguments: dict[str, Any], context: ToolContext) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self._collect,
            arguments.get("name_contains", ""),
            arguments.get("limit", 50),
        )

    @staticmethod
    def _collect(name_contains: str, limit: int) -> list[dict[str, Any]]:
        needle = name_contains.casefold()
        results: list[dict[str, Any]] = []
        for process in psutil.process_iter(["pid", "name", "status", "memory_info"]):
            if len(results) >= limit:
                break
            try:
                info = process.info
                name = info.get("name") or ""
                if needle and needle not in name.casefold():
                    continue
                memory_info = info.get("memory_info")
                results.append({
                    "pid": info["pid"],
                    "name": name,
                    "status": info.get("status"),
                    "memory_rss_bytes": memory_info.rss if memory_info else None,
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return results


class ProcessInfoTool:
    spec = ToolSpec(
        name="system.get_process_info",
        description="Get basic metadata for one process by PID, without command-line or environment data.",
        input_schema={
            "type": "object",
            "properties": {"pid": {"type": "integer", "minimum": 1}},
            "required": ["pid"],
            "additionalProperties": False,
        },
        capabilities=frozenset({"system:read"}),
    )

    async def invoke(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return await asyncio.to_thread(self._collect, arguments["pid"])

    @staticmethod
    def _collect(pid: int) -> dict[str, Any]:
        try:
            process = psutil.Process(pid)
            with process.oneshot():
                memory = process.memory_info()
                return {
                    "pid": process.pid,
                    "name": process.name(),
                    "status": process.status(),
                    "memory_rss_bytes": memory.rss,
                    "memory_vms_bytes": memory.vms,
                    "created_at": process.create_time(),
                }
        except psutil.NoSuchProcess as exc:
            raise ToolExecutionError(f"No process exists with PID {pid}.") from exc
        except (psutil.AccessDenied, psutil.ZombieProcess) as exc:
            raise ToolExecutionError(f"Access to process {pid} is unavailable.") from exc


def create_system_tools() -> tuple[PlatformInfoTool, ListProcessesTool, ProcessInfoTool]:
    """Create the read-only system inspection tool pack."""
    return PlatformInfoTool(), ListProcessesTool(), ProcessInfoTool()

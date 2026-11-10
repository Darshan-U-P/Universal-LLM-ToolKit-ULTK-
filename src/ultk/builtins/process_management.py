"""Explicitly permissioned process control tools."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import psutil

from ultk.exceptions import ToolExecutionError
from ultk.models import ToolContext, ToolSpec


def _get_verified_process(pid: int, expected_create_time: float) -> psutil.Process:
    if pid == os.getpid():
        raise ToolExecutionError("ULTK cannot control its own host process.")
    try:
        process = psutil.Process(pid)
        actual = process.create_time()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as exc:
        raise ToolExecutionError(f"Process {pid} is unavailable.") from exc
    if abs(actual - expected_create_time) > 0.01:
        raise ToolExecutionError("PID identity check failed; the PID may have been reused.")
    return process


class TerminateProcessTool:
    spec = ToolSpec(
        name="process.terminate",
        description=(
            "Request termination of a process only when its PID and previously observed "
            "creation timestamp match. Force-kill is separately requested."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "pid": {"type": "integer", "minimum": 1},
                "expected_create_time": {"type": "number", "minimum": 0},
                "force": {"type": "boolean", "default": False},
            },
            "required": ["pid", "expected_create_time"],
            "additionalProperties": False,
        },
        capabilities=frozenset({"process:terminate"}),
        timeout_seconds=8,
    )

    async def invoke(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return await asyncio.to_thread(self._terminate, arguments)

    @staticmethod
    def _terminate(arguments: dict[str, Any]) -> dict[str, Any]:
        pid = arguments["pid"]
        process = _get_verified_process(pid, arguments["expected_create_time"])
        try:
            if arguments.get("force", False):
                process.kill()
                action = "kill_requested"
            else:
                process.terminate()
                action = "termination_requested"
            try:
                process.wait(timeout=3)
                return {"pid": pid, "action": action, "status": "exited"}
            except psutil.TimeoutExpired:
                return {"pid": pid, "action": action, "status": "still_running"}
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            raise ToolExecutionError(f"Unable to control process {pid}.") from exc


class SuspendProcessTool:
    spec = ToolSpec(
        name="process.suspend",
        description="Suspend a process after verifying its PID and creation timestamp.",
        input_schema={
            "type": "object",
            "properties": {
                "pid": {"type": "integer", "minimum": 1},
                "expected_create_time": {"type": "number", "minimum": 0},
            },
            "required": ["pid", "expected_create_time"],
            "additionalProperties": False,
        },
        capabilities=frozenset({"process:suspend"}),
    )

    async def invoke(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return await asyncio.to_thread(self._change_state, arguments, "suspend")

    @staticmethod
    def _change_state(arguments: dict[str, Any], action: str) -> dict[str, Any]:
        process = _get_verified_process(arguments["pid"], arguments["expected_create_time"])
        try:
            getattr(process, action)()
            return {"pid": process.pid, "status": "suspended"}
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as exc:
            raise ToolExecutionError(f"Unable to suspend process {process.pid}.") from exc


class ResumeProcessTool:
    spec = ToolSpec(
        name="process.resume",
        description="Resume a suspended process after verifying its PID and creation timestamp.",
        input_schema={
            "type": "object",
            "properties": {
                "pid": {"type": "integer", "minimum": 1},
                "expected_create_time": {"type": "number", "minimum": 0},
            },
            "required": ["pid", "expected_create_time"],
            "additionalProperties": False,
        },
        capabilities=frozenset({"process:resume"}),
    )

    async def invoke(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return await asyncio.to_thread(self._change_state, arguments, "resume")

    @staticmethod
    def _change_state(arguments: dict[str, Any], action: str) -> dict[str, Any]:
        process = _get_verified_process(arguments["pid"], arguments["expected_create_time"])
        try:
            getattr(process, action)()
            return {"pid": process.pid, "status": "running"}
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as exc:
            raise ToolExecutionError(f"Unable to resume process {process.pid}.") from exc


def create_process_management_tools() -> tuple[
    TerminateProcessTool, SuspendProcessTool, ResumeProcessTool
]:
    """Create the explicit process-control tool pack."""
    return TerminateProcessTool(), SuspendProcessTool(), ResumeProcessTool()

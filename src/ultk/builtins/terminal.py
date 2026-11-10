"""Restricted, shell-free command execution for explicitly approved executables."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import psutil

from ultk.exceptions import ToolExecutionError
from ultk.models import ToolContext, ToolSpec


async def _read_capped(stream: asyncio.StreamReader, limit: int) -> bytes:
    chunks: list[bytes] = []
    remaining = limit
    while True:
        chunk = await stream.read(64 * 1024)
        if not chunk:
            break
        if remaining > 0:
            kept = chunk[:remaining]
            chunks.append(kept)
            remaining -= len(kept)
    return b"".join(chunks)


def _kill_process_tree(pid: int) -> None:
    """Best-effort termination of a child process tree; never signals unrelated PIDs."""
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    children = parent.children(recursive=True)
    for child in reversed(children):
        try:
            child.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    try:
        parent.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    psutil.wait_procs([*children, parent], timeout=2)


class CommandExecutionTool:
    """Run only configured executables, with argv (never a shell command string)."""

    def __init__(
        self,
        working_root: str | Path,
        allowed_executables: Mapping[str, str | Path],
        *,
        timeout_seconds: float = 15.0,
        max_output_bytes: int = 64_000,
        allowed_environment: frozenset[str] = frozenset(),
    ) -> None:
        self.working_root = Path(working_root).expanduser().resolve()
        if not self.working_root.is_dir():
            raise ValueError("working_root must be an existing directory")
        if not 0 < timeout_seconds <= 120:
            raise ValueError("timeout_seconds must be between 0 and 120")
        if not 1 <= max_output_bytes <= 1_000_000:
            raise ValueError("max_output_bytes must be between 1 and 1000000")
        if not allowed_executables:
            raise ValueError("at least one explicitly allowed executable is required")

        resolved: dict[str, str] = {}
        for alias, executable in allowed_executables.items():
            path = Path(executable).expanduser().resolve(strict=True)
            if not path.is_file():
                raise ValueError(f"allowed executable is not a file: {alias}")
            resolved[alias] = str(path)
        self.allowed_executables = resolved
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.environment = {
            key: value for key, value in os.environ.items() if key in allowed_environment
        }

        self.spec = ToolSpec(
            name="terminal.execute",
            description=(
                "Execute an approved executable by alias with a separate argument array. "
                "No shell parsing, pipelines, redirection, or implicit command lookup is used."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "executable": {"type": "string", "enum": sorted(resolved)},
                    "args": {
                        "type": "array",
                        "items": {"type": "string", "maxLength": 4096},
                        "maxItems": 128,
                    },
                    "cwd": {"type": "string", "maxLength": 2048},
                    "timeout_seconds": {
                        "type": "number",
                        "exclusiveMinimum": 0,
                        "maximum": timeout_seconds,
                    },
                },
                "required": ["executable", "args"],
                "additionalProperties": False,
            },
            capabilities=frozenset({"terminal:execute"}),
            timeout_seconds=timeout_seconds + 5,
            max_output_chars=max_output_bytes * 2 + 1000,
        )

    def _resolve_cwd(self, value: str | None) -> Path:
        candidate = self.working_root if not value else (
            self.working_root / value
        ).resolve()
        if not candidate.is_relative_to(self.working_root) or not candidate.is_dir():
            raise ToolExecutionError("Working directory must be an existing directory inside the configured root.")
        return candidate

    async def invoke(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        alias = arguments["executable"]
        executable = self.allowed_executables.get(alias)
        if executable is None:
            raise ToolExecutionError("Executable is not allowlisted.")
        cwd = self._resolve_cwd(arguments.get("cwd"))
        timeout = min(float(arguments.get("timeout_seconds", self.timeout_seconds)), self.timeout_seconds)
        argv = [executable, *arguments["args"]]
        if any("\x00" in item for item in argv):
            raise ToolExecutionError("Arguments cannot contain NUL characters.")

        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(cwd),
                env=self.environment,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                shell=False,
            )
        except (OSError, ValueError) as exc:
            raise ToolExecutionError(f"Could not start approved executable ({type(exc).__name__}).") from exc

        assert process.stdout is not None and process.stderr is not None
        stdout_task = asyncio.create_task(_read_capped(process.stdout, self.max_output_bytes))
        stderr_task = asyncio.create_task(_read_capped(process.stderr, self.max_output_bytes))
        timed_out = False
        try:
            await asyncio.wait_for(process.wait(), timeout=timeout)
        except TimeoutError:
            timed_out = True
            await asyncio.to_thread(_kill_process_tree, process.pid)
            await process.wait()
        except asyncio.CancelledError:
            await asyncio.to_thread(_kill_process_tree, process.pid)
            await process.wait()
            stdout_task.cancel()
            stderr_task.cancel()
            raise

        stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
        return {
            "executable": alias,
            "return_code": process.returncode,
            "timed_out": timed_out,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "output_limit_bytes_per_stream": self.max_output_bytes,
            "output_may_be_truncated": len(stdout) >= self.max_output_bytes or len(stderr) >= self.max_output_bytes,
        }


def create_terminal_tools(
    working_root: str | Path,
    allowed_executables: Mapping[str, str | Path],
    **options: Any,
) -> tuple[CommandExecutionTool, ...]:
    """Create the configured terminal tool pack."""
    return (CommandExecutionTool(working_root, allowed_executables, **options),)

"""Root-confined filesystem tools."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any

from ultk.exceptions import ToolExecutionError
from ultk.models import ToolContext, ToolSpec


class _FilesystemTool:
    def __init__(self, root_dir: str | Path, max_file_bytes: int) -> None:
        self.root_dir = Path(root_dir).expanduser().resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        if max_file_bytes < 1:
            raise ValueError("max_file_bytes must be positive.")
        self.max_file_bytes = max_file_bytes

    def resolve(self, user_path: str) -> Path:
        """Resolve a user path and reject traversal or symlink escapes."""
        if not user_path or not isinstance(user_path, str):
            raise ToolExecutionError("A non-empty relative path is required.")
        candidate = Path(user_path)
        if candidate.is_absolute():
            raise ToolExecutionError("Absolute paths are not permitted.")
        resolved = (self.root_dir / candidate).resolve()
        if not resolved.is_relative_to(self.root_dir):
            raise ToolExecutionError("Path escapes the configured filesystem root.")
        return resolved


class ReadFileTool(_FilesystemTool):
    spec = ToolSpec(
        name="filesystem.read_file",
        description="Read a UTF-8 text file inside the configured filesystem root.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string", "minLength": 1}},
            "required": ["path"],
            "additionalProperties": False,
        },
        capabilities=frozenset({"filesystem:read"}),
    )

    async def invoke(self, arguments: dict[str, Any], context: ToolContext) -> str:
        return await asyncio.to_thread(self._read, arguments["path"])

    def _read(self, user_path: str) -> str:
        path = self.resolve(user_path)
        if not path.is_file():
            raise ToolExecutionError("The requested path is not a regular file.")
        if path.stat().st_size > self.max_file_bytes:
            raise ToolExecutionError("File exceeds the configured read-size limit.")
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ToolExecutionError("File is not valid UTF-8 text.") from exc


class WriteFileTool(_FilesystemTool):
    spec = ToolSpec(
        name="filesystem.write_file",
        description="Create or replace a UTF-8 text file inside the configured root.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "minLength": 1},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
        capabilities=frozenset({"filesystem:write"}),
    )

    async def invoke(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._write, arguments["path"], arguments["content"]
        )

    def _write(self, user_path: str, content: str) -> dict[str, Any]:
        path = self.resolve(user_path)
        if path.exists() and path.is_dir():
            raise ToolExecutionError("Cannot write file content to a directory.")
        encoded = content.encode("utf-8")
        if len(encoded) > self.max_file_bytes:
            raise ToolExecutionError("Content exceeds the configured write-size limit.")
        if not path.parent.is_dir():
            raise ToolExecutionError("Parent directory does not exist.")
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=path.parent, prefix=".ultk-", delete=False
            ) as temporary:
                temporary.write(encoded)
                temporary_path = temporary.name
            os.replace(temporary_path, path)
        finally:
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)
        return {"path": user_path, "bytes_written": len(encoded)}


class ListDirectoryTool(_FilesystemTool):
    spec = ToolSpec(
        name="filesystem.list_directory",
        description="List entries in a directory inside the configured filesystem root.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string", "default": "."}},
            "additionalProperties": False,
        },
        capabilities=frozenset({"filesystem:read"}),
    )

    async def invoke(self, arguments: dict[str, Any], context: ToolContext) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list, arguments.get("path", "."))

    def _list(self, user_path: str) -> list[dict[str, Any]]:
        path = self.resolve(user_path)
        if not path.is_dir():
            raise ToolExecutionError("The requested path is not a directory.")
        entries = []
        for item in sorted(path.iterdir(), key=lambda entry: entry.name.casefold()):
            resolved = item.resolve()
            if not resolved.is_relative_to(self.root_dir):
                continue
            entries.append({
                "name": item.name,
                "type": "directory" if item.is_dir() else "file",
                "size_bytes": item.stat().st_size if item.is_file() else None,
            })
        return entries


class CreateDirectoryTool(_FilesystemTool):
    spec = ToolSpec(
        name="filesystem.create_directory",
        description="Create a directory inside the configured filesystem root.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string", "minLength": 1}},
            "required": ["path"],
            "additionalProperties": False,
        },
        capabilities=frozenset({"filesystem:write"}),
    )

    async def invoke(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, str]:
        return await asyncio.to_thread(self._create, arguments["path"])

    def _create(self, user_path: str) -> dict[str, str]:
        path = self.resolve(user_path)
        path.mkdir(parents=True, exist_ok=True)
        return {"path": user_path, "status": "created"}


class StatPathTool(_FilesystemTool):
    spec = ToolSpec(
        name="filesystem.stat",
        description="Return basic metadata for a file or directory inside the root.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string", "minLength": 1}},
            "required": ["path"],
            "additionalProperties": False,
        },
        capabilities=frozenset({"filesystem:read"}),
    )

    async def invoke(self, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return await asyncio.to_thread(self._stat, arguments["path"])

    def _stat(self, user_path: str) -> dict[str, Any]:
        path = self.resolve(user_path)
        if not path.exists():
            raise ToolExecutionError("The requested path does not exist.")
        stat = path.stat()
        return {
            "path": user_path,
            "type": "directory" if path.is_dir() else "file",
            "size_bytes": stat.st_size,
            "modified_time": stat.st_mtime,
        }


def create_filesystem_tools(
    root_dir: str | Path,
    *,
    max_file_bytes: int = 2_000_000,
) -> tuple[_FilesystemTool, ...]:
    """Create filesystem tools sharing one confined root and size limit."""
    return (
        ReadFileTool(root_dir, max_file_bytes),
        WriteFileTool(root_dir, max_file_bytes),
        ListDirectoryTool(root_dir, max_file_bytes),
        CreateDirectoryTool(root_dir, max_file_bytes),
        StatPathTool(root_dir, max_file_bytes),
    )

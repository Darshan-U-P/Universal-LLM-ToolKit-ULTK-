"""Development, source-analysis, Git and test/build tools."""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from ultk.builtins._common import FunctionTool, object_schema
from ultk.exceptions import ToolExecutionError


def _rooted(root_dir: str, relative_path: str) -> Path:
    root = Path(root_dir).expanduser().resolve()
    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise ToolExecutionError("Absolute paths are not accepted.")
    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root):
        raise ToolExecutionError("Path escapes configured project root.")
    return resolved


def _read_source(path: str, root_dir: str) -> dict[str, Any]:
    target = _rooted(root_dir, path)
    if not target.is_file() or target.stat().st_size > 1_000_000:
        raise ToolExecutionError("Source file is missing or exceeds 1 MB.")
    return {"path": path, "content": target.read_text(encoding="utf-8")}


def _write_source(path: str, content: str, root_dir: str) -> dict[str, Any]:
    target = _rooted(root_dir, path)
    encoded = content.encode("utf-8")
    if len(encoded) > 500_000:
        raise ToolExecutionError("Source content exceeds 500 KB.")
    if not target.parent.is_dir():
        raise ToolExecutionError("Parent directory must already exist.")
    if target.exists() and not target.is_file():
        raise ToolExecutionError("Target is not a regular file.")
    target.write_bytes(encoded)
    return {"path": path, "bytes_written": len(encoded)}


def _analyze_python(path: str, root_dir: str) -> dict[str, Any]:
    target = _rooted(root_dir, path)
    if target.suffix != ".py" or not target.is_file() or target.stat().st_size > 1_000_000:
        raise ToolExecutionError("Expected a Python source file no larger than 1 MB.")
    source = target.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return {"path": path, "valid": False, "error": exc.msg,
                "line": exc.lineno, "offset": exc.offset}
    imports, functions, classes = [], [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append({"name": node.name, "line": node.lineno})
        elif isinstance(node, ast.ClassDef):
            classes.append({"name": node.name, "line": node.lineno})
    return {"path": path, "valid": True, "lines": len(source.splitlines()),
            "imports": sorted(set(imports)), "functions": functions, "classes": classes}


def _run_command(args: list[str], root_dir: str, timeout_seconds: int = 20,
                 max_output_bytes: int = 30000) -> dict[str, Any]:
    root = Path(root_dir).expanduser().resolve()
    if not root.is_dir() or not 1 <= timeout_seconds <= 60:
        raise ToolExecutionError("Invalid project root or timeout.")
    try:
        completed = subprocess.run(args, cwd=root, shell=False, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   timeout=timeout_seconds, check=False,
                                   env={"PATH": os.environ.get("PATH", ""),
                                        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
                                        "WINDIR": os.environ.get("WINDIR", "")})
    except subprocess.TimeoutExpired as exc:
        raise ToolExecutionError("Development command timed out.") from exc
    except OSError as exc:
        raise ToolExecutionError(f"Unable to start command ({type(exc).__name__}).") from exc
    return {"return_code": completed.returncode,
            "stdout": completed.stdout[:max_output_bytes].decode("utf-8", errors="replace"),
            "stderr": completed.stderr[:max_output_bytes].decode("utf-8", errors="replace"),
            "output_truncated": len(completed.stdout) > max_output_bytes or len(completed.stderr) > max_output_bytes}


def _git(action: str, root_dir: str, revision: str | None = None) -> dict[str, Any]:
    commands = {"status": ["git", "status", "--short", "--branch"],
                "log": ["git", "log", "-5", "--oneline", "--decorate"],
                "diff": ["git", "diff", "--stat"]}
    if action not in commands:
        raise ToolExecutionError("Only read-only Git status/log/diff actions are enabled.")
    args = commands[action]
    if revision is not None:
        if action != "log" or not revision.replace("/", "").replace("-", "").replace("_", "").isalnum():
            raise ToolExecutionError("Revision selector is not valid for this operation.")
        args = ["git", "log", "-5", "--oneline", revision]
    return _run_command(args, root_dir, 15)


def _python_compile(path: str, root_dir: str) -> dict[str, Any]:
    target = _rooted(root_dir, path)
    if target.suffix != ".py" or not target.is_file():
        raise ToolExecutionError("Compilation target must be an existing .py file.")
    return _run_command([sys.executable, "-m", "py_compile", str(target)], root_dir, 20)


def _run_tests(test_path: str, root_dir: str) -> dict[str, Any]:
    target = _rooted(root_dir, test_path)
    if not target.exists():
        raise ToolExecutionError("Test path does not exist.")
    return _run_command([sys.executable, "-m", "pytest", "-q", str(target)], root_dir, 60)


def _run_allowlisted(alias: str, args: list[str], root_dir: str,
                     allowed_executables: dict[str, str]) -> dict[str, Any]:
    executable = allowed_executables.get(alias)
    if not executable:
        raise ToolExecutionError("Executable alias is not allowlisted.")
    if len(args) > 64 or any(not isinstance(item, str) or len(item) > 2000 or "\x00" in item for item in args):
        raise ToolExecutionError("Argument list is invalid or too large.")
    path = Path(executable).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ToolExecutionError("Configured executable is not a file.")
    return _run_command([str(path), *args], root_dir, 60)


def create_development_tools(*, project_root: str | Path,
                             allowed_executables: dict[str, str] | None = None) -> tuple[FunctionTool, ...]:
    """Create project-scoped development tools.

    Code execution, build/test commands and package-manager aliases execute with host-user
    privileges. Only configure trusted commands and use an external OS/container sandbox for
    untrusted model-authored code. Package installation and Git writes are deliberately omitted.
    """
    root = str(Path(project_root).expanduser().resolve())
    executables = dict(allowed_executables or {})
    return (
        FunctionTool("development.read_file", "Read a UTF-8 source file inside project_root.",
                     object_schema({"path": {"type": "string", "minLength": 1}}, ["path"]),
                     "development:read", lambda path: _read_source(path, root)),
        FunctionTool("development.write_file", "Create or replace a source file inside project_root.",
                     object_schema({"path": {"type": "string", "minLength": 1},
                                    "content": {"type": "string", "maxLength": 500000}},
                                   ["path", "content"]),
                     "development:write", lambda path, content: _write_source(path, content, root)),
        FunctionTool("development.analyze_python", "Parse Python source and report imports, classes, functions and syntax errors.",
                     object_schema({"path": {"type": "string", "minLength": 1}}, ["path"]),
                     "development:analyze", lambda path: _analyze_python(path, root)),
        FunctionTool("development.git", "Inspect Git status, recent log or diff summary (read-only).",
                     object_schema({"action": {"type": "string", "enum": ["status", "log", "diff"]},
                                    "revision": {"type": "string", "maxLength": 120}},
                                   ["action"]),
                     "development:git:read", lambda action, revision=None: _git(action, root, revision)),
        FunctionTool("development.compile_python", "Compile-check a Python file without executing its application code.",
                     object_schema({"path": {"type": "string", "minLength": 1}}, ["path"]),
                     "development:compile", lambda path: _python_compile(path, root)),
        FunctionTool("development.run_tests", "Run pytest against a project-relative test path.",
                     object_schema({"test_path": {"type": "string", "minLength": 1}}, ["test_path"]),
                     "development:test", lambda test_path: _run_tests(test_path, root), timeout=65),
        FunctionTool("development.run_command", "Run a configured executable alias with argv in project_root.",
                     object_schema({"alias": {"type": "string", "enum": sorted(executables)},
                                    "args": {"type": "array", "items": {"type": "string", "maxLength": 2000},
                                             "maxItems": 64}}, ["alias", "args"]),
                     "development:command", lambda alias, args: _run_allowlisted(alias, args, root, executables),
                     timeout=65),
    )

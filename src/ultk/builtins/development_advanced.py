"""Advanced development integrations: debugging, restricted REPL, compilers, packages,
Git mutations, builds, API checks, deployment targets, IDE launch and static analyzers.

All configured external commands execute with the ULTK host user's privileges. Use a dedicated
container/VM executor for untrusted repositories and model-authored code.
"""
from __future__ import annotations

import ast
import json
import operator
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from ultk.exceptions import ToolExecutionError
from ultk.builtins._common import FunctionTool, object_schema


def _rooted(root: str, relative: str, *, must_exist: bool = False) -> Path:
    base = Path(root).expanduser().resolve()
    candidate = Path(relative)
    if candidate.is_absolute():
        raise ToolExecutionError("Absolute paths are not accepted.")
    target = (base / candidate).resolve()
    if not target.is_relative_to(base):
        raise ToolExecutionError("Path escapes configured project root.")
    if must_exist and not target.is_file():
        raise ToolExecutionError("Project file does not exist.")
    return target


def _run(args: list[str], root: str, timeout: int = 60) -> dict[str, Any]:
    base = Path(root).resolve()
    try:
        result = subprocess.run(args, cwd=base, shell=False, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ToolExecutionError("Development operation timed out.") from exc
    except OSError as exc:
        raise ToolExecutionError(f"Unable to start configured tool ({type(exc).__name__}).") from exc
    return {"return_code": result.returncode,
            "stdout": result.stdout[:50000].decode("utf-8", errors="replace"),
            "stderr": result.stderr[:50000].decode("utf-8", errors="replace"),
            "output_truncated": len(result.stdout) > 50000 or len(result.stderr) > 50000}


class RestrictedInterpreter:
    """Small expression interpreter; deliberately not general-purpose Python exec."""
    _binary = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
               ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
               ast.Mod: operator.mod, ast.Pow: operator.pow}
    _compare = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
                ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge}
    @staticmethod
    def _safe_range(*args):
        sequence = range(*args)
        if len(sequence) > 10000:
            raise ToolExecutionError("Interpreter range is limited to 10000 values.")
        return list(sequence)

    _builtins = {"abs": abs, "round": round, "min": min, "max": max,
                 "sum": sum, "len": len, "sorted": sorted,
                 "range": _safe_range.__func__}

    def __init__(self):
        self.sessions: dict[str, dict[str, Any]] = {}

    def execute(self, session_id: str, source: str) -> dict[str, Any]:
        if not session_id or len(session_id) > 80 or len(source) > 2000:
            raise ToolExecutionError("Invalid session identifier or statement size.")
        if session_id not in self.sessions and len(self.sessions) >= 1000:
            raise ToolExecutionError("Interpreter session limit reached.")
        env = self.sessions.setdefault(session_id, {})
        if len(env) >= 100 and "=" in source and source.split("=", 1)[0].strip() not in env:
            raise ToolExecutionError("Interpreter variable limit reached.")
        try:
            tree = ast.parse(source, mode="exec")
            if len(tree.body) != 1:
                raise ToolExecutionError("Submit exactly one expression or assignment per call.")
            node = tree.body[0]
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if name.startswith("_"):
                    raise ToolExecutionError("Private variable names are not allowed.")
                env[name] = self._eval(node.value, env)
                value = env[name]
            elif isinstance(node, ast.Expr):
                value = self._eval(node.value, env)
            else:
                raise ToolExecutionError("Only expressions and simple variable assignments are supported.")
            json.dumps(value)
            return {"value": value, "variables": sorted(env)}
        except ToolExecutionError:
            raise
        except Exception as exc:  # noqa: BLE001 - interpreter input is untrusted
            raise ToolExecutionError(f"Restricted interpreter error ({type(exc).__name__}).") from exc

    def _eval(self, node, env):
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float, bool, type(None))):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in env:
                return env[node.id]
            if node.id in self._builtins:
                return self._builtins[node.id]
            raise ToolExecutionError(f"Unknown variable: {node.id}")
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            values = [self._eval(v, env) for v in node.elts]
            return values if not isinstance(node, ast.Tuple) else tuple(values)
        if isinstance(node, ast.Dict):
            return {self._eval(k, env): self._eval(v, env) for k, v in zip(node.keys, node.values)}
        if isinstance(node, ast.BinOp) and type(node.op) in self._binary:
            left, right = self._eval(node.left, env), self._eval(node.right, env)
            if isinstance(node.op, ast.Mult):
                if isinstance(left, (str, list, tuple)) and isinstance(right, int) and len(left) * max(0, right) > 10000:
                    raise ToolExecutionError("Interpreter multiplication result is too large.")
                if isinstance(right, (str, list, tuple)) and isinstance(left, int) and len(right) * max(0, left) > 10000:
                    raise ToolExecutionError("Interpreter multiplication result is too large.")
            if isinstance(node.op, ast.Pow) and (not isinstance(right, (int, float)) or abs(right) > 12):
                raise ToolExecutionError("Exponent is too large.")
            result = self._binary[type(node.op)](left, right)
            if isinstance(result, (str, list, tuple, dict)) and len(result) > 10000:
                raise ToolExecutionError("Interpreter result collection is too large.")
            if isinstance(result, int) and result.bit_length() > 4096:
                raise ToolExecutionError("Interpreter integer result is too large.")
            return result
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub, ast.Not)):
            value = self._eval(node.operand, env)
            return +value if isinstance(node.op, ast.UAdd) else (-value if isinstance(node.op, ast.USub) else not value)
        if isinstance(node, ast.Subscript):
            return self._eval(node.value, env)[self._eval(node.slice, env)]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in self._builtins:
            args = [self._eval(arg, env) for arg in node.args]
            if node.keywords:
                raise ToolExecutionError("Keyword arguments are not supported.")
            if any(isinstance(arg, (str, list, tuple, dict)) and len(arg) > 1000 for arg in args):
                raise ToolExecutionError("Interpreter collection input is too large.")
            return self._builtins[node.func.id](*args)
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in self._compare:
            return self._compare[type(node.ops[0])](self._eval(node.left, env), self._eval(node.comparators[0], env))
        raise ToolExecutionError(f"Unsupported syntax: {type(node).__name__}")

    def clear(self, session_id: str) -> dict[str, Any]:
        self.sessions.pop(session_id, None)
        return {"session_id": session_id, "cleared": True}


def _git_write(action: str, root: str, branch: str | None = None,
               paths: list[str] | None = None, message: str | None = None,
               remote: str | None = None, allowed_remotes: tuple[str, ...] = ()) -> dict[str, Any]:
    if action in {"create_branch", "checkout"}:
        if not branch or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,100}", branch) or ".." in branch:
            raise ToolExecutionError("Invalid Git branch name.")
        args = ["git", "switch", "-c" if action == "create_branch" else "", branch]
        if action == "checkout":
            args = ["git", "switch", branch]
    elif action == "stage":
        if not paths or len(paths) > 50:
            raise ToolExecutionError("Stage requires 1–50 project-relative paths.")
        safe = []
        for item in paths:
            if not re.fullmatch(r"[A-Za-z0-9_./-]{1,240}", item) or item.startswith("-"):
                raise ToolExecutionError("Invalid Git pathspec.")
            _rooted(root, item)
            safe.append(item)
        args = ["git", "add", "--", *safe]
    elif action == "commit":
        if not message or not message.strip() or len(message) > 300:
            raise ToolExecutionError("Commit message must contain 1–300 characters.")
        args = ["git", "commit", "-m", message]
    elif action == "push":
        if remote not in allowed_remotes or not branch:
            raise ToolExecutionError("Push requires a configured remote and explicit branch.")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,100}", branch) or ".." in branch:
            raise ToolExecutionError("Invalid branch name.")
        args = ["git", "push", "--", remote, branch]
    else:
        raise ToolExecutionError("Unsupported Git mutation.")
    return _run(args, root, 90)


def _compile(alias: str, source: str, output: str, root: str,
             compilers: dict[str, dict[str, Any]]) -> dict[str, Any]:
    config = compilers.get(alias)
    if not config:
        raise ToolExecutionError("Compiler alias is not configured.")
    src, out = _rooted(root, source, must_exist=True), _rooted(root, output)
    if not out.parent.is_dir():
        raise ToolExecutionError("Output directory must exist.")
    template = config.get("args", ["{source}", "-o", "{output}"])
    if not isinstance(template, list) or any(x not in {"{source}", "{output}"} and not isinstance(x, str) for x in template):
        raise ToolExecutionError("Compiler argument template is invalid.")
    args = [str(Path(config["path"]).expanduser().resolve(strict=True))]
    args.extend(str(item).replace("{source}", str(src)).replace("{output}", str(out)) for item in template)
    return _run(args, root, 120)


def _package(action: str, manager: str, package: str, root: str,
             managers: dict[str, dict[str, str]]) -> dict[str, Any]:
    cfg = managers.get(manager)
    if not cfg or action not in {"install", "remove", "list"}:
        raise ToolExecutionError("Package manager or action is not configured.")
    if action != "list" and (package.startswith("-") or not re.fullmatch(r"[A-Za-z0-9@._/-]{1,160}", package)):
        raise ToolExecutionError("Package identifier is invalid.")
    exe = str(Path(cfg["path"]).expanduser().resolve(strict=True))
    ecosystem = cfg.get("ecosystem")
    if ecosystem == "pip":
        args = [exe, "list"] if action == "list" else [exe, "uninstall", "-y", package] if action == "remove" else [exe, "install", package]
    elif ecosystem == "npm":
        args = [exe, "ls", "--depth=0"] if action == "list" else [exe, "uninstall", package] if action == "remove" else [exe, "install", package]
    else:
        raise ToolExecutionError("Only configured pip and npm managers are supported.")
    return _run(args, root, 180)


def _debug_python(path: str, line: int, root: str) -> dict[str, Any]:
    target = _rooted(root, path, must_exist=True)
    if target.suffix != ".py" or not 1 <= line <= 1_000_000:
        raise ToolExecutionError("Debug target must be Python and line must be positive.")
    return _run([sys.executable, "-m", "pdb", "-c", f"break {target}:{line}",
                 "-c", "continue", str(target)], root, 60)


def _build(target: str, root: str, targets: dict[str, list[str]]) -> dict[str, Any]:
    args = targets.get(target)
    if not args:
        raise ToolExecutionError("Build target is not configured.")
    return _run(list(args), root, 300)


def _deploy(target: str, targets: dict[str, list[str]], root: str) -> dict[str, Any]:
    args = targets.get(target)
    if not args:
        raise ToolExecutionError("Deployment target is not configured.")
    return _run(list(args), root, 600)


def _api_request(url: str, method: str, body: dict[str, Any] | None,
                 allowed_hosts: tuple[str, ...]) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(url)
    local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if (parsed.scheme != "https" and not local_http) or parsed.hostname not in allowed_hosts or parsed.username or parsed.password:
        raise ToolExecutionError("API URL must use HTTPS (or HTTP on explicitly allowlisted loopback) and an allowlisted host.")
    if method not in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"}:
        raise ToolExecutionError("Unsupported HTTP method.")
    payload = None if body is None else json.dumps(body).encode()
    if payload and len(payload) > 100_000:
        raise ToolExecutionError("API request body exceeds 100 KB.")
    class AllowlistedRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            redirected = urllib.parse.urlparse(newurl)
            redirect_local_http = redirected.scheme == "http" and redirected.hostname in {"localhost", "127.0.0.1", "::1"}
            if (redirected.scheme != "https" and not redirect_local_http) or redirected.hostname not in allowed_hosts:
                raise ToolExecutionError("API redirect target is not allowlisted.")
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    request = urllib.request.Request(url, data=payload, method=method,
                                     headers={"Content-Type": "application/json",
                                              "Accept": "application/json"})
    try:
        opener = urllib.request.build_opener(AllowlistedRedirect())
        with opener.open(request, timeout=15) as response:
            final = urllib.parse.urlparse(response.geturl())
            final_local_http = final.scheme == "http" and final.hostname in {"localhost", "127.0.0.1", "::1"}
            if (final.scheme != "https" and not final_local_http) or final.hostname not in allowed_hosts:
                raise ToolExecutionError("Final API response host is not allowlisted.")
            data = response.read(100_001)
            return {"status": response.status, "headers": {
                "content_type": response.headers.get("Content-Type")},
                "body": data[:100000].decode("utf-8", errors="replace"),
                "truncated": len(data) > 100000}
    except urllib.error.HTTPError as exc:
        return {"status": exc.code, "body": exc.read(100000).decode("utf-8", errors="replace")}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ToolExecutionError(f"API request failed ({type(exc).__name__}).") from exc


def _ide_open(alias: str, path: str, line: int, root: str,
              ides: dict[str, str]) -> dict[str, Any]:
    exe = ides.get(alias)
    if not exe:
        raise ToolExecutionError("IDE alias is not configured.")
    target = _rooted(root, path, must_exist=True)
    binary = str(Path(exe).expanduser().resolve(strict=True))
    proc = subprocess.Popen([binary, "--goto", f"{target}:{line}"], cwd=root,
                            shell=False, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"pid": proc.pid, "file": path, "line": line, "status": "started"}


def _analyze(path: str, root: str, analyzer: str,
             analyzers: dict[str, dict[str, Any]]) -> dict[str, Any]:
    cfg = analyzers.get(analyzer)
    if not cfg:
        raise ToolExecutionError("Static analyzer alias is not configured.")
    target = _rooted(root, path, must_exist=True)
    binary = str(Path(cfg["path"]).expanduser().resolve(strict=True))
    prefix = cfg.get("args", [])
    if not isinstance(prefix, list) or any(not isinstance(v, str) for v in prefix):
        raise ToolExecutionError("Analyzer arguments must be a trusted string list.")
    return _run([binary, *prefix, str(target)], root, 120)


def create_advanced_development_tools(
    *, project_root: str | Path,
    compilers: dict[str, dict[str, Any]] | None = None,
    package_managers: dict[str, dict[str, str]] | None = None,
    build_targets: dict[str, list[str]] | None = None,
    deployment_targets: dict[str, list[str]] | None = None,
    api_hosts: tuple[str, ...] = (),
    ides: dict[str, str] | None = None,
    analyzers: dict[str, dict[str, Any]] | None = None,
    allowed_git_remotes: tuple[str, ...] = (),
) -> tuple[FunctionTool, ...]:
    root = str(Path(project_root).expanduser().resolve())
    compilers, package_managers = dict(compilers or {}), dict(package_managers or {})
    build_targets, deployment_targets = dict(build_targets or {}), dict(deployment_targets or {})
    ides, analyzers = dict(ides or {}), dict(analyzers or {})
    repl = RestrictedInterpreter()
    tools = [
        FunctionTool("development.interpreter", "Evaluate one restricted Python expression or assignment in a named in-memory session.",
                     object_schema({"session_id": {"type": "string", "minLength": 1, "maxLength": 80},
                                    "source": {"type": "string", "minLength": 1, "maxLength": 2000}},
                                   ["session_id","source"]),
                     "development:interpreter", repl.execute),
        FunctionTool("development.interpreter_clear", "Clear a restricted interpreter session.",
                     object_schema({"session_id": {"type": "string", "minLength": 1, "maxLength": 80}},
                                   ["session_id"]),
                     "development:interpreter", repl.clear),
        FunctionTool("development.debug_python", "Run a Python script under pdb with a configured source-line breakpoint.",
                     object_schema({"path": {"type": "string", "minLength": 1},
                                    "line": {"type": "integer", "minimum": 1}}, ["path","line"]),
                     "development:debug", lambda path,line: _debug_python(path,line,root), timeout=65),
        FunctionTool("development.git_write", "Create/switch branches, stage paths, commit or push to an allowlisted remote.",
                     object_schema({"action": {"type": "string", "enum": ["create_branch","checkout","stage","commit","push"]},
                                    "branch": {"type": "string", "maxLength": 100},
                                    "paths": {"type": "array", "items": {"type": "string"}, "maxItems": 50},
                                    "message": {"type": "string", "maxLength": 300},
                                    "remote": {"type": "string", "maxLength": 100}}, ["action"]),
                     "development:git:write", lambda action,branch=None,paths=None,message=None,remote=None:
                     _git_write(action,root,branch,paths,message,remote,allowed_git_remotes), timeout=100),
        FunctionTool("development.compile", "Compile a source file with a host-configured compiler alias and fixed argument template.",
                     object_schema({"compiler": {"type": "string", "enum": sorted(compilers)},
                                    "source": {"type": "string", "minLength": 1},
                                    "output": {"type": "string", "minLength": 1}},
                                   ["compiler","source","output"]),
                     "development:compile", lambda compiler,source,output:
                     _compile(compiler,source,output,root,compilers), timeout=125),
        FunctionTool("development.package", "Install, remove or list packages using an explicitly configured pip/npm manager.",
                     object_schema({"action": {"type": "string", "enum": ["install","remove","list"]},
                                    "manager": {"type": "string", "enum": sorted(package_managers)},
                                    "package": {"type": "string", "maxLength": 160}}, ["action","manager"]),
                     "development:package:mutate", lambda action,manager,package="":
                     _package(action,manager,package,root,package_managers), timeout=185),
        FunctionTool("development.build", "Run a named build target from trusted host configuration.",
                     object_schema({"target": {"type": "string", "enum": sorted(build_targets)}}, ["target"]),
                     "development:build", lambda target: _build(target,root,build_targets), timeout=305),
        FunctionTool("development.deploy", "Execute a named deployment target from trusted host configuration.",
                     object_schema({"target": {"type": "string", "enum": sorted(deployment_targets)}}, ["target"]),
                     "development:deploy", lambda target: _deploy(target,deployment_targets,root), timeout=605),
        FunctionTool("development.api_test", "Send an HTTP API test request to an HTTPS host explicitly allowlisted by the host.",
                     object_schema({"url": {"type": "string", "format": "uri"},
                                    "method": {"type": "string", "enum": ["GET","HEAD","POST","PUT","PATCH","DELETE"]},
                                    "body": {"type": ["object","null"]}},
                                   ["url","method"]),
                     "development:api:test", lambda url,method,body=None:
                     _api_request(url,method,body,api_hosts), timeout=20),
        FunctionTool("development.ide_open", "Open a project file at a line in a configured IDE alias.",
                     object_schema({"ide": {"type": "string", "enum": sorted(ides)},
                                    "path": {"type": "string", "minLength": 1},
                                    "line": {"type": "integer", "minimum": 1}}, ["ide","path","line"]),
                     "development:ide", lambda ide,path,line: _ide_open(ide,path,line,root,ides)),
        FunctionTool("development.static_analysis", "Run a configured static analyzer against a project file.",
                     object_schema({"analyzer": {"type": "string", "enum": sorted(analyzers)},
                                    "path": {"type": "string", "minLength": 1}}, ["analyzer","path"]),
                     "development:analysis:advanced", lambda analyzer,path:
                     _analyze(path,root,analyzer,analyzers), timeout=125),
    ]
    return tuple(tools)

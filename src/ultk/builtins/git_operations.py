"""Policy-gated advanced Git history, workspace, submodule and PR operations.

Git is invoked with fixed executable/argument arrays (never a shell). This is not an OS
sandbox: Git hooks, filters, credential helpers and configured merge drivers execute with
the host user's privileges. Use a trusted repository and an external sandbox for untrusted
repositories. The GitHub PR adapter is trusted host code supplied by the application.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from ultk.builtins._common import FunctionTool, object_schema
from ultk.exceptions import ToolExecutionError

_OUTPUT_LIMIT = 40_000
_REF_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,159}\Z")
_BRANCH_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,119}\Z")
_STASH_PATTERN = re.compile(r"(?:stash|stash@\{[0-9]{1,6}\})\Z")
_CONFLICT_CODES = {"AA", "DD", "AU", "UA", "DU", "UD", "UU"}


def _environment() -> dict[str, str]:
    env = os.environ.copy()
    for key in (
        "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR",
    ):
        env.pop(key, None)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_EDITOR"] = "true"
    env["GIT_SEQUENCE_EDITOR"] = "true"
    env["GIT_MERGE_AUTOEDIT"] = "no"
    env["GIT_LITERAL_PATHSPECS"] = "1"
    return env


def _git(root: str, args: list[str], *, timeout: int = 30) -> dict[str, Any]:
    if not 1 <= timeout <= 180:
        raise ToolExecutionError("Git operation timeout is outside the allowed range.")
    base = Path(root).resolve()
    if not base.is_dir():
        raise ToolExecutionError("Configured project root is not a directory.")
    try:
        result = subprocess.run(
            ["git", *args], cwd=base, shell=False, stdin=subprocess.DEVNULL,
            capture_output=True, timeout=timeout, check=False, env=_environment(),
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolExecutionError("Git operation timed out.") from exc
    except OSError as exc:
        raise ToolExecutionError(f"Unable to start Git ({type(exc).__name__}).") from exc
    stdout, stderr = result.stdout, result.stderr
    return {
        "return_code": result.returncode,
        "stdout": stdout[:_OUTPUT_LIMIT].decode("utf-8", errors="replace"),
        "stderr": stderr[:_OUTPUT_LIMIT].decode("utf-8", errors="replace"),
        "output_truncated": len(stdout) > _OUTPUT_LIMIT or len(stderr) > _OUTPUT_LIMIT,
    }


def _require_repo(root: str) -> str:
    base = Path(root).resolve()
    result = _git(str(base), ["rev-parse", "--show-toplevel"], timeout=10)
    if result["return_code"] != 0:
        raise ToolExecutionError("Configured project root is not inside a Git repository.")
    top = Path(result["stdout"].strip()).resolve()
    if top != base:
        raise ToolExecutionError("Configured project root must be the Git repository root.")
    return str(base)


def _validate_ref(root: str, ref: str) -> str:
    if not isinstance(ref, str) or not _REF_PATTERN.fullmatch(ref) or ".." in ref or "@{" in ref:
        raise ToolExecutionError("Invalid Git revision selector.")
    checked = _git(root, ["rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}"], timeout=10)
    if checked["return_code"] != 0:
        raise ToolExecutionError("Git revision does not resolve to a commit.")
    return ref


def _validate_branch(root: str, branch: str) -> str:
    if not isinstance(branch, str) or not _BRANCH_PATTERN.fullmatch(branch) or ".." in branch or "@{" in branch:
        raise ToolExecutionError("Invalid Git branch name.")
    checked = _git(root, ["check-ref-format", "--branch", branch], timeout=10)
    if checked["return_code"] != 0:
        raise ToolExecutionError("Git branch name is not valid.")
    return branch


def _status(root: str) -> str:
    result = _git(root, ["status", "--porcelain=v1", "--untracked-files=normal"], timeout=10)
    if result["return_code"] != 0:
        raise ToolExecutionError("Unable to inspect Git working-tree status.")
    return result["stdout"]


def _require_clean(root: str) -> None:
    if _status(root):
        raise ToolExecutionError("Operation requires a clean working tree and index; stash or commit changes first.")


def _operation_state(root: str) -> dict[str, bool]:
    git_dir_result = _git(root, ["rev-parse", "--git-path", "."], timeout=10)
    git_dir = Path(git_dir_result["stdout"].strip())
    if not git_dir.is_absolute():
        git_dir = Path(root) / git_dir
    git_dir = git_dir.resolve()
    return {
        "rebase": (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists(),
        "cherry_pick": (git_dir / "CHERRY_PICK_HEAD").exists(),
        "revert": (git_dir / "REVERT_HEAD").exists(),
        "merge": (git_dir / "MERGE_HEAD").exists(),
    }


def _history(root: str, action: str, *, upstream: str | None = None,
             onto: str | None = None, commits: list[str] | None = None,
             rebase_merges: bool = False) -> dict[str, Any]:
    root = _require_repo(root)
    commits = commits or []
    state = _operation_state(root)
    if action == "rebase":
        if state["rebase"] or state["cherry_pick"] or state["revert"] or state["merge"]:
            raise ToolExecutionError("Another Git history operation is already in progress.")
        _require_clean(root)
        if not upstream:
            raise ToolExecutionError("Rebase requires an upstream revision.")
        upstream = _validate_ref(root, upstream)
        args = ["rebase"]
        if rebase_merges:
            args.append("--rebase-merges")
        if onto:
            args.extend(["--onto", _validate_ref(root, onto)])
        args.append(upstream)
    elif action in {"rebase_continue", "rebase_abort", "rebase_skip"}:
        if not state["rebase"]:
            raise ToolExecutionError("No rebase is currently in progress.")
        args = ["rebase", {"rebase_continue": "--continue", "rebase_abort": "--abort",
                           "rebase_skip": "--skip"}[action]]
    elif action == "cherry_pick":
        if any(state.values()):
            raise ToolExecutionError("Another Git history operation is already in progress.")
        _require_clean(root)
        if not 1 <= len(commits) <= 20:
            raise ToolExecutionError("Cherry-pick requires 1–20 commit revisions.")
        args = ["cherry-pick", *[_validate_ref(root, item) for item in commits]]
    elif action in {"cherry_pick_continue", "cherry_pick_abort", "cherry_pick_skip"}:
        if not state["cherry_pick"]:
            raise ToolExecutionError("No cherry-pick is currently in progress.")
        args = ["cherry-pick", {"cherry_pick_continue": "--continue",
                                "cherry_pick_abort": "--abort",
                                "cherry_pick_skip": "--skip"}[action]]
    elif action == "revert":
        if any(state.values()):
            raise ToolExecutionError("Another Git history operation is already in progress.")
        _require_clean(root)
        if not 1 <= len(commits) <= 20:
            raise ToolExecutionError("Revert requires 1–20 commit revisions.")
        args = ["revert", "--no-edit", *[_validate_ref(root, item) for item in commits]]
    elif action in {"revert_continue", "revert_abort", "revert_skip"}:
        if not state["revert"]:
            raise ToolExecutionError("No revert is currently in progress.")
        args = ["revert", {"revert_continue": "--continue", "revert_abort": "--abort",
                           "revert_skip": "--skip"}[action]]
    else:
        raise ToolExecutionError("Unsupported Git history action.")
    result = _git(root, args, timeout=120)
    result["action"] = action
    result["operation_state"] = _operation_state(root)
    return result


def _stash(root: str, action: str, *, message: str | None = None,
           reference: str | None = None, include_untracked: bool = False) -> dict[str, Any]:
    root = _require_repo(root)
    if action == "push":
        if message is not None and (not message.strip() or len(message) > 200):
            raise ToolExecutionError("Stash message must contain 1–200 characters.")
        args = ["stash", "push"]
        if include_untracked:
            args.append("--include-untracked")
        if message:
            args.extend(["--message", message])
    elif action == "list":
        args = ["stash", "list", "--date=iso", "--format=%gd%x09%H%x09%gs"]
    elif action in {"show", "apply", "pop", "drop"}:
        ref = reference or "stash@{0}"
        if not _STASH_PATTERN.fullmatch(ref):
            raise ToolExecutionError("Stash reference must be stash or stash@{N}.")
        if action == "show":
            args = ["stash", "show", "--stat", ref]
        elif action == "apply":
            args = ["stash", "apply", ref]
        elif action == "pop":
            args = ["stash", "pop", ref]
        else:
            args = ["stash", "drop", ref]
    else:
        raise ToolExecutionError("Unsupported stash action.")
    result = _git(root, args, timeout=90)
    result["action"] = action
    return result


def _worktree_path(worktree_root: str, relative: str, *, must_exist: bool = False) -> Path:
    base = Path(worktree_root).resolve()
    candidate = Path(relative)
    if (candidate.is_absolute() or not relative or "\x00" in relative
            or ".." in candidate.parts or "\\" in relative):
        raise ToolExecutionError("Worktree path is unsafe or escapes the configured root.")
    target = (base / candidate).resolve()
    if not target.is_relative_to(base) or target == base:
        raise ToolExecutionError("Worktree path escapes its configured root.")
    if must_exist and not target.is_dir():
        raise ToolExecutionError("Worktree directory does not exist.")
    return target


def _worktree(root: str, worktree_root: str, action: str, *,
              path: str | None = None, branch: str | None = None,
              reference: str | None = None) -> dict[str, Any]:
    root = _require_repo(root)
    base = Path(worktree_root).resolve()
    base.mkdir(parents=True, exist_ok=True)
    if action == "list":
        args = ["worktree", "list", "--porcelain"]
    elif action == "inspect":
        if not path:
            raise ToolExecutionError("Worktree inspection requires a relative path.")
        target = _worktree_path(str(base), path, must_exist=True)
        result = _git(root, ["-C", str(target), "status", "--short", "--branch"], timeout=15)
        result["path"] = str(target)
        result["action"] = action
        return result
    elif action == "add":
        if not path:
            raise ToolExecutionError("Worktree add requires a relative path.")
        target = _worktree_path(str(base), path)
        if target.exists():
            raise ToolExecutionError("Worktree destination already exists.")
        target.parent.mkdir(parents=True, exist_ok=True)
        args = ["worktree", "add"]
        if branch:
            args.extend(["-b", _validate_branch(root, branch)])
        args.append(str(target))
        if reference:
            args.append(_validate_ref(root, reference))
    elif action in {"remove", "lock", "unlock", "move"}:
        if not path:
            raise ToolExecutionError(f"Worktree {action} requires a relative path.")
        target = _worktree_path(str(base), path, must_exist=True)
        if action == "remove":
            args = ["worktree", "remove", str(target)]
        elif action == "lock":
            args = ["worktree", "lock", str(target)]
        elif action == "unlock":
            args = ["worktree", "unlock", str(target)]
        else:
            if not reference:
                raise ToolExecutionError("Worktree move requires a destination relative path.")
            destination = _worktree_path(str(base), reference)
            if destination.exists():
                raise ToolExecutionError("Worktree move destination already exists.")
            destination.parent.mkdir(parents=True, exist_ok=True)
            args = ["worktree", "move", str(target), str(destination)]
    elif action == "prune":
        args = ["worktree", "prune", "--verbose"]
    else:
        raise ToolExecutionError("Unsupported worktree action.")
    result = _git(root, args, timeout=90)
    result["action"] = action
    return result


def _project_path(root: str, relative: str, *, must_exist: bool = False) -> Path:
    base = Path(root).resolve()
    candidate = Path(relative)
    if (candidate.is_absolute() or not relative or "\x00" in relative
            or ".." in candidate.parts or "\\" in relative):
        raise ToolExecutionError("Submodule paths must be safe project-relative paths.")
    target = (base / candidate).resolve()
    if not target.is_relative_to(base) or target == base:
        raise ToolExecutionError("Submodule path escapes the configured project root.")
    if must_exist and not target.exists():
        raise ToolExecutionError("Submodule path does not exist.")
    return target


def _allowed_submodule_url(url: str, allowed_hosts: tuple[str, ...]) -> bool:
    if not isinstance(url, str) or len(url) > 2000 or "\x00" in url:
        return False
    if url.startswith("git@") and ":" in url:
        host = url.split("@", 1)[1].split(":", 1)[0].lower()
    else:
        parsed = urlparse(url)
        if parsed.scheme not in {"https", "ssh"} or not parsed.hostname or parsed.username not in {None, "git"}:
            return False
        host = parsed.hostname.lower()
    return host in {item.lower() for item in allowed_hosts}


def _submodule(root: str, action: str, *, path: str | None = None,
               url: str | None = None, allowed_hosts: tuple[str, ...] = ()) -> dict[str, Any]:
    root = _require_repo(root)
    if action == "status":
        args = ["submodule", "status", "--recursive"]
    elif action == "update":
        configured = _git(root, ["config", "--file", ".gitmodules", "--get-regexp",
                                 r"^submodule\..*\.url$"], timeout=10)
        if configured["return_code"] not in {0, 1}:
            raise ToolExecutionError("Unable to inspect configured submodule URLs.")
        for line in configured["stdout"].splitlines():
            _, configured_url = line.split(None, 1)
            if not _allowed_submodule_url(configured_url, allowed_hosts):
                raise ToolExecutionError("A configured submodule URL is not on a host allowlisted by the application.")
        args = ["submodule", "update", "--init", "--checkout"]
        if path:
            _project_path(root, path)
            args.extend(["--", path])
    elif action == "sync":
        args = ["submodule", "sync", "--recursive"]
    elif action == "add":
        if not path or not url or not _allowed_submodule_url(url, allowed_hosts):
            raise ToolExecutionError("Submodule add requires a URL on a host allowlisted by the application.")
        target = _project_path(root, path)
        if target.exists():
            raise ToolExecutionError("Submodule destination already exists.")
        args = ["submodule", "add", "--", url, path]
    elif action == "deinit":
        if not path:
            raise ToolExecutionError("Submodule deinit requires a project-relative path.")
        _project_path(root, path, must_exist=True)
        args = ["submodule", "deinit", "--", path]
    else:
        raise ToolExecutionError("Unsupported submodule action.")
    result = _git(root, args, timeout=150)
    result["action"] = action
    return result


def _conflicts(root: str, action: str, *, path: str | None = None,
               resolution: str | None = None) -> dict[str, Any]:
    root = _require_repo(root)
    if action == "list":
        raw = _git(root, ["status", "--porcelain=v1", "-z"], timeout=10)
        if raw["return_code"] != 0:
            return raw
        entries = raw["stdout"].split("\x00")
        conflicts = []
        for entry in entries:
            if len(entry) >= 4 and entry[:2] in _CONFLICT_CODES:
                conflicts.append({"status": entry[:2], "path": entry[3:]})
        return {"conflicts": conflicts}
    if action == "stages":
        if not path:
            raise ToolExecutionError("Conflict stage inspection requires a path.")
        _project_path(root, path)
        raw = _git(root, ["ls-files", "-u", "--", path], timeout=10)
        if raw["return_code"] != 0:
            return raw
        return {"path": path, "unmerged_index_entries": raw["stdout"]}
    if action == "resolve":
        if not path or resolution not in {"ours", "theirs", "working"}:
            raise ToolExecutionError("Conflict resolution requires a path and ours, theirs or working.")
        _project_path(root, path)
        if resolution in {"ours", "theirs"}:
            selected = _git(root, ["checkout", f"--{resolution}", "--", path], timeout=20)
            if selected["return_code"] != 0:
                return selected
        staged = _git(root, ["add", "--", path], timeout=20)
        staged["path"] = path
        staged["resolution"] = resolution
        return staged
    raise ToolExecutionError("Unsupported conflict action.")


def _pr_call(adapter: Callable[[str, dict[str, Any]], Any] | None,
             action: str, payload: dict[str, Any]) -> dict[str, Any]:
    if adapter is None:
        raise ToolExecutionError("No trusted pull-request adapter was configured by the host.")
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > 20_000:
        raise ToolExecutionError("Pull-request payload exceeds 20 KB.")
    result = adapter(action, payload)
    if not isinstance(result, dict):
        raise ToolExecutionError("Pull-request adapter must return a JSON-compatible object.")
    try:
        json.dumps(result)
    except (TypeError, ValueError) as exc:
        raise ToolExecutionError("Pull-request adapter returned a non-JSON result.") from exc
    return result


def create_advanced_git_tools(
    *, project_root: str | Path,
    worktree_root: str | Path | None = None,
    allowed_submodule_hosts: tuple[str, ...] = (),
    pull_request_adapter: Callable[[str, dict[str, Any]], Any] | None = None,
) -> tuple[FunctionTool, ...]:
    """Create advanced Git tools scoped to one repository.

    Mutations are capability-gated. The host policy must bind approval to exact arguments
    for destructive operations and PR merges. No PR credentials or network client are bundled.
    """
    root = str(Path(project_root).expanduser().resolve())
    worktrees = str(Path(worktree_root or (Path(root).parent / f"{Path(root).name}.ultk-worktrees")).expanduser().resolve())
    hosts = tuple(allowed_submodule_hosts)
    pr_adapter = pull_request_adapter
    tools = [
        FunctionTool(
            "git.history",
            "Run bounded rebase, cherry-pick and revert operations; continue, skip or abort an in-progress operation.",
            object_schema({
                "action": {"type": "string", "enum": [
                    "rebase", "rebase_continue", "rebase_abort", "rebase_skip",
                    "cherry_pick", "cherry_pick_continue", "cherry_pick_abort", "cherry_pick_skip",
                    "revert", "revert_continue", "revert_abort", "revert_skip"]},
                "upstream": {"type": "string", "maxLength": 160},
                "onto": {"type": "string", "maxLength": 160},
                "commits": {"type": "array", "items": {"type": "string", "maxLength": 160}, "maxItems": 20},
                "rebase_merges": {"type": "boolean"},
            }, ["action"]),
            "git:history:mutate",
            lambda action, upstream=None, onto=None, commits=None, rebase_merges=False:
                _history(root, action, upstream=upstream, onto=onto, commits=commits,
                         rebase_merges=rebase_merges),
            timeout=130,
        ),
        FunctionTool(
            "git.stash",
            "Create, apply or pop Git stashes; listing/inspection and dropping use separate capabilities.",
            object_schema({
                "action": {"type": "string", "enum": ["push", "apply", "pop"]},
                "message": {"type": "string", "maxLength": 200},
                "reference": {"type": "string", "maxLength": 32},
                "include_untracked": {"type": "boolean"},
            }, ["action"]),
            "git:stash:mutate",
            lambda action, message=None, reference=None, include_untracked=False:
                _stash(root, action, message=message, reference=reference,
                       include_untracked=include_untracked),
            timeout=100,
        ),
        FunctionTool(
            "git.stash_inspect",
            "List stash entries or inspect the diff summary of one selected stash.",
            object_schema({
                "action": {"type": "string", "enum": ["list", "show"]},
                "reference": {"type": "string", "maxLength": 32},
            }, ["action"]),
            "git:stash:read",
            lambda action, reference=None: _stash(root, action, reference=reference),
            timeout=30,
        ),
        FunctionTool(
            "git.stash_drop",
            "Permanently drop one explicitly selected Git stash entry.",
            object_schema({"reference": {"type": "string", "maxLength": 32}}, ["reference"]),
            "git:destructive",
            lambda reference: _stash(root, "drop", reference=reference),
            timeout=30,
        ),
        FunctionTool(
            "git.worktree",
            "Add, move, lock, unlock or prune worktrees under the host-configured worktree root.",
            object_schema({
                "action": {"type": "string", "enum": ["add", "move", "lock", "unlock", "prune"]},
                "path": {"type": "string", "maxLength": 500},
                "branch": {"type": "string", "maxLength": 120},
                "reference": {"type": "string", "maxLength": 500},
            }, ["action"]),
            "git:worktree:mutate",
            lambda action, path=None, branch=None, reference=None:
                _worktree(root, worktrees, action, path=path, branch=branch, reference=reference),
            timeout=100,
        ),
        FunctionTool(
            "git.worktree_inspect",
            "List linked worktrees or inspect the status of one configured worktree.",
            object_schema({
                "action": {"type": "string", "enum": ["list", "inspect"]},
                "path": {"type": "string", "maxLength": 500},
            }, ["action"]),
            "git:worktree:read",
            lambda action, path=None: _worktree(root, worktrees, action, path=path),
            timeout=30,
        ),
        FunctionTool(
            "git.worktree_remove",
            "Remove an explicitly selected worktree; dirty worktrees are not force-removed.",
            object_schema({"path": {"type": "string", "minLength": 1, "maxLength": 500}}, ["path"]),
            "git:destructive",
            lambda path: _worktree(root, worktrees, "remove", path=path),
            timeout=60,
        ),
        FunctionTool(
            "git.submodule",
            "Add from an allowlisted host, initialize/update with checkout strategy, or synchronize submodules.",
            object_schema({
                "action": {"type": "string", "enum": ["add", "update", "sync"]},
                "path": {"type": "string", "maxLength": 500},
                "url": {"type": "string", "maxLength": 2000},
            }, ["action"]),
            "git:submodule:mutate",
            lambda action, path=None, url=None:
                _submodule(root, action, path=path, url=url, allowed_hosts=hosts),
            timeout=160,
        ),
        FunctionTool(
            "git.submodule_inspect",
            "Inspect recursive submodule status without changing repository state.",
            object_schema({"action": {"type": "string", "enum": ["status"]}}, ["action"]),
            "git:submodule:read",
            lambda action: _submodule(root, action, allowed_hosts=hosts),
            timeout=30,
        ),
        FunctionTool(
            "git.submodule_deinit",
            "Deinitialize an explicitly selected submodule, removing its checked-out working-tree content.",
            object_schema({"path": {"type": "string", "minLength": 1, "maxLength": 500}}, ["path"]),
            "git:destructive",
            lambda path: _submodule(root, "deinit", path=path, allowed_hosts=hosts),
            timeout=90,
        ),
        FunctionTool(
            "git.conflict_inspect",
            "List unmerged files and inspect the index stages for one conflicted path.",
            object_schema({
                "action": {"type": "string", "enum": ["list", "stages"]},
                "path": {"type": "string", "maxLength": 500},
            }, ["action"]),
            "git:conflict:read",
            lambda action, path=None: _conflicts(root, action, path=path),
            timeout=30,
        ),
        FunctionTool(
            "git.conflict_resolve",
            "Stage an explicit ours/theirs/working resolution for one conflicted path.",
            object_schema({
                "path": {"type": "string", "minLength": 1, "maxLength": 500},
                "resolution": {"type": "string", "enum": ["ours", "theirs", "working"]},
            }, ["path", "resolution"]),
            "git:conflict:resolve",
            lambda path, resolution: _conflicts(root, "resolve", path=path, resolution=resolution),
            timeout=30,
        ),
        FunctionTool(
            "git.pull_request_read",
            "Inspect a pull request, reviews, comments or checks through the host-injected PR adapter.",
            object_schema({
                "action": {"type": "string", "enum": ["inspect", "list_reviews", "list_comments", "checks"]},
                "number": {"type": "integer", "minimum": 1},
            }, ["action", "number"]),
            "git:pull_request:read",
            lambda action, number: _pr_call(pr_adapter, action, {"number": number}),
            timeout=30,
        ),
        FunctionTool(
            "git.pull_request_write",
            "Create/update/comment/review/close a pull request through the host-injected adapter; never merges.",
            object_schema({
                "action": {"type": "string", "enum": ["create", "update", "comment", "review", "close"]},
                "number": {"type": "integer", "minimum": 1},
                "title": {"type": "string", "maxLength": 300},
                "body": {"type": "string", "maxLength": 10000},
                "head": {"type": "string", "maxLength": 160},
                "base": {"type": "string", "maxLength": 160},
                "state": {"type": "string", "enum": ["open", "closed"]},
                "event": {"type": "string", "enum": ["APPROVE", "REQUEST_CHANGES", "COMMENT"]},
                "comment": {"type": "string", "maxLength": 10000},
            }, ["action"]),
            "git:pull_request:write",
            lambda **payload: _pr_call(pr_adapter, payload.pop("action"), payload),
            timeout=40,
        ),
        FunctionTool(
            "git.pull_request_merge",
            "Merge a pull request through the host-injected adapter; host policy must require explicit human approval.",
            object_schema({
                "number": {"type": "integer", "minimum": 1},
                "method": {"type": "string", "enum": ["merge", "squash", "rebase"]},
                "expected_head_sha": {"type": "string", "pattern": "^[0-9a-fA-F]{40}$"},
            }, ["number", "expected_head_sha"]),
            "git:pull_request:merge",
            lambda number, expected_head_sha, method="squash":
                _pr_call(pr_adapter, "merge", {
                    "number": number, "method": method, "expected_head_sha": expected_head_sha,
                }),
            timeout=60,
        ),
    ]
    return tuple(tools)

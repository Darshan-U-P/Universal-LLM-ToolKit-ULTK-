"""Repository-scoped, policy-governed Git operations.

The pack exposes fixed, typed workflows rather than arbitrary Git command execution.
Remote operations require host-configured HTTPS host allowlists.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ultk.builtins._common import FunctionTool, object_schema
from ultk.exceptions import ToolExecutionError

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,119}$")
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@{}^~:+-]{0,199}$")


class GitRepository:
    """A fixed-command Git facade bound to one configured working tree."""

    def __init__(self, root_dir: str | Path, *, allowed_remote_hosts: set[str] | frozenset[str] = frozenset(),
                 timeout_seconds: int = 30, max_output_bytes: int = 200_000) -> None:
        self.root = Path(root_dir).expanduser().resolve()
        if not self.root.is_dir():
            raise ToolExecutionError("Configured Git root is not a directory.")
        self.allowed_remote_hosts = frozenset(host.casefold().rstrip(".") for host in allowed_remote_hosts)
        if not 1 <= timeout_seconds <= 120 or not 1024 <= max_output_bytes <= 2_000_000:
            raise ToolExecutionError("Invalid Git execution limits.")
        self.timeout = timeout_seconds
        self.max_output = max_output_bytes
        probe = self._run(["rev-parse", "--show-toplevel"], check=True)
        top = Path(probe["stdout"].strip()).resolve()
        if top != self.root:
            raise ToolExecutionError("Configured root must be the Git repository top-level directory.")

    def _run(self, args: list[str], *, check: bool = True, timeout: int | None = None) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="ultk-git-hooks-") as empty_hooks:
            command = [
                "git", "-C", str(self.root),
                "-c", f"core.hooksPath={empty_hooks}",
                "-c", "core.pager=cat",
                "-c", "diff.external=",
                "-c", "protocol.allow=never",
                "-c", "protocol.https.allow=always",
                "--no-pager", *args,
            ]
            env = os.environ.copy()
            for key in tuple(env):
                if key.startswith("GIT_"):
                    env.pop(key, None)
            env["GIT_TERMINAL_PROMPT"] = "0"
            env["GIT_CONFIG_NOSYSTEM"] = "1"
            try:
                result = subprocess.run(
                    command, cwd=self.root, env=env, shell=False, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    timeout=timeout or self.timeout, check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise ToolExecutionError("Git operation timed out.") from exc
            except OSError as exc:
                raise ToolExecutionError(f"Unable to start Git ({type(exc).__name__}).") from exc
        stdout = result.stdout[:self.max_output].decode("utf-8", errors="replace")
        stderr = result.stderr[:self.max_output].decode("utf-8", errors="replace")
        response = {
            "return_code": result.returncode, "stdout": stdout, "stderr": stderr,
            "output_truncated": len(result.stdout) > self.max_output or len(result.stderr) > self.max_output,
        }
        if check and result.returncode:
            detail = (stderr or stdout).strip()[:1200]
            raise ToolExecutionError(f"Git operation failed (exit {result.returncode}): {detail}")
        return response

    @staticmethod
    def _name(value: str, label: str = "name") -> str:
        if not isinstance(value, str) or not _NAME.fullmatch(value) or value.startswith("-") or ".." in value:
            raise ToolExecutionError(f"Invalid Git {label}.")
        return value

    @staticmethod
    def _ref(value: str) -> str:
        if not isinstance(value, str) or not _REF.fullmatch(value) or value.startswith("-") or ".." in value:
            raise ToolExecutionError("Invalid Git revision.")
        return value

    def _path(self, value: str) -> str:
        if not isinstance(value, str) or not value or len(value) > 1000 or "\x00" in value:
            raise ToolExecutionError("Invalid repository-relative path.")
        candidate = Path(value)
        if candidate.is_absolute() or any(part == ".." for part in candidate.parts):
            raise ToolExecutionError("Git paths must remain inside the configured repository.")
        resolved = (self.root / candidate).resolve()
        if not resolved.is_relative_to(self.root):
            raise ToolExecutionError("Git path escapes the configured repository.")
        return candidate.as_posix()

    def _pathspecs(self, paths: list[str]) -> list[str]:
        if not isinstance(paths, list) or not paths or len(paths) > 100:
            raise ToolExecutionError("Supply between 1 and 100 repository-relative paths.")
        return [f":(literal){self._path(path)}" for path in paths]

    def _commit_ref(self, revision: str) -> str:
        ref = self._ref(revision)
        self._run(["rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"])
        return ref

    def _remote(self, remote: str) -> tuple[str, str]:
        name = self._name(remote, "remote name")
        url = self._run(["remote", "get-url", name])["stdout"].strip()
        parsed = urlsplit(url)
        host = (parsed.hostname or "").casefold().rstrip(".")
        if parsed.scheme != "https" or not host or parsed.username or parsed.password:
            raise ToolExecutionError("Remote URL must be HTTPS and must not embed credentials.")
        if parsed.port not in (None, 443) or host not in self.allowed_remote_hosts:
            raise ToolExecutionError("Remote host is not in the host-configured HTTPS allowlist.")
        return name, url

    def inspect(self) -> dict[str, Any]:
        status = self._run(["status", "--porcelain=v1", "--branch", "-z"])
        branch = self._run(["branch", "--show-current"])["stdout"].strip()
        head = self._run(["rev-parse", "HEAD"])["stdout"].strip()
        remotes = self._run(["remote", "-v"])["stdout"].splitlines()
        branches = self._run(["for-each-ref", "--format=%(refname:short)%09%(objectname:short)%09%(upstream:short)", "refs/heads", "refs/remotes"])["stdout"].splitlines()
        return {
            "root": str(self.root), "branch": branch or None, "detached": not bool(branch),
            "head": head, "status_porcelain": status["stdout"],
            "branches": [line.split("\t") for line in branches], "remotes": remotes,
        }

    def branches(self, include_remote: bool = True) -> dict[str, Any]:
        refs = ["refs/heads"]
        if include_remote:
            refs.append("refs/remotes")
        output = self._run(["for-each-ref", "--format=%(refname:short)%09%(objectname:short)%09%(upstream:short)", *refs])["stdout"]
        return {"branches": [line.split("\t") for line in output.splitlines()]}

    def create_branch(self, name: str, start_point: str | None = None, switch: bool = False) -> dict[str, Any]:
        name = self._name(name, "branch name")
        if start_point:
            args = ["switch", "-c", name, self._commit_ref(start_point)] if switch else ["branch", name, self._commit_ref(start_point)]
        else:
            args = ["switch", "-c", name] if switch else ["branch", name]
        return self._run(args)

    def switch_branch(self, name: str) -> dict[str, Any]:
        return self._run(["switch", self._name(name, "branch name")])

    def rename_branch(self, old_name: str, new_name: str) -> dict[str, Any]:
        return self._run(["branch", "-m", self._name(old_name), self._name(new_name)])

    def delete_branch(self, name: str) -> dict[str, Any]:
        return self._run(["branch", "-d", self._name(name)])

    def stage(self, paths: list[str]) -> dict[str, Any]:
        return self._run(["add", "--", *self._pathspecs(paths)])

    def unstage(self, paths: list[str]) -> dict[str, Any]:
        return self._run(["restore", "--staged", "--", *self._pathspecs(paths)])

    def commit(self, message: str, paths: list[str] | None = None) -> dict[str, Any]:
        if not isinstance(message, str) or not message.strip() or len(message) > 500:
            raise ToolExecutionError("Commit message must contain 1–500 characters.")
        if paths:
            self.stage(paths)
        return self._run(["commit", "-m", message])

    def diff(self, mode: str = "working", base: str | None = None, target: str | None = None,
             path: str | None = None) -> dict[str, Any]:
        args = ["diff", "--no-ext-diff", "--no-textconv", "--no-color", "--no-renames"]
        if mode == "staged":
            args.append("--cached")
        elif mode == "commits":
            if not base or not target:
                raise ToolExecutionError("Commit diff requires base and target revisions.")
            args.extend([self._commit_ref(base), self._commit_ref(target)])
        elif mode != "working":
            raise ToolExecutionError("Diff mode must be working, staged or commits.")
        if path:
            args.extend(["--", f":(literal){self._path(path)}"])
        return self._run(args)

    def merge_start(self, revision: str) -> dict[str, Any]:
        return self._run(["merge", "--no-commit", "--no-ff", "--no-edit", self._commit_ref(revision)], check=False)

    def merge_abort(self) -> dict[str, Any]:
        return self._run(["merge", "--abort"])

    def merge_commit(self, message: str) -> dict[str, Any]:
        if not isinstance(message, str) or not message.strip() or len(message) > 500:
            raise ToolExecutionError("Merge message must contain 1–500 characters.")
        state = self._run(["rev-parse", "--verify", "-q", "MERGE_HEAD"], check=False)
        if state["return_code"]:
            raise ToolExecutionError("No merge is currently in progress.")
        if self.conflicts()["conflicts"]:
            raise ToolExecutionError("Resolve and stage all merge conflicts before completing the merge.")
        return self._run(["commit", "--no-edit", "-m", message])

    def conflicts(self) -> dict[str, Any]:
        output = self._run(["ls-files", "-u", "-z"])["stdout"]
        found: dict[str, set[int]] = {}
        for record in output.split("\x00"):
            if not record:
                continue
            try:
                metadata, path = record.split("\t", 1)
                stage = int(metadata.rsplit(" ", 1)[1])
                found.setdefault(path, set()).add(stage)
            except (ValueError, IndexError):
                continue
        return {"conflicts": [{"path": path, "stages": sorted(stages)} for path, stages in sorted(found.items())]}

    def resolve_conflict(self, path: str, strategy: str, content: str | None = None) -> dict[str, Any]:
        relative = self._path(path)
        if not any(item["path"] == relative for item in self.conflicts()["conflicts"]):
            raise ToolExecutionError("Path is not currently unmerged.")
        target = self.root / relative
        if strategy in ("ours", "theirs"):
            self._run(["checkout", f"--{strategy}", "--", f":(literal){relative}"])
        elif strategy == "manual":
            if not isinstance(content, str) or len(content.encode("utf-8")) > 500_000:
                raise ToolExecutionError("Manual resolution requires UTF-8 text no larger than 500 KB.")
            if not target.parent.resolve().is_relative_to(self.root):
                raise ToolExecutionError("Conflict path escapes the repository.")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="")
        else:
            raise ToolExecutionError("Resolution strategy must be ours, theirs or manual.")
        self._run(["add", "--", f":(literal){relative}"])
        return {"path": relative, "strategy": strategy, "remaining_conflicts": self.conflicts()["conflicts"]}

    def history(self, revision: str = "HEAD", limit: int = 20, path: str | None = None) -> dict[str, Any]:
        if not 1 <= limit <= 100:
            raise ToolExecutionError("History limit must be between 1 and 100.")
        args = ["log", f"-{limit}", "--date=iso-strict", "--format=%H%x09%P%x09%an%x09%aI%x09%s", self._commit_ref(revision)]
        if path:
            args.extend(["--", f":(literal){self._path(path)}"])
        return self._run(args)

    def show_commit(self, revision: str) -> dict[str, Any]:
        return self._run(["show", "--no-ext-diff", "--no-textconv", "--no-color",
                          "--format=fuller", "--stat", self._commit_ref(revision)])

    def blame(self, path: str, revision: str = "HEAD") -> dict[str, Any]:
        return self._run(["blame", "--line-porcelain", self._commit_ref(revision), "--",
                          f":(literal){self._path(path)}"])

    def tags(self) -> dict[str, Any]:
        return {"tags": self._run(["tag", "--list", "--format=%(refname:short)%09%(objectname:short)%09%(subject)"])["stdout"].splitlines()}

    def remotes(self) -> dict[str, Any]:
        return {"remotes": self._run(["remote", "-v"])["stdout"].splitlines()}

    def _validate_remote_url(self, url: str) -> None:
        if not isinstance(url, str) or len(url) > 2000:
            raise ToolExecutionError("Invalid remote URL.")
        parsed = urlsplit(url)
        host = (parsed.hostname or "").casefold().rstrip(".")
        if parsed.scheme != "https" or not host or parsed.username or parsed.password:
            raise ToolExecutionError("Only HTTPS remote URLs without embedded credentials are supported.")
        if parsed.port not in (None, 443) or host not in self.allowed_remote_hosts:
            raise ToolExecutionError("Remote host is not in the host-configured HTTPS allowlist.")

    def add_remote(self, name: str, url: str) -> dict[str, Any]:
        self._validate_remote_url(url)
        return self._run(["remote", "add", self._name(name, "remote name"), url])

    def set_remote_url(self, name: str, url: str) -> dict[str, Any]:
        self._validate_remote_url(url)
        return self._run(["remote", "set-url", self._name(name, "remote name"), url])

    def remove_remote(self, name: str) -> dict[str, Any]:
        return self._run(["remote", "remove", self._name(name, "remote name")])

    def fetch(self, remote: str, prune: bool = False) -> dict[str, Any]:
        name, _ = self._remote(remote)
        return self._run(["fetch", "--no-recurse-submodules", *(["--prune"] if prune else []), name],
                         timeout=max(self.timeout, 60))

    def pull(self, remote: str, branch: str, mode: str = "merge") -> dict[str, Any]:
        name, _ = self._remote(remote)
        if mode not in ("merge", "rebase", "ff-only"):
            raise ToolExecutionError("Pull mode must be merge, rebase or ff-only.")
        args = ["pull", "--no-recurse-submodules", "--no-edit",
                {"merge": "--no-rebase", "rebase": "--rebase", "ff-only": "--ff-only"}[mode],
                name, self._name(branch, "remote branch")]
        return self._run(args, check=False, timeout=max(self.timeout, 60))

    def push(self, remote: str, branch: str, set_upstream: bool = False) -> dict[str, Any]:
        name, _ = self._remote(remote)
        args = ["push", "--porcelain"]
        if set_upstream:
            args.append("--set-upstream")
        args.extend([name, self._name(branch, "branch")])
        return self._run(args, check=False, timeout=max(self.timeout, 60))


def create_git_tools(*, repository_root: str | Path,
                     allowed_remote_hosts: set[str] | frozenset[str] = frozenset(),
                     timeout_seconds: int = 30,
                     max_output_bytes: int = 200_000) -> tuple[FunctionTool, ...]:
    """Create the Git tool pack with separate capabilities for mutations."""
    git = GitRepository(repository_root, allowed_remote_hosts=allowed_remote_hosts,
                        timeout_seconds=timeout_seconds, max_output_bytes=max_output_bytes)

    def tool(name: str, description: str, properties: dict[str, Any], required: list[str],
             capability: str, function: Any, timeout: int = 30) -> FunctionTool:
        return FunctionTool(name, description, object_schema(properties, required),
                            capability, function, timeout=timeout, output_limit=max_output_bytes)

    path_array = {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 1000},
                  "minItems": 1, "maxItems": 100}
    ref = {"type": "string", "minLength": 1, "maxLength": 200}
    return (
        tool("git.inspect_repository", "Inspect repository metadata, status, branches and remotes.", {}, [], "git:read", git.inspect),
        tool("git.list_branches", "List local and optionally remote-tracking branches.", {"include_remote": {"type": "boolean"}}, [], "git:read", git.branches),
        tool("git.create_branch", "Create a local branch, optionally from a revision and switch to it.", {"name": ref, "start_point": ref, "switch": {"type": "boolean"}}, ["name"], "git:branch:write", git.create_branch),
        tool("git.switch_branch", "Switch to an existing local branch.", {"name": ref}, ["name"], "git:branch:write", git.switch_branch),
        tool("git.rename_branch", "Rename a local branch.", {"old_name": ref, "new_name": ref}, ["old_name", "new_name"], "git:branch:write", git.rename_branch),
        tool("git.delete_branch", "Safely delete a fully merged local branch; force deletion is not exposed.", {"name": ref}, ["name"], "git:branch:delete", git.delete_branch),
        tool("git.stage_files", "Stage selected repository-relative paths.", {"paths": path_array}, ["paths"], "git:index:write", git.stage),
        tool("git.unstage_files", "Unstage selected paths without discarding working-tree content.", {"paths": path_array}, ["paths"], "git:index:write", git.unstage),
        tool("git.commit", "Commit the index, optionally staging explicit paths first.", {"message": {"type": "string", "minLength": 1, "maxLength": 500}, "paths": path_array}, ["message"], "git:commit", git.commit),
        tool("git.diff", "Inspect working, staged or commit-to-commit diffs.", {"mode": {"type": "string", "enum": ["working", "staged", "commits"]}, "base": ref, "target": ref, "path": {"type": "string", "maxLength": 1000}}, [], "git:read", git.diff),
        tool("git.start_merge", "Start a non-committing merge; inspect and resolve conflicts explicitly.", {"revision": ref}, ["revision"], "git:merge", git.merge_start),
        tool("git.abort_merge", "Abort the in-progress merge.", {}, [], "git:merge", git.merge_abort),
        tool("git.complete_merge", "Create the merge commit after every conflict is resolved and staged.", {"message": {"type": "string", "minLength": 1, "maxLength": 500}}, ["message"], "git:merge", git.merge_commit),
        tool("git.list_conflicts", "List unmerged paths and available index stages.", {}, [], "git:read", git.conflicts),
        tool("git.resolve_conflict", "Resolve and stage one file using ours, theirs or supplied UTF-8 content.", {"path": {"type": "string", "minLength": 1, "maxLength": 1000}, "strategy": {"type": "string", "enum": ["ours", "theirs", "manual"]}, "content": {"type": "string", "maxLength": 500000}}, ["path", "strategy"], "git:conflict:resolve", git.resolve_conflict),
        tool("git.history", "Read bounded commit history with authors, timestamps, parents and subjects.", {"revision": ref, "limit": {"type": "integer", "minimum": 1, "maximum": 100}, "path": {"type": "string", "maxLength": 1000}}, [], "git:read", git.history),
        tool("git.show_commit", "Inspect commit metadata and file-change summary.", {"revision": ref}, ["revision"], "git:read", git.show_commit),
        tool("git.blame", "Inspect line-level commit attribution for a file.", {"path": {"type": "string", "minLength": 1, "maxLength": 1000}, "revision": ref}, ["path"], "git:read", git.blame),
        tool("git.list_tags", "List repository tags and target summaries.", {}, [], "git:read", git.tags),
        tool("git.list_remotes", "List configured remotes.", {}, [], "git:remote:read", git.remotes),
        tool("git.add_remote", "Add an HTTPS remote on a host-allowlisted hostname.", {"name": ref, "url": {"type": "string", "minLength": 8, "maxLength": 2000}}, ["name", "url"], "git:remote:configure", git.add_remote),
        tool("git.set_remote_url", "Change a remote to an allowlisted HTTPS URL.", {"name": ref, "url": {"type": "string", "minLength": 8, "maxLength": 2000}}, ["name", "url"], "git:remote:configure", git.set_remote_url),
        tool("git.remove_remote", "Remove a configured remote.", {"name": ref}, ["name"], "git:remote:configure", git.remove_remote),
        tool("git.fetch", "Fetch refs from an allowlisted HTTPS remote.", {"remote": ref, "prune": {"type": "boolean"}}, ["remote"], "git:remote:fetch", git.fetch, 120),
        tool("git.pull", "Pull a remote branch using merge, rebase or fast-forward-only mode.", {"remote": ref, "branch": ref, "mode": {"type": "string", "enum": ["merge", "rebase", "ff-only"]}}, ["remote", "branch"], "git:remote:pull", git.pull, 120),
        tool("git.push", "Push a local branch to an allowlisted HTTPS remote.", {"remote": ref, "branch": ref, "set_upstream": {"type": "boolean"}}, ["remote", "branch"], "git:remote:push", git.push, 120),
    )

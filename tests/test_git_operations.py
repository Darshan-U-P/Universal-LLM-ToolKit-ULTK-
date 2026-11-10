from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ultk.builtins.git_operations import (
    _allowed_submodule_url,
    _conflicts,
    _history,
    _stash,
    _worktree,
    create_advanced_git_tools,
)
from ultk.engine import ToolEngine
from ultk.permissions import AllowListPolicy


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, shell=False, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _repo(path: Path) -> Path:
    path.mkdir()
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.name", "ULTK Tests")
    _git(path, "config", "user.email", "ultk-tests@example.invalid")
    (path / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(path, "add", "tracked.txt")
    _git(path, "commit", "-m", "initial")
    return path


def test_advanced_git_pack_registers_operations(tmp_path: Path) -> None:
    tools = create_advanced_git_tools(project_root=tmp_path)
    names = {tool.spec.name for tool in tools}
    assert {
        "git.history", "git.stash", "git.stash_inspect", "git.stash_drop",
        "git.worktree", "git.worktree_inspect", "git.worktree_remove",
        "git.submodule", "git.submodule_inspect", "git.submodule_deinit",
        "git.conflict_inspect", "git.conflict_resolve",
        "git.pull_request_read", "git.pull_request_write", "git.pull_request_merge",
    } <= names


def test_rebase_uses_validated_refs_and_preserves_clean_worktree(tmp_path: Path) -> None:
    root = _repo(tmp_path / "repo")
    _git(root, "switch", "-c", "topic")
    (root / "topic.txt").write_text("topic\n", encoding="utf-8")
    _git(root, "add", "topic.txt")
    _git(root, "commit", "-m", "topic")
    _git(root, "switch", "main")
    (root / "main.txt").write_text("main\n", encoding="utf-8")
    _git(root, "add", "main.txt")
    _git(root, "commit", "-m", "main update")
    _git(root, "switch", "topic")

    result = _history(str(root), "rebase", upstream="main")
    assert result["return_code"] == 0
    assert result["operation_state"]["rebase"] is False


def test_history_mutation_rejects_dirty_tree_and_option_like_refs(tmp_path: Path) -> None:
    root = _repo(tmp_path / "repo")
    (root / "tracked.txt").write_text("modified\n", encoding="utf-8")
    with pytest.raises(Exception, match="clean working tree"):
        _history(str(root), "rebase", upstream="main")
    (root / "tracked.txt").write_text("base\n", encoding="utf-8")
    with pytest.raises(Exception, match="Invalid Git revision"):
        _history(str(root), "rebase", upstream="--upload-pack=evil")


def test_cherry_pick_and_revert_use_explicit_commit_ids(tmp_path: Path) -> None:
    root = _repo(tmp_path / "repo")
    _git(root, "switch", "-c", "source")
    (root / "source.txt").write_text("source\n", encoding="utf-8")
    _git(root, "add", "source.txt")
    _git(root, "commit", "-m", "source change")
    commit = _git(root, "rev-parse", "HEAD")
    _git(root, "switch", "main")
    picked = _history(str(root), "cherry_pick", commits=[commit])
    assert picked["return_code"] == 0
    reverted = _history(str(root), "revert", commits=[commit])
    assert reverted["return_code"] == 0
    assert not (root / "source.txt").exists()


def test_stash_lifecycle_is_bounded_and_explicit(tmp_path: Path) -> None:
    root = _repo(tmp_path / "repo")
    (root / "tracked.txt").write_text("work in progress\n", encoding="utf-8")
    pushed = _stash(str(root), "push", message="checkpoint", include_untracked=True)
    assert pushed["return_code"] == 0
    listed = _stash(str(root), "list")
    assert "checkpoint" in listed["stdout"]
    applied = _stash(str(root), "apply", reference="stash@{0}")
    assert applied["return_code"] == 0
    with pytest.raises(Exception, match="Stash reference"):
        _stash(str(root), "drop", reference="--all")


def test_worktree_add_is_confined_and_uses_valid_branch(tmp_path: Path) -> None:
    root = _repo(tmp_path / "repo")
    worktree_root = tmp_path / "worktrees"
    result = _worktree(
        str(root), str(worktree_root), "add",
        path="feature", branch="feature-worktree", reference="HEAD",
    )
    assert result["return_code"] == 0
    assert (worktree_root / "feature").is_dir()
    with pytest.raises(Exception, match="escapes"):
        _worktree(str(root), str(worktree_root), "add", path="../outside")


def test_conflict_inspection_and_explicit_resolution(tmp_path: Path) -> None:
    root = _repo(tmp_path / "repo")
    _git(root, "switch", "-c", "other")
    (root / "tracked.txt").write_text("other\n", encoding="utf-8")
    _git(root, "commit", "-am", "other change")
    _git(root, "switch", "main")
    (root / "tracked.txt").write_text("main change\n", encoding="utf-8")
    _git(root, "commit", "-am", "main change")
    conflict = subprocess.run(
        ["git", "merge", "other"], check=False, cwd=root, shell=False, capture_output=True, text=True
    )
    assert conflict.returncode != 0
    listed = _conflicts(str(root), "list")
    assert listed["conflicts"][0]["path"] == "tracked.txt"
    resolved = _conflicts(str(root), "resolve", path="tracked.txt", resolution="ours")
    assert resolved["return_code"] == 0
    assert _git(root, "ls-files", "-u") == ""
    assert _git(root, "status", "--porcelain") == ""


def test_submodule_urls_require_exact_host_allowlist() -> None:
    assert _allowed_submodule_url("https://github.com/example/repo.git", ("github.com",))
    assert _allowed_submodule_url("git@github.com:example/repo.git", ("github.com",))
    assert not _allowed_submodule_url("https://evil.example/repo.git", ("github.com",))
    assert not _allowed_submodule_url("file:///tmp/repo", ("github.com",))


def test_pull_request_adapter_is_host_injected_and_receives_structured_data() -> None:
    calls = []

    def adapter(action: str, payload: dict) -> dict:
        calls.append((action, payload))
        return {"action": action, "number": payload.get("number"), "ok": True}

    tools = {tool.spec.name: tool for tool in create_advanced_git_tools(
        project_root=Path.cwd(), pull_request_adapter=adapter
    )}
    result = tools["git.pull_request_read"]._function(action="inspect", number=17)
    assert result == {"action": "inspect", "number": 17, "ok": True}
    assert calls == [("inspect", {"number": 17})]


def test_engine_installs_advanced_git_tools_with_policy_gates(tmp_path: Path) -> None:
    root = _repo(tmp_path / "repo")
    engine = ToolEngine(policy=AllowListPolicy({"git.stash"}))
    engine.install_advanced_git_tools(project_root=root)
    names = {tool.spec.name for tool in engine.registry.list()}
    assert "git.history" in names
    assert "git.pull_request_merge" in names
    stash = next(tool for tool in engine.registry.list() if tool.spec.name == "git.stash")
    assert stash.spec.capabilities == frozenset({"git:stash:mutate"})

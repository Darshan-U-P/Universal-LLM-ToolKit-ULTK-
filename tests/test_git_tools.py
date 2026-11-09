"""Tests for the Git tool pack. Authored but intentionally not run during implementation."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ultk.builtins.git import GitRepository, create_git_tools
from ultk.exceptions import ToolExecutionError


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], check=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "ULTK Test")
    git(root, "config", "user.email", "ultk@example.invalid")
    (root / "tracked.txt").write_text("base\n", encoding="utf-8")
    git(root, "add", "tracked.txt")
    git(root, "commit", "-m", "initial")
    return root


def test_inspect_stage_commit_and_history(repo: Path) -> None:
    tools = GitRepository(repo)
    (repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
    tools.stage(["tracked.txt"])
    assert tools.diff("staged")["stdout"]
    tools.commit("change tracked file")
    assert "change tracked file" in tools.history()["stdout"]


def test_branch_lifecycle(repo: Path) -> None:
    tools = GitRepository(repo)
    tools.create_branch("feature/test", switch=True)
    assert tools.inspect()["branch"] == "feature/test"
    tools.rename_branch("feature/test", "feature/renamed")
    tools.switch_branch("main")
    tools.delete_branch("feature/renamed")


def test_path_escape_rejected(repo: Path) -> None:
    tools = GitRepository(repo)
    with pytest.raises(ToolExecutionError):
        tools.stage(["../outside.txt"])


def test_remote_allowlist_required(repo: Path) -> None:
    tools = GitRepository(repo, allowed_remote_hosts={"github.com"})
    with pytest.raises(ToolExecutionError):
        tools.add_remote("origin", "https://example.com/acme/repo.git")
    tools.add_remote("origin", "https://github.com/acme/repo.git")
    assert "origin" in tools.remotes()["remotes"][0]


def test_merge_conflict_resolution(repo: Path) -> None:
    tools = GitRepository(repo)
    tools.create_branch("feature", switch=True)
    (repo / "tracked.txt").write_text("feature\n", encoding="utf-8")
    tools.stage(["tracked.txt"])
    tools.commit("feature edit")
    tools.switch_branch("main")
    (repo / "tracked.txt").write_text("main\n", encoding="utf-8")
    tools.stage(["tracked.txt"])
    tools.commit("main edit")
    result = tools.merge_start("feature")
    assert result["return_code"] != 0
    assert tools.conflicts()["conflicts"]
    tools.resolve_conflict("tracked.txt", "ours")
    assert not tools.conflicts()["conflicts"]
    tools.merge_commit("merge feature")
    assert "merge feature" in tools.history()["stdout"]


def test_tool_pack_exports_expected_names(repo: Path) -> None:
    tools = create_git_tools(repository_root=repo)
    names = {tool.spec.name for tool in tools}
    assert {"git.inspect_repository", "git.resolve_conflict", "git.push",
            "git.history", "git.diff"} <= names

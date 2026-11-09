from __future__ import annotations

from pathlib import Path

import pytest

from ultk.builtins.computer import create_computer_tools
from ultk.builtins.development import create_development_tools
from ultk.builtins.web import _validate_public_url, create_web_tools
from ultk.engine import ToolEngine
from ultk.permissions import AllowListPolicy


def test_computer_tools_are_registered_without_optional_gui_dependencies(tmp_path: Path) -> None:
    engine = ToolEngine(policy=AllowListPolicy({"computer.clipboard_read"}))
    engine.install_computer_tools(image_root=tmp_path)
    names = {tool.spec.name for tool in engine.registry.list()}
    assert "computer.screenshot" in names
    assert "computer.mouse" in names
    assert "computer.keyboard" in names
    assert "computer.clipboard_read" in names


def test_development_tools_are_project_scoped(tmp_path: Path) -> None:
    (tmp_path / "sample.py").write_text("import os\n\ndef f():\n    return 1\n", encoding="utf-8")
    tools = {tool.spec.name: tool for tool in create_development_tools(project_root=tmp_path)}
    assert tools["development.analyze_python"].spec.capabilities == frozenset({"development:analyze"})
    assert tools["development.git"].spec.name == "development.git"


def test_development_path_traversal_is_rejected(tmp_path: Path) -> None:
    from ultk.builtins.development import _rooted
    with pytest.raises(Exception, match="escapes"):
        _rooted(str(tmp_path), "../outside.txt")


def test_web_rejects_local_and_non_http_targets() -> None:
    with pytest.raises(Exception, match="Only credential-free"):
        _validate_public_url("file:///etc/passwd")
    with pytest.raises(Exception, match="private"):
        _validate_public_url("http://127.0.0.1/")


def test_web_tools_register_without_playwright_installed() -> None:
    names = {tool.spec.name for tool in create_web_tools()}
    assert {"web.search", "web.fetch_url", "web.extract_page",
            "web.download_file", "web.browser_open", "web.analyze_site"} <= names


@pytest.mark.asyncio
async def test_tool_engine_applies_capability_policy_to_new_tool_packs(tmp_path: Path) -> None:
    engine = ToolEngine(policy=AllowListPolicy({"development.analyze_python"}))
    (tmp_path / "ok.py").write_text("def ok():\n    return True\n", encoding="utf-8")
    engine.install_development_tools(project_root=tmp_path)
    denied = await engine.execute("development.analyze_python", {"path": "ok.py"})
    assert denied.is_error
    allowed = await engine.execute(
        "development.analyze_python", {"path": "ok.py"},
        granted_capabilities=frozenset({"development:analyze"}),
    )
    assert not allowed.is_error

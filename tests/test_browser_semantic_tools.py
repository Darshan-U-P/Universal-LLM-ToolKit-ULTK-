from __future__ import annotations

from pathlib import Path

import pytest

from ultk.builtins import browser_semantic
from ultk.builtins.browser_semantic import (
    _act,
    _validate_target,
    _wait_for,
    create_semantic_browser_tools,
)
from ultk.exceptions import ToolExecutionError
from ultk.engine import ToolEngine
from ultk.permissions import AllowListPolicy


class FakeLocator:
    def __init__(self, count=1):
        self.matches = count
        self.calls = []

    def count(self):
        return self.matches

    def click(self, **kwargs):
        self.calls.append(("click", kwargs))

    def fill(self, value, **kwargs):
        self.calls.append(("fill", value, kwargs))

    def press_sequentially(self, value, **kwargs):
        self.calls.append(("type", value, kwargs))

    def press(self, key, **kwargs):
        self.calls.append(("press", key, kwargs))

    def check(self, **kwargs):
        self.calls.append(("check", kwargs))

    def uncheck(self, **kwargs):
        self.calls.append(("uncheck", kwargs))

    def select_option(self, **kwargs):
        self.calls.append(("select", kwargs))

    def hover(self, **kwargs):
        self.calls.append(("hover", kwargs))

    def wait_for(self, **kwargs):
        self.calls.append(("wait_for", kwargs))


class FakePage:
    url = "https://example.org/"

    def __init__(self, count=1):
        self.locator_result = FakeLocator(count)
        self.calls = []

    def get_by_role(self, role, **kwargs):
        self.calls.append(("role", role, kwargs))
        return self.locator_result

    def get_by_label(self, target, **kwargs):
        self.calls.append(("label", target, kwargs))
        return self.locator_result

    def get_by_text(self, target, **kwargs):
        self.calls.append(("text", target, kwargs))
        return self.locator_result

    def get_by_placeholder(self, target, **kwargs):
        self.calls.append(("placeholder", target, kwargs))
        return self.locator_result

    def get_by_alt_text(self, target, **kwargs):
        self.calls.append(("alt", target, kwargs))
        return self.locator_result

    def get_by_test_id(self, target):
        self.calls.append(("test_id", target))
        return self.locator_result


def test_semantic_browser_pack_registers_three_tools(tmp_path: Path) -> None:
    tools = create_semantic_browser_tools(session_root=tmp_path / "sessions")
    assert {tool.spec.name for tool in tools} == {
        "browser.inspect_interactive",
        "browser.semantic_act",
        "browser.wait_for_target",
    }


def test_engine_installs_semantic_browser_tools(tmp_path: Path) -> None:
    engine = ToolEngine(policy=AllowListPolicy({"browser.inspect_interactive"}))
    engine.install_semantic_browser_tools(session_root=tmp_path / "sessions")
    assert "browser.inspect_interactive" in {
        tool.spec.name for tool in engine.registry.list()
    }


def test_role_locator_uses_exact_accessible_name(monkeypatch, tmp_path: Path) -> None:
    page = FakePage()
    monkeypatch.setattr(browser_semantic, "_with_page", lambda root, sid, action: action(page))
    result = _act(str(tmp_path), "s1", "role", "Continue", "click", role="button")
    assert result["action"] == "click"
    assert page.calls == [("role", "button", {"name": "Continue", "exact": True})]
    assert page.locator_result.calls[0][0] == "click"


@pytest.mark.parametrize("count", [0, 2])
def test_semantic_action_fails_closed_for_missing_or_ambiguous_target(
    monkeypatch, tmp_path: Path, count: int
) -> None:
    page = FakePage(count=count)
    monkeypatch.setattr(browser_semantic, "_with_page", lambda root, sid, action: action(page))
    with pytest.raises(ToolExecutionError, match="exactly one"):
        _act(str(tmp_path), "s1", "text", "Pay now", "click")
    assert page.locator_result.calls == []


def test_semantic_action_rejects_unapproved_keys_before_browser_launch(tmp_path: Path) -> None:
    with pytest.raises(ToolExecutionError, match="allowlisted"):
        _act(str(tmp_path), "s1", "text", "Search", "press", key="Control+L")


def test_semantic_action_validates_role_and_value_combinations(tmp_path: Path) -> None:
    with pytest.raises(ToolExecutionError, match="accessible role"):
        _act(str(tmp_path), "s1", "role", "Submit", "click", role="unknown")
    with pytest.raises(ToolExecutionError, match="only valid"):
        _act(str(tmp_path), "s1", "text", "Submit", "click", value="unexpected")


def test_wait_for_target_is_bounded_and_uses_exact_locator(monkeypatch, tmp_path: Path) -> None:
    page = FakePage()
    monkeypatch.setattr(browser_semantic, "_with_page", lambda root, sid, action: action(page))
    result = _wait_for(str(tmp_path), "s1", "label", "Email", "visible", 1500)
    assert result["matches"] == 1
    assert page.locator_result.calls == [
        ("wait_for", {"state": "visible", "timeout": 1500})
    ]


def test_wait_for_target_rejects_oversized_timeout_before_launch(tmp_path: Path) -> None:
    with pytest.raises(ToolExecutionError, match="between 100 and 10000"):
        _wait_for(str(tmp_path), "s1", "text", "Ready", "visible", 20000)


def test_target_validation_rejects_role_on_non_role_strategy() -> None:
    with pytest.raises(ToolExecutionError, match="only valid"):
        _validate_target("text", "Save", role="button")

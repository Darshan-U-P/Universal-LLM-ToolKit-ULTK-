"""Tests for OCR-backed computer automation."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ultk.builtins.computer_visual import ComputerVisualPack, create_computer_visual_tools
from ultk.exceptions import ToolExecutionError


class FakeImage:
    width = 640
    height = 480


@pytest.fixture
def pack() -> ComputerVisualPack:
    return ComputerVisualPack(allowed_ocr_languages=("eng", "deu"), max_ocr_lines=20)


def ocr_data(words=("Save", "changes"), *, left=(10, 55), top=(20, 20)):
    return {
        "text": list(words),
        "conf": ["95"] * len(words),
        "left": list(left),
        "top": list(top),
        "width": [40] * len(words),
        "height": [12] * len(words),
        "page_num": [1] * len(words),
        "block_num": [1] * len(words),
        "par_num": [1] * len(words),
        "line_num": [1] * len(words),
    }


def install_backends(monkeypatch, pack, *, data=None, calls=None):
    calls = calls if calls is not None else []
    backend = SimpleNamespace(
        screenshot=lambda region=None: (calls.append(("screenshot", region)) or FakeImage()),
        click=lambda **kwargs: calls.append(("click", kwargs)),
        scroll=lambda *args, **kwargs: calls.append(("scroll", args, kwargs)),
        moveTo=lambda *args, **kwargs: calls.append(("move", args, kwargs)),
        dragTo=lambda *args, **kwargs: calls.append(("drag", args, kwargs)),
        write=lambda *args, **kwargs: calls.append(("write", args, kwargs)),
        press=lambda *args, **kwargs: calls.append(("press", args, kwargs)),
        hotkey=lambda *args, **kwargs: calls.append(("hotkey", args, kwargs)),
    )
    pytesseract = SimpleNamespace(
        Output=SimpleNamespace(DICT="dict"),
        image_to_data=lambda image, lang, output_type: data or ocr_data(),
    )
    monkeypatch.setattr(
        "ultk.builtins.computer_visual._optional",
        lambda name: backend if name == "pyautogui" else pytesseract,
    )
    return calls


def test_ocr_groups_words_and_applies_region_origin(pack, monkeypatch):
    calls = install_backends(monkeypatch, pack)
    result = pack.ocr_screen(region=[100, 200, 300, 200], language="eng")
    assert result["line_count"] == 1
    assert result["lines"][0]["text"] == "Save changes"
    assert result["lines"][0]["x"] == 110
    assert result["lines"][0]["y"] == 220
    assert calls[0] == ("screenshot", (100, 200, 300, 200))


def test_find_text_is_exact_and_does_not_click(pack, monkeypatch):
    calls = install_backends(monkeypatch, pack)
    result = pack.find_text(" save   changes ")
    assert result["match_count"] == 1
    assert not any(call[0] == "click" for call in calls)


def test_click_text_clicks_unique_line_center(pack, monkeypatch):
    calls = install_backends(monkeypatch, pack)
    result = pack.click_text("Save changes", region=[100, 200, 300, 200])
    assert result["status"] == "click_requested"
    assert ("click", {"x": 152, "y": 226, "button": "left"}) in calls


def test_click_text_rejects_ambiguous_target(pack, monkeypatch):
    data = ocr_data(("Save", "changes", "Save", "changes"),
                    left=(10, 55, 10, 55), top=(20, 20, 80, 80))
    # Two distinct OCR lines have separate line identifiers.
    data["line_num"] = [1, 1, 2, 2]
    calls = install_backends(monkeypatch, pack, data=data)
    with pytest.raises(ToolExecutionError, match="exactly one"):
        pack.click_text("Save changes")
    assert not any(call[0] == "click" for call in calls)


def test_ocr_rejects_language_outside_host_allowlist(pack, monkeypatch):
    calls = install_backends(monkeypatch, pack)
    with pytest.raises(ToolExecutionError, match="allowlist"):
        pack.ocr_screen(language="fra")
    assert calls == []


@pytest.mark.parametrize("region", [[0, 0, 0, 20], [0, 0, 20001, 1], [0, 0, 1]])
def test_invalid_screen_regions_are_rejected(pack, region):
    with pytest.raises(ToolExecutionError):
        pack.ocr_screen(region=region)


def test_wait_for_text_returns_when_exact_line_is_present(pack, monkeypatch):
    install_backends(monkeypatch, pack)
    result = pack.wait_for_text("Save changes", timeout_seconds=0)
    assert result["found"] is True
    assert result["attempts"] == 1


def test_scroll_and_drag_use_bounded_coordinates(pack, monkeypatch):
    calls = install_backends(monkeypatch, pack)
    pack.scroll(-100, 200, 3, "down")
    pack.drag(-100, 200, 300, 400, duration_seconds=0.8)
    assert ("scroll", (-3,), {"x": -100, "y": 200}) in calls
    assert ("move", (-100, 200), {}) in calls
    assert ("drag", (300, 400), {"duration": 0.8, "button": "left"}) in calls


def test_hotkey_rejects_secure_attention_sequence(pack):
    with pytest.raises(ToolExecutionError, match="secure-attention"):
        pack._validate_hotkey(["ctrl", "alt", "delete"])


def test_desktop_workflow_prevalidates_all_steps_before_side_effects(pack, monkeypatch):
    calls = install_backends(monkeypatch, pack)
    with pytest.raises(ToolExecutionError, match="unsupported visual desktop action"):
        pack.desktop_workflow([
            {"action": "scroll", "x": 10, "y": 20, "clicks": 2},
            {"action": "unknown"},
        ])
    assert calls == []


def test_desktop_workflow_executes_scroll_and_keyboard_steps(pack, monkeypatch):
    calls = install_backends(monkeypatch, pack)
    result = pack.desktop_workflow([
        {"action": "scroll", "x": 10, "y": 20, "clicks": 2, "direction": "up"},
        {"action": "type", "text": "hello"},
        {"action": "hotkey", "keys": ["ctrl", "s"]},
    ])
    assert result["status"] == "completed"
    assert result["steps_completed"] == 3
    assert [call[0] for call in calls] == ["scroll", "write", "hotkey"]


def test_desktop_workflow_enforces_combined_wait_budget(pack):
    with pytest.raises(ToolExecutionError, match="wait budget"):
        pack.desktop_workflow([
            {"action": "wait", "seconds": 5},
            {"action": "wait_text", "text": "Ready", "timeout_seconds": 10},
            {"action": "wait_text", "text": "Done", "timeout_seconds": 10},
            {"action": "wait", "seconds": 5},
            {"action": "wait", "seconds": 1},
        ])


def test_factory_registers_visual_tools_with_separate_capabilities():
    tools = create_computer_visual_tools(allowed_ocr_languages=("eng",))
    specs = {tool.spec.name: tool.spec for tool in tools}
    assert set(specs) == {
        "computer_visual.ocr_screen",
        "computer_visual.find_text",
        "computer_visual.click_text",
        "computer_visual.wait_for_text",
        "computer_visual.scroll",
        "computer_visual.drag",
        "computer_visual.desktop_workflow",
    }
    assert specs["computer_visual.click_text"].capabilities == frozenset({"computer:screen:control"})
    assert specs["computer_visual.find_text"].capabilities == frozenset({"computer:screen:read"})

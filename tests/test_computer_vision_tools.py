from __future__ import annotations

from pathlib import Path

import pytest

from ultk.builtins.computer_vision import (
    ComputerVisionPack,
    _iou,
    create_computer_vision_tools,
)
from ultk.engine import ToolEngine
from ultk.exceptions import ToolExecutionError
from ultk.permissions import AllowListPolicy


def test_computer_vision_pack_registers_three_tools(tmp_path: Path) -> None:
    tools = create_computer_vision_tools(template_root=tmp_path / "templates")
    assert {tool.spec.name for tool in tools} == {
        "computer_vision.match_template",
        "computer_vision.click_template",
        "computer_vision.wait_for_template",
    }


def test_engine_installs_computer_vision_tools(tmp_path: Path) -> None:
    engine = ToolEngine(policy=AllowListPolicy({"computer_vision.match_template"}))
    engine.install_computer_vision_tools(template_root=tmp_path / "templates")
    assert "computer_vision.match_template" in {
        tool.spec.name for tool in engine.registry.list()
    }


def test_template_paths_are_confined_to_configured_root(tmp_path: Path) -> None:
    root = tmp_path / "templates"
    pack = ComputerVisionPack(template_root=root)
    valid = root / "button.png"
    valid.write_bytes(b"image")
    assert pack._resolve_template("button.png") == valid.resolve()

    outside = tmp_path / "outside.png"
    outside.write_bytes(b"image")
    with pytest.raises(ToolExecutionError, match="inside the configured"):
        pack._resolve_template(str(outside))


def test_template_path_rejects_unsupported_extensions_and_oversize(tmp_path: Path) -> None:
    root = tmp_path / "templates"
    pack = ComputerVisionPack(template_root=root, max_template_bytes=4)
    unsupported = root / "script.py"
    unsupported.write_bytes(b"x")
    with pytest.raises(ToolExecutionError, match="supported"):
        pack._resolve_template("script.py")
    oversized = root / "large.png"
    oversized.write_bytes(b"12345")
    with pytest.raises(ToolExecutionError, match="byte limit"):
        pack._resolve_template("large.png")


@pytest.mark.parametrize(
    ("score", "count"),
    [(0.49, 1), (1.0, 1), (0.8, 0), (0.8, 21)],
)
def test_match_options_are_bounded(tmp_path: Path, score: float, count: int) -> None:
    with pytest.raises(ToolExecutionError):
        ComputerVisionPack(template_root=tmp_path)._validate_match_options(score, count)


def test_iou_is_zero_for_separate_regions_and_one_for_identical() -> None:
    a = {"x": 0, "y": 0, "width": 10, "height": 10}
    same = dict(a)
    separate = {"x": 20, "y": 20, "width": 10, "height": 10}
    assert _iou(a, same) == 1.0
    assert _iou(a, separate) == 0.0


def test_click_template_fails_closed_when_no_or_multiple_matches(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "templates"
    root.mkdir()
    (root / "icon.png").write_bytes(b"image")
    pack = ComputerVisionPack(template_root=root)
    for matches in ([], [
        {"center_x": 10, "center_y": 10, "score": 0.91},
        {"center_x": 30, "center_y": 30, "score": 0.90},
    ]):
        monkeypatch.setattr(
            pack, "_match", lambda *args, _matches=matches, **kwargs: _matches
        )
        with pytest.raises(ToolExecutionError, match="exactly one"):
            pack.click_template("icon.png")


def test_click_template_clicks_center_of_unique_match(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "templates"
    root.mkdir()
    (root / "icon.png").write_bytes(b"image")
    pack = ComputerVisionPack(template_root=root)
    calls = []
    match = {"center_x": 123, "center_y": 456, "score": 0.94}
    monkeypatch.setattr(pack, "_match", lambda *args, **kwargs: [match])

    class FakePyAutoGUI:
        @staticmethod
        def click(**kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(
        "ultk.builtins.computer_vision._optional", lambda name: FakePyAutoGUI
    )
    result = pack.click_template("icon.png")
    assert result["status"] == "click_requested"
    assert calls == [{"x": 123, "y": 456, "button": "left"}]


def test_wait_for_template_is_bounded_before_matching(tmp_path: Path) -> None:
    pack = ComputerVisionPack(template_root=tmp_path)
    with pytest.raises(ToolExecutionError, match="between 0 and 10"):
        pack.wait_for_template("missing.png", timeout_seconds=11)


def test_region_bounds_are_enforced(tmp_path: Path) -> None:
    with pytest.raises(ToolExecutionError, match="16 megapixels"):
        ComputerVisionPack(template_root=tmp_path)._region([0, 0, 5000, 5000])

from __future__ import annotations

from pathlib import Path

import pytest

from ultk.builtins.computer_grounding import (
    ComputerGroundingPack,
    create_computer_grounding_tools,
)
from ultk.engine import ToolEngine
from ultk.exceptions import ToolExecutionError


def _candidate(x: int = 10, y: int = 20, confidence: float = 0.94) -> dict:
    return {
        "label": "settings gear",
        "x": x,
        "y": y,
        "width": 20,
        "height": 20,
        "confidence": confidence,
    }


def test_grounding_pack_registers_read_and_control_tools() -> None:
    tools = create_computer_grounding_tools(grounder=lambda image, target: [])
    assert {tool.spec.name for tool in tools} == {
        "computer_grounding.locate_target",
        "computer_grounding.click_target",
    }
    read_tool, control_tool = tools
    assert read_tool.spec.capabilities == frozenset({"computer:screen:read"})
    assert control_tool.spec.capabilities == frozenset({"computer:screen:control"})


def test_engine_installs_grounding_tools() -> None:
    engine = ToolEngine()
    engine.install_computer_grounding_tools(grounder=lambda image, target: [])
    assert {
        tool.spec.name for tool in engine.registry.list()
    } >= {
        "computer_grounding.locate_target",
        "computer_grounding.click_target",
    }


def test_grounder_receives_screenshot_and_natural_language_target() -> None:
    seen = {}
    def grounder(image: bytes, target: str) -> list[dict]:
        seen["image"] = image
        seen["target"] = target
        return [_candidate()]

    pack = ComputerGroundingPack(grounder)
    pack._capture = lambda region: (b"png", 100, 100, 0, 0)
    result = pack.locate_target("the settings gear in the upper-right corner")
    assert seen == {
        "image": b"png",
        "target": "the settings gear in the upper-right corner",
    }
    assert result["candidate_count"] == 1
    assert result["candidates"][0]["center_x"] == 20
    assert result["candidates"][0]["center_y"] == 30


def test_region_origin_is_applied_to_returned_coordinates() -> None:
    pack = ComputerGroundingPack(lambda image, target: [_candidate(5, 7)])
    pack._capture = lambda region: (b"png", 100, 100, -100, 200)
    result = pack.locate_target("settings gear")
    assert result["candidates"][0]["x"] == -95
    assert result["candidates"][0]["y"] == 207


def test_low_confidence_candidates_are_filtered() -> None:
    pack = ComputerGroundingPack(
        lambda image, target: [_candidate(confidence=0.69)]
    )
    pack._capture = lambda region: (b"png", 100, 100, 0, 0)
    assert pack.locate_target("settings gear", confidence_threshold=0.70)[
        "candidate_count"
    ] == 0


@pytest.mark.parametrize(
    "candidate",
    [
        {**_candidate(), "x": -1},
        {**_candidate(), "width": 0},
        {**_candidate(), "x": 90},
        {**_candidate(), "confidence": 1.5},
        {**_candidate(), "confidence": True},
    ],
)
def test_invalid_backend_boxes_are_rejected(candidate: dict) -> None:
    pack = ComputerGroundingPack(lambda image, target: [candidate])
    pack._capture = lambda region: (b"png", 100, 100, 0, 0)
    with pytest.raises(ToolExecutionError, match="invalid bounding box"):
        pack.locate_target("settings gear")


def test_missing_backend_fails_closed() -> None:
    pack = ComputerGroundingPack(None)
    pack._capture = lambda region: (b"png", 100, 100, 0, 0)
    with pytest.raises(ToolExecutionError, match="No visual-grounding backend"):
        pack.locate_target("settings gear")


def test_backend_exception_is_normalized() -> None:
    def broken(image: bytes, target: str) -> list[dict]:
        raise RuntimeError("private backend details")

    pack = ComputerGroundingPack(broken)
    pack._capture = lambda region: (b"png", 100, 100, 0, 0)
    with pytest.raises(ToolExecutionError, match="backend failed"):
        pack.locate_target("settings gear")


def test_click_target_requires_exactly_one_accepted_candidate() -> None:
    for candidates in ([], [_candidate(), _candidate(x=50)]):
        pack = ComputerGroundingPack(lambda image, target: candidates)
        pack._capture = lambda region: (b"png", 100, 100, 0, 0)
        with pytest.raises(ToolExecutionError, match="exactly one candidate"):
            pack.click_target("settings gear")


def test_click_target_clicks_center_of_unique_candidate(monkeypatch) -> None:
    pack = ComputerGroundingPack(lambda image, target: [_candidate(10, 20)])
    pack._capture = lambda region: (b"png", 100, 100, 0, 0)
    calls = []

    class FakePyAutoGUI:
        @staticmethod
        def click(**kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(
        "ultk.builtins.computer_grounding._optional", lambda name: FakePyAutoGUI
    )
    result = pack.click_target("settings gear")
    assert result["status"] == "click_requested"
    assert calls == [{"x": 20, "y": 30, "button": "left"}]


def test_target_and_candidate_limits_are_enforced() -> None:
    pack = ComputerGroundingPack(lambda image, target: [])
    with pytest.raises(ToolExecutionError, match="1-500"):
        pack._validate_target(" ")
    with pytest.raises(ToolExecutionError, match="0.50 and 0.99"):
        pack._validate_threshold(1.0)
    with pytest.raises(ValueError, match="candidate limit"):
        ComputerGroundingPack(lambda image, target: [], max_candidates=11)


def test_backend_cannot_return_more_than_candidate_limit() -> None:
    pack = ComputerGroundingPack(
        lambda image, target: [_candidate() for _ in range(3)],
        max_candidates=2,
    )
    pack._capture = lambda region: (b"png", 100, 100, 0, 0)
    with pytest.raises(ToolExecutionError, match="candidate limit"):
        pack.locate_target("settings gear")

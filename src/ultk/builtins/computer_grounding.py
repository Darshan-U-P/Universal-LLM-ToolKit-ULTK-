"""Natural-language visual grounding for desktop GUI automation.

A host-injected vision backend receives a bounded PNG screenshot and a target
description, then returns candidate bounding boxes. ULTK validates every result
and fails closed on ambiguous targets. No model provider or network client is
bundled into this pack.
"""
from __future__ import annotations

import io
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from ultk.builtins._common import FunctionTool, object_schema
from ultk.exceptions import ToolExecutionError


class VisualGrounder(Protocol):
    """Host adapter contract for an image-plus-text visual grounding model."""

    def __call__(
        self, screenshot_png: bytes, target_description: str
    ) -> list[dict[str, Any]]:
        """Return candidates with label, x, y, width, height and confidence.

        Coordinates are pixel coordinates relative to the supplied screenshot.
        Confidence must be a numeric value from 0 to 1. The adapter is responsible
        for translating its model/provider response into this stable contract.
        """


def _optional(module: str) -> Any:
    try:
        return __import__(module)
    except ImportError as exc:
        raise ToolExecutionError(
            f"Optional dependency '{module}' is required for visual grounding."
        ) from exc


class ComputerGroundingPack:
    """Bounded screenshot grounding with unique-target-only desktop clicking."""

    def __init__(
        self,
        grounder: VisualGrounder | Callable[[bytes, str], list[dict[str, Any]]] | None,
        *,
        max_screenshot_pixels: int = 16_000_000,
        max_screenshot_bytes: int = 12_000_000,
        max_candidates: int = 10,
    ) -> None:
        if not 1 <= max_screenshot_pixels <= 16_000_000:
            raise ValueError("max_screenshot_pixels must be between 1 and 16 megapixels.")
        if not 1 <= max_screenshot_bytes <= 12_000_000:
            raise ValueError("max_screenshot_bytes must be between 1 and 12 MB.")
        if not 1 <= max_candidates <= 10:
            raise ValueError("max_candidates must be between 1 and 10.")
        self.grounder = grounder
        self.max_screenshot_pixels = max_screenshot_pixels
        self.max_screenshot_bytes = max_screenshot_bytes
        self.max_candidates = max_candidates

    @staticmethod
    def _validate_target(target: str) -> None:
        if not isinstance(target, str) or not target.strip() or len(target) > 500:
            raise ToolExecutionError(
                "target_description must contain 1-500 non-whitespace characters."
            )

    @staticmethod
    def _region(region: list[int] | None) -> tuple[int, int, int, int] | None:
        if region is None:
            return None
        if (
            not isinstance(region, (list, tuple))
            or len(region) != 4
            or any(type(value) is not int for value in region)
        ):
            raise ToolExecutionError("region must contain integer x, y, width and height.")
        x, y, width, height = region
        if not -30000 <= x <= 30000 or not -30000 <= y <= 30000:
            raise ToolExecutionError("Region origin is outside virtual-screen bounds.")
        if (
            not 1 <= width <= 20000
            or not 1 <= height <= 20000
            or width * height > 16_000_000
        ):
            raise ToolExecutionError("Region must be positive and no larger than 16 megapixels.")
        return x, y, width, height

    @staticmethod
    def _validate_threshold(confidence_threshold: float) -> None:
        if (
            type(confidence_threshold) not in {int, float}
            or not math.isfinite(confidence_threshold)
            or not 0.50 <= confidence_threshold <= 0.99
        ):
            raise ToolExecutionError("confidence_threshold must be between 0.50 and 0.99.")

    def _capture(self, region: list[int] | None) -> tuple[bytes, int, int, int, int]:
        selected = self._region(region)
        screenshot = _optional("pyautogui").screenshot(region=selected)
        width, height = screenshot.size
        if width < 1 or height < 1 or width * height > self.max_screenshot_pixels:
            raise ToolExecutionError("Captured screen exceeds the configured pixel limit.")
        output = io.BytesIO()
        screenshot.save(output, format="PNG", optimize=True)
        image_bytes = output.getvalue()
        if len(image_bytes) > self.max_screenshot_bytes:
            raise ToolExecutionError("Captured screenshot exceeds the configured byte limit.")
        origin_x, origin_y = (selected[0], selected[1]) if selected else (0, 0)
        return image_bytes, width, height, origin_x, origin_y

    def _locate(
        self,
        target_description: str,
        *,
        region: list[int] | None,
        confidence_threshold: float,
    ) -> list[dict[str, Any]]:
        self._validate_target(target_description)
        self._validate_threshold(confidence_threshold)
        if self.grounder is None or not callable(self.grounder):
            raise ToolExecutionError(
                "No visual-grounding backend is configured. Supply a host VisualGrounder adapter."
            )
        image_bytes, screen_width, screen_height, origin_x, origin_y = self._capture(region)
        try:
            raw_candidates = self.grounder(image_bytes, target_description)
        except Exception as exc:
            raise ToolExecutionError(
                f"Visual-grounding backend failed ({type(exc).__name__})."
            ) from exc
        if not isinstance(raw_candidates, list):
            raise ToolExecutionError("Visual-grounding backend must return a list of candidates.")
        if len(raw_candidates) > self.max_candidates:
            raise ToolExecutionError("Visual-grounding backend exceeded the candidate limit.")

        candidates: list[dict[str, Any]] = []
        for candidate in raw_candidates:
            if not isinstance(candidate, dict):
                raise ToolExecutionError("Each visual-grounding candidate must be an object.")
            label = candidate.get("label", target_description)
            x, y = candidate.get("x"), candidate.get("y")
            width, height = candidate.get("width"), candidate.get("height")
            confidence = candidate.get("confidence")
            numbers = (x, y, width, height, confidence)
            if (
                not isinstance(label, str)
                or len(label) > 200
                or any(type(value) not in {int, float} or not math.isfinite(value)
                       for value in numbers)
                or type(confidence) not in {int, float}
                or not 0.0 <= confidence <= 1.0
                or type(x) not in {int, float}
                or type(y) not in {int, float}
                or type(width) not in {int, float}
                or type(height) not in {int, float}
                or width <= 0
                or height <= 0
                or x < 0
                or y < 0
                or x + width > screen_width
                or y + height > screen_height
            ):
                raise ToolExecutionError("Visual-grounding backend returned an invalid bounding box.")
            left, top = int(round(x)), int(round(y))
            box_width, box_height = int(round(width)), int(round(height))
            if box_width < 1 or box_height < 1:
                raise ToolExecutionError("Visual-grounding bounding box is too small.")
            candidates.append({
                "label": label or target_description,
                "x": left + origin_x,
                "y": top + origin_y,
                "width": box_width,
                "height": box_height,
                "center_x": left + origin_x + box_width // 2,
                "center_y": top + origin_y + box_height // 2,
                "confidence": round(float(confidence), 4),
            })
        return sorted(candidates, key=lambda item: item["confidence"], reverse=True)

    def locate_target(
        self,
        target_description: str,
        region: list[int] | None = None,
        confidence_threshold: float = 0.70,
    ) -> dict[str, Any]:
        candidates = self._locate(
            target_description, region=region, confidence_threshold=confidence_threshold
        )
        accepted = [
            item for item in candidates if item["confidence"] >= confidence_threshold
        ]
        return {
            "target_description": target_description,
            "candidate_count": len(accepted),
            "candidates": accepted,
            "confidence_semantics": (
                "backend-reported model confidence; not a calibrated probability or guarantee"
            ),
        }

    def click_target(
        self,
        target_description: str,
        region: list[int] | None = None,
        confidence_threshold: float = 0.85,
        button: str = "left",
    ) -> dict[str, Any]:
        if button not in {"left", "middle", "right"}:
            raise ToolExecutionError("Mouse button must be left, middle or right.")
        candidates = self._locate(
            target_description, region=region, confidence_threshold=confidence_threshold
        )
        accepted = [
            item for item in candidates if item["confidence"] >= confidence_threshold
        ]
        if len(accepted) != 1:
            raise ToolExecutionError(
                "Visual target must resolve to exactly one candidate above the confidence "
                f"threshold; found {len(accepted)}. No click was issued."
            )
        match = accepted[0]
        _optional("pyautogui").click(
            x=match["center_x"], y=match["center_y"], button=button
        )
        return {
            "target_description": target_description,
            "label": match["label"],
            "x": match["center_x"],
            "y": match["center_y"],
            "confidence": match["confidence"],
            "status": "click_requested",
        }


def create_computer_grounding_tools(
    *,
    grounder: VisualGrounder | Callable[[bytes, str], list[dict[str, Any]]] | None = None,
    max_screenshot_pixels: int = 16_000_000,
    max_screenshot_bytes: int = 12_000_000,
    max_candidates: int = 10,
) -> tuple[FunctionTool, ...]:
    """Create natural-language visual-grounding tools using a host-supplied backend."""
    pack = ComputerGroundingPack(
        grounder,
        max_screenshot_pixels=max_screenshot_pixels,
        max_screenshot_bytes=max_screenshot_bytes,
        max_candidates=max_candidates,
    )
    region = {
        "type": ["array", "null"],
        "items": {"type": "integer"},
        "minItems": 4,
        "maxItems": 4,
    }
    target = {"type": "string", "minLength": 1, "maxLength": 500}
    threshold = {"type": "number", "minimum": 0.50, "maximum": 0.99}
    return (
        FunctionTool(
            "computer_grounding.locate_target",
            "Locate a natural-language-described desktop element and return bounded candidate boxes.",
            object_schema({
                "target_description": target,
                "region": region,
                "confidence_threshold": threshold,
            }, ["target_description"]),
            "computer:screen:read",
            pack.locate_target,
            timeout=35,
        ),
        FunctionTool(
            "computer_grounding.click_target",
            "Click a natural-language-described desktop element only when exactly one candidate "
            "exceeds the confidence threshold.",
            object_schema({
                "target_description": target,
                "region": region,
                "confidence_threshold": threshold,
                "button": {"type": "string", "enum": ["left", "middle", "right"]},
            }, ["target_description"]),
            "computer:screen:control",
            pack.click_target,
            timeout=35,
        ),
    )

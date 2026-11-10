"""Bounded image-template recognition for desktop GUI automation.

Templates are host-supplied image files. Matching uses OpenCV multi-scale
normalized correlation; this is not general-purpose semantic object detection.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ultk.builtins._common import FunctionTool, object_schema
from ultk.exceptions import ToolExecutionError

_ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
_SCALES = (0.80, 0.90, 1.00, 1.10, 1.20)


def _optional(module: str) -> Any:
    try:
        return __import__(module)
    except ImportError as exc:
        raise ToolExecutionError(
            f"Optional dependency '{module}' is required for image-template recognition."
        ) from exc


def _iou(a: dict[str, Any], b: dict[str, Any]) -> float:
    left = max(a["x"], b["x"])
    top = max(a["y"], b["y"])
    right = min(a["x"] + a["width"], b["x"] + b["width"])
    bottom = min(a["y"] + a["height"], b["y"] + b["height"])
    intersection = max(0, right - left) * max(0, bottom - top)
    union = a["width"] * a["height"] + b["width"] * b["height"] - intersection
    return intersection / union if union else 0.0


class ComputerVisionPack:
    """Multi-scale image-template matching with fail-closed desktop actions."""

    def __init__(
        self,
        *,
        template_root: str | Path = "./computer_templates",
        max_template_bytes: int = 2_000_000,
        max_template_pixels: int = 2_000_000,
    ) -> None:
        self.template_root = Path(template_root).expanduser().resolve()
        self.template_root.mkdir(parents=True, exist_ok=True)
        if not 1 <= max_template_bytes <= 10_000_000:
            raise ValueError("max_template_bytes must be between 1 and 10 MB.")
        if not 1 <= max_template_pixels <= 4_000_000:
            raise ValueError("max_template_pixels must be between 1 and 4 megapixels.")
        self.max_template_bytes = max_template_bytes
        self.max_template_pixels = max_template_pixels

    def _resolve_template(self, template: str) -> Path:
        if not isinstance(template, str) or not template.strip() or len(template) > 500:
            raise ToolExecutionError("A template file path of 1-500 characters is required.")
        candidate = Path(template).expanduser()
        if not candidate.is_absolute():
            candidate = self.template_root / candidate
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(self.template_root)
        except (OSError, ValueError) as exc:
            raise ToolExecutionError("Template must be an existing file inside the configured template root.") from exc
        if not resolved.is_file() or resolved.suffix.lower() not in _ALLOWED_EXTENSIONS:
            raise ToolExecutionError("Template must be a supported PNG, JPEG, BMP or WebP image file.")
        try:
            if resolved.stat().st_size > self.max_template_bytes:
                raise ToolExecutionError("Template file exceeds the configured byte limit.")
        except OSError as exc:
            raise ToolExecutionError("Template file could not be inspected.") from exc
        return resolved

    @staticmethod
    def _region(region: list[int] | None) -> tuple[int, int, int, int] | None:
        if region is None:
            return None
        if (
            not isinstance(region, (list, tuple)) or len(region) != 4
            or any(type(v) is not int for v in region)
        ):
            raise ToolExecutionError("region must contain integer x, y, width and height.")
        x, y, width, height = region
        if not -30000 <= x <= 30000 or not -30000 <= y <= 30000:
            raise ToolExecutionError("Region origin is outside virtual-screen bounds.")
        if not 1 <= width <= 20000 or not 1 <= height <= 20000 or width * height > 16_000_000:
            raise ToolExecutionError("Region must be positive and no larger than 16 megapixels.")
        return x, y, width, height

    @staticmethod
    def _validate_match_options(min_score: float, max_matches: int) -> None:
        if type(min_score) not in {int, float} or not 0.50 <= min_score <= 0.99:
            raise ToolExecutionError("min_score must be between 0.50 and 0.99.")
        if type(max_matches) is not int or not 1 <= max_matches <= 20:
            raise ToolExecutionError("max_matches must be an integer between 1 and 20.")

    @staticmethod
    def _suppress_overlaps(candidates: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        for item in sorted(candidates, key=lambda row: row["score"], reverse=True):
            if all(_iou(item, existing) < 0.30 for existing in selected):
                selected.append(item)
                if len(selected) >= limit:
                    break
        return selected

    def _match(
        self,
        template_path: Path,
        *,
        region: list[int] | None,
        min_score: float,
        max_matches: int,
    ) -> list[dict[str, Any]]:
        self._validate_match_options(min_score, max_matches)
        selected_region = self._region(region)
        pyautogui = _optional("pyautogui")
        screenshot = pyautogui.screenshot(region=selected_region)
        if screenshot.width * screenshot.height > 16_000_000:
            raise ToolExecutionError("Captured screen exceeds the 16-megapixel computer-vision limit.")

        cv2 = _optional("cv2")
        np = _optional("numpy")
        try:
            screen_rgb = np.asarray(screenshot.convert("RGB"))
            screen_gray = cv2.cvtColor(screen_rgb, cv2.COLOR_RGB2GRAY)
            template_gray = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
            if template_gray is None:
                raise ToolExecutionError("OpenCV could not decode the template image.")
            template_height, template_width = template_gray.shape[:2]
            if template_width * template_height > self.max_template_pixels:
                raise ToolExecutionError("Template exceeds the configured pixel limit.")
            origin_x, origin_y = (selected_region[0], selected_region[1]) if selected_region else (0, 0)
            candidates: list[dict[str, Any]] = []
            for scale in _SCALES:
                width = max(1, round(template_width * scale))
                height = max(1, round(template_height * scale))
                if width > screen_gray.shape[1] or height > screen_gray.shape[0]:
                    continue
                resized = cv2.resize(template_gray, (width, height), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
                response = cv2.matchTemplate(screen_gray, resized, cv2.TM_CCOEFF_NORMED)
                for _ in range(max_matches):
                    _, score, _, location = cv2.minMaxLoc(response)
                    if score < min_score:
                        break
                    x, y = location
                    candidates.append({
                        "x": int(x + origin_x), "y": int(y + origin_y),
                        "width": width, "height": height,
                        "center_x": int(x + origin_x + width // 2),
                        "center_y": int(y + origin_y + height // 2),
                        "score": round(float(score), 4), "scale": scale,
                    })
                    x0, y0 = max(0, x - width // 3), max(0, y - height // 3)
                    x1 = min(response.shape[1], x + width + width // 3)
                    y1 = min(response.shape[0], y + height + height // 3)
                    response[y0:y1, x0:x1] = -1.0
            return self._suppress_overlaps(candidates, max_matches)
        except ToolExecutionError:
            raise
        except Exception as exc:
            raise ToolExecutionError(
                f"Image-template matching failed ({type(exc).__name__})."
            ) from exc

    def match_template(
        self,
        template: str,
        region: list[int] | None = None,
        min_score: float = 0.85,
        max_matches: int = 10,
    ) -> dict[str, Any]:
        path = self._resolve_template(template)
        matches = self._match(path, region=region, min_score=min_score, max_matches=max_matches)
        return {
            "template": path.name,
            "match_count": len(matches),
            "matches": matches,
            "score_semantics": "normalized grayscale correlation; not a probability",
        }

    def click_template(
        self,
        template: str,
        region: list[int] | None = None,
        min_score: float = 0.85,
        button: str = "left",
    ) -> dict[str, Any]:
        if button not in {"left", "middle", "right"}:
            raise ToolExecutionError("Mouse button must be left, middle or right.")
        path = self._resolve_template(template)
        matches = self._match(path, region=region, min_score=min_score, max_matches=20)
        if len(matches) != 1:
            raise ToolExecutionError(
                f"Template target must produce exactly one non-overlapping match; found {len(matches)}."
            )
        match = matches[0]
        _optional("pyautogui").click(x=match["center_x"], y=match["center_y"], button=button)
        return {
            "template": path.name, "x": match["center_x"], "y": match["center_y"],
            "score": match["score"], "status": "click_requested",
        }

    def wait_for_template(
        self,
        template: str,
        timeout_seconds: float = 5.0,
        poll_interval_seconds: float = 0.5,
        region: list[int] | None = None,
        min_score: float = 0.85,
    ) -> dict[str, Any]:
        if type(timeout_seconds) not in {int, float} or not 0 <= timeout_seconds <= 10:
            raise ToolExecutionError("timeout_seconds must be between 0 and 10.")
        if type(poll_interval_seconds) not in {int, float} or not 0.1 <= poll_interval_seconds <= 2:
            raise ToolExecutionError("poll_interval_seconds must be between 0.1 and 2.")
        path = self._resolve_template(template)
        self._region(region)
        self._validate_match_options(min_score, 20)
        deadline = time.monotonic() + timeout_seconds
        attempts = 0
        while True:
            attempts += 1
            matches = self._match(path, region=region, min_score=min_score, max_matches=20)
            if matches:
                return {"found": True, "template": path.name, "matches": matches,
                        "attempts": attempts}
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {"found": False, "template": path.name, "attempts": attempts}
            time.sleep(min(float(poll_interval_seconds), remaining))


def create_computer_vision_tools(
    *,
    template_root: str | Path = "./computer_templates",
    max_template_bytes: int = 2_000_000,
    max_template_pixels: int = 2_000_000,
) -> tuple[FunctionTool, ...]:
    """Create image-template recognition tools using host-supplied reference images."""
    pack = ComputerVisionPack(
        template_root=template_root,
        max_template_bytes=max_template_bytes,
        max_template_pixels=max_template_pixels,
    )
    region = {
        "type": ["array", "null"], "items": {"type": "integer"},
        "minItems": 4, "maxItems": 4,
    }
    template = {"type": "string", "minLength": 1, "maxLength": 500}
    score = {"type": "number", "minimum": 0.50, "maximum": 0.99}
    return (
        FunctionTool(
            "computer_vision.match_template",
            "Find bounded multi-scale matches for a host-supplied image template on the desktop.",
            object_schema({
                "template": template, "region": region, "min_score": score,
                "max_matches": {"type": "integer", "minimum": 1, "maximum": 20},
            }, ["template"]),
            "computer:screen:read", pack.match_template, timeout=30,
        ),
        FunctionTool(
            "computer_vision.click_template",
            "Click a uniquely detected image template; zero or multiple detections fail closed.",
            object_schema({
                "template": template, "region": region, "min_score": score,
                "button": {"type": "string", "enum": ["left", "middle", "right"]},
            }, ["template"]),
            "computer:screen:control", pack.click_template, timeout=30,
        ),
        FunctionTool(
            "computer_vision.wait_for_template",
            "Wait up to 10 seconds for an image template to appear on the desktop.",
            object_schema({
                "template": template,
                "timeout_seconds": {"type": "number", "minimum": 0, "maximum": 10},
                "poll_interval_seconds": {"type": "number", "minimum": 0.1, "maximum": 2},
                "region": region, "min_score": score,
            }, ["template"]),
            "computer:screen:read", pack.wait_for_template, timeout=35,
        ),
    )

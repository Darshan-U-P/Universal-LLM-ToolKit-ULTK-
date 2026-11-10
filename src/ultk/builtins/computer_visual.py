"""Visual desktop interaction tools with OCR-backed targeting.

This pack adds text-aware GUI interaction on top of the coordinate/window tools.
It is not a sandbox: actions run in the host user's active desktop session.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from ultk.builtins._common import FunctionTool, object_schema
from ultk.exceptions import ToolExecutionError

_SAFE_KEYS = {
    "enter", "esc", "tab", "space", "backspace", "delete", "insert",
    "home", "end", "pageup", "pagedown", "up", "down", "left", "right",
    "shift", "ctrl", "alt", "win", "command", "option", "capslock",
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
    *list("abcdefghijklmnopqrstuvwxyz0123456789"),
}
_MODIFIERS = {"ctrl", "alt", "shift", "win", "command", "option"}
_WORD_SPACE = re.compile(r"\s+")


def _optional(module: str) -> Any:
    try:
        return __import__(module)
    except ImportError as exc:
        raise ToolExecutionError(
            f"Optional dependency '{module}' is required for this visual desktop operation."
        ) from exc


class ComputerVisualPack:
    """OCR-backed screen understanding and bounded visual desktop interaction."""

    def __init__(
        self,
        *,
        allowed_ocr_languages: tuple[str, ...] = ("eng",),
        max_ocr_lines: int = 100,
    ) -> None:
        if not allowed_ocr_languages or any(
            not re.fullmatch(r"[A-Za-z0-9_+-]{1,32}", lang)
            for lang in allowed_ocr_languages
        ):
            raise ValueError("At least one valid OCR language must be configured.")
        if not 1 <= max_ocr_lines <= 300:
            raise ValueError("max_ocr_lines must be between 1 and 300.")
        self.allowed_languages = frozenset(allowed_ocr_languages)
        self.max_ocr_lines = max_ocr_lines

    @staticmethod
    def _region(region: list[int] | None) -> tuple[int, int, int, int] | None:
        if region is None:
            return None
        if (
            not isinstance(region, (list, tuple))
            or len(region) != 4
            or any(type(value) is not int for value in region)
        ):
            raise ToolExecutionError("region must contain four integer values: x, y, width, height.")
        x, y, width, height = region
        if not -30000 <= x <= 30000 or not -30000 <= y <= 30000:
            raise ToolExecutionError("Region origin is outside the supported virtual-screen bounds.")
        if not 1 <= width <= 20000 or not 1 <= height <= 20000:
            raise ToolExecutionError("Region width and height must be between 1 and 20000.")
        if width * height > 40_000_000:
            raise ToolExecutionError("Requested screen region exceeds the 40-megapixel limit.")
        return x, y, width, height

    def _capture(self, region: list[int] | None = None) -> tuple[Any, tuple[int, int]]:
        selected = self._region(region)
        pyautogui = _optional("pyautogui")
        image = pyautogui.screenshot(region=selected)
        if image.width * image.height > 40_000_000:
            raise ToolExecutionError("Captured screen image exceeds the 40-megapixel limit.")
        origin = (selected[0], selected[1]) if selected else (0, 0)
        return image, origin

    def _ocr(
        self,
        *,
        region: list[int] | None = None,
        language: str = "eng",
        max_lines: int | None = None,
    ) -> list[dict[str, Any]]:
        if language not in self.allowed_languages:
            raise ToolExecutionError("OCR language is not in the host-configured allowlist.")
        limit = self.max_ocr_lines if max_lines is None else max_lines
        if not 1 <= limit <= self.max_ocr_lines:
            raise ToolExecutionError(
                f"max_lines must be between 1 and the configured limit ({self.max_ocr_lines})."
            )
        image, origin = self._capture(region)
        pytesseract = _optional("pytesseract")
        try:
            data = pytesseract.image_to_data(
                image, lang=language, output_type=pytesseract.Output.DICT
            )
        except Exception as exc:  # noqa: BLE001 - normalize OCR engine/backend errors
            raise ToolExecutionError(
                f"OCR failed ({type(exc).__name__}); verify the Tesseract binary and language data."
            ) from exc

        grouped: dict[tuple[int, int, int, int], dict[str, Any]] = {}
        count = len(data.get("text", []))
        for index in range(count):
            word = str(data["text"][index]).strip()
            if not word:
                continue
            try:
                confidence = float(data["conf"][index])
                left = int(data["left"][index])
                top = int(data["top"][index])
                width = int(data["width"][index])
                height = int(data["height"][index])
                key = (
                    int(data["page_num"][index]), int(data["block_num"][index]),
                    int(data["par_num"][index]), int(data["line_num"][index]),
                )
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise ToolExecutionError("OCR engine returned malformed word geometry.") from exc
            if confidence < 0:
                continue
            line = grouped.setdefault(key, {
                "words": [], "left": left, "top": top,
                "right": left + width, "bottom": top + height,
                "confidences": [],
            })
            line["words"].append(word)
            line["left"] = min(line["left"], left)
            line["top"] = min(line["top"], top)
            line["right"] = max(line["right"], left + width)
            line["bottom"] = max(line["bottom"], top + height)
            line["confidences"].append(confidence)

        rows = []
        for line in grouped.values():
            text = " ".join(line["words"]).strip()
            if not text:
                continue
            rows.append({
                "text": text[:1000],
                "x": line["left"] + origin[0],
                "y": line["top"] + origin[1],
                "width": line["right"] - line["left"],
                "height": line["bottom"] - line["top"],
                "confidence": round(sum(line["confidences"]) / len(line["confidences"]), 2),
            })
            if len(rows) >= limit:
                break
        return rows

    @staticmethod
    def _normalize_text(value: str) -> str:
        return _WORD_SPACE.sub(" ", value).strip().casefold()

    def ocr_screen(
        self, region: list[int] | None = None, language: str = "eng",
        max_lines: int = 100,
    ) -> dict[str, Any]:
        rows = self._ocr(region=region, language=language, max_lines=max_lines)
        return {"line_count": len(rows), "lines": rows}

    def find_text(
        self, text: str, region: list[int] | None = None, language: str = "eng",
    ) -> dict[str, Any]:
        target = self._normalize_text(text)
        if not target or len(target) > 200:
            raise ToolExecutionError("Search text must contain 1–200 non-whitespace characters.")
        rows = self._ocr(region=region, language=language)
        matches = [row for row in rows if self._normalize_text(row["text"]) == target]
        return {"text": text, "match_count": len(matches), "matches": matches}

    def click_text(
        self, text: str, region: list[int] | None = None, language: str = "eng",
        button: str = "left",
    ) -> dict[str, Any]:
        if button not in {"left", "middle", "right"}:
            raise ToolExecutionError("Mouse button must be left, middle or right.")
        result = self.find_text(text, region=region, language=language)
        if result["match_count"] != 1:
            raise ToolExecutionError(
                f"Text target must match exactly one visible line; found {result['match_count']}."
            )
        match = result["matches"][0]
        x = match["x"] + match["width"] // 2
        y = match["y"] + match["height"] // 2
        _optional("pyautogui").click(x=x, y=y, button=button)
        return {"text": match["text"], "x": x, "y": y, "status": "click_requested"}

    def wait_for_text(
        self, text: str, timeout_seconds: float = 5.0,
        poll_interval_seconds: float = 0.5, region: list[int] | None = None,
        language: str = "eng",
    ) -> dict[str, Any]:
        target = self._normalize_text(text)
        if not target or len(target) > 200:
            raise ToolExecutionError("Search text must contain 1–200 non-whitespace characters.")
        if not 0 <= timeout_seconds <= 15:
            raise ToolExecutionError("timeout_seconds must be between 0 and 15.")
        if not 0.1 <= poll_interval_seconds <= 2:
            raise ToolExecutionError("poll_interval_seconds must be between 0.1 and 2.")
        self._region(region)
        deadline = time.monotonic() + timeout_seconds
        attempts = 0
        while True:
            attempts += 1
            matches = [
                row for row in self._ocr(region=region, language=language)
                if self._normalize_text(row["text"]) == target
            ]
            if matches:
                return {"found": True, "text": matches[0]["text"], "attempts": attempts,
                        "elapsed_seconds": round(timeout_seconds - max(0, deadline - time.monotonic()), 3)}
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {"found": False, "text": text, "attempts": attempts,
                        "elapsed_seconds": timeout_seconds}
            time.sleep(min(poll_interval_seconds, remaining))

    @staticmethod
    def _coordinates(x: int, y: int) -> None:
        if type(x) is not int or type(y) is not int or not -30000 <= x <= 30000 or not -30000 <= y <= 30000:
            raise ToolExecutionError("Coordinates must be integers within virtual-screen bounds.")

    def scroll(self, x: int, y: int, clicks: int, direction: str = "down") -> dict[str, Any]:
        self._coordinates(x, y)
        if type(clicks) is not int or not 1 <= clicks <= 100:
            raise ToolExecutionError("Scroll clicks must be an integer between 1 and 100.")
        if direction not in {"up", "down"}:
            raise ToolExecutionError("Scroll direction must be up or down.")
        amount = clicks if direction == "up" else -clicks
        _optional("pyautogui").scroll(amount, x=x, y=y)
        return {"x": x, "y": y, "direction": direction, "clicks": clicks}

    def drag(
        self, start_x: int, start_y: int, end_x: int, end_y: int,
        duration_seconds: float = 0.5, button: str = "left",
    ) -> dict[str, Any]:
        self._coordinates(start_x, start_y)
        self._coordinates(end_x, end_y)
        if not 0.1 <= duration_seconds <= 5:
            raise ToolExecutionError("Drag duration must be between 0.1 and 5 seconds.")
        if button not in {"left", "middle", "right"}:
            raise ToolExecutionError("Drag button must be left, middle or right.")
        pyautogui = _optional("pyautogui")
        pyautogui.moveTo(start_x, start_y)
        pyautogui.dragTo(end_x, end_y, duration=duration_seconds, button=button)
        return {"start": [start_x, start_y], "end": [end_x, end_y],
                "duration_seconds": duration_seconds, "button": button}

    @staticmethod
    def _validate_hotkey(keys: list[str]) -> list[str]:
        if not isinstance(keys, list) or not 1 <= len(keys) <= 5:
            raise ToolExecutionError("Hotkey must contain 1–5 keys.")
        normalized = [str(key).casefold() for key in keys]
        if any(key not in _SAFE_KEYS for key in normalized):
            raise ToolExecutionError("Hotkey contains a key outside the safe allowlist.")
        if {"ctrl", "alt", "delete"}.issubset(normalized):
            raise ToolExecutionError("The secure-attention key sequence is not permitted.")
        if len(normalized) != len(set(normalized)):
            raise ToolExecutionError("Hotkey keys must not be duplicated.")
        if sum(key in _MODIFIERS for key in normalized) > 3:
            raise ToolExecutionError("Hotkey contains too many modifiers.")
        return normalized

    def desktop_workflow(self, steps: list[dict[str, Any]]) -> dict[str, Any]:
        """Execute a fully prevalidated, bounded sequence of visual desktop actions."""
        if not isinstance(steps, list) or not 1 <= len(steps) <= 30:
            raise ToolExecutionError("Visual desktop workflow must contain 1–30 steps.")
        prepared: list[tuple[str, dict[str, Any]]] = []
        wait_budget = 0.0
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                raise ToolExecutionError(f"Step {index} must be an object.")
            action = step.get("action")
            if action == "scroll":
                x, y, clicks, direction = step.get("x"), step.get("y"), step.get("clicks", 1), step.get("direction", "down")
                self._coordinates(x, y)
                if type(clicks) is not int or not 1 <= clicks <= 100 or direction not in {"up", "down"}:
                    raise ToolExecutionError(f"Step {index} has invalid scroll options.")
                prepared.append((action, {"x": x, "y": y, "clicks": clicks, "direction": direction}))
            elif action == "drag":
                sx, sy, ex, ey = (step.get("start_x"), step.get("start_y"), step.get("end_x"), step.get("end_y"))
                self._coordinates(sx, sy)
                self._coordinates(ex, ey)
                duration, button = step.get("duration_seconds", 0.5), step.get("button", "left")
                if type(duration) not in {int, float} or not 0.1 <= duration <= 5 or button not in {"left", "middle", "right"}:
                    raise ToolExecutionError(f"Step {index} has invalid drag options.")
                prepared.append((action, {"start_x": sx, "start_y": sy, "end_x": ex, "end_y": ey, "duration_seconds": float(duration), "button": button}))
            elif action in {"click_text", "wait_text"}:
                target = step.get("text")
                if not isinstance(target, str) or not 1 <= len(target.strip()) <= 200:
                    raise ToolExecutionError(f"Step {index} requires target text of 1–200 characters.")
                region = self._region(step.get("region"))
                language = step.get("language", "eng")
                if language not in self.allowed_languages:
                    raise ToolExecutionError(f"Step {index} uses an OCR language outside the host allowlist.")
                payload = {"text": target, "region": list(region) if region else None, "language": language}
                if action == "click_text":
                    button = step.get("button", "left")
                    if button not in {"left", "middle", "right"}:
                        raise ToolExecutionError(f"Step {index} has an invalid mouse button.")
                    payload["button"] = button
                else:
                    timeout = step.get("timeout_seconds", 5.0)
                    interval = step.get("poll_interval_seconds", 0.5)
                    if type(timeout) not in {int, float} or not 0 <= timeout <= 10:
                        raise ToolExecutionError(f"Step {index} text wait must be between 0 and 10 seconds.")
                    if type(interval) not in {int, float} or not 0.1 <= interval <= 2:
                        raise ToolExecutionError(f"Step {index} has an invalid OCR poll interval.")
                    wait_budget += float(timeout)
                    payload.update({"timeout_seconds": float(timeout), "poll_interval_seconds": float(interval)})
                prepared.append((action, payload))
            elif action == "type":
                value = step.get("text")
                if not isinstance(value, str) or len(value) > 1000:
                    raise ToolExecutionError(f"Step {index} text must be at most 1000 characters.")
                prepared.append((action, {"text": value}))
            elif action == "press":
                key = step.get("key")
                if not isinstance(key, str) or key.casefold() not in _SAFE_KEYS:
                    raise ToolExecutionError(f"Step {index} uses an unsupported key.")
                prepared.append((action, {"key": key.casefold()}))
            elif action == "hotkey":
                prepared.append((action, {"keys": self._validate_hotkey(step.get("keys"))}))
            elif action == "wait":
                seconds = step.get("seconds", 0)
                if type(seconds) not in {int, float} or not 0 <= seconds <= 5:
                    raise ToolExecutionError(f"Step {index} wait must be between 0 and 5 seconds.")
                wait_budget += float(seconds)
                prepared.append((action, {"seconds": float(seconds)}))
            else:
                raise ToolExecutionError(f"Step {index} has an unsupported visual desktop action.")
        if wait_budget > 30:
            raise ToolExecutionError("Combined workflow wait budget cannot exceed 30 seconds.")

        pyautogui = None
        results = []
        for index, (action, payload) in enumerate(prepared):
            try:
                if action == "scroll":
                    result = self.scroll(**payload)
                elif action == "drag":
                    result = self.drag(**payload)
                elif action == "click_text":
                    result = self.click_text(**payload)
                elif action == "wait_text":
                    result = self.wait_for_text(**payload)
                    if not result["found"]:
                        raise ToolExecutionError(f"Text target was not found at step {index}.")
                elif action == "wait":
                    time.sleep(payload["seconds"])
                    result = {"waited_seconds": payload["seconds"]}
                else:
                    if pyautogui is None:
                        pyautogui = _optional("pyautogui")
                    if action == "type":
                        pyautogui.write(payload["text"], interval=0.01)
                        result = {"characters": len(payload["text"])}
                    elif action == "press":
                        pyautogui.press(payload["key"])
                        result = {"key": payload["key"]}
                    else:
                        pyautogui.hotkey(*payload["keys"])
                        result = {"keys": payload["keys"]}
                results.append({"step": index, "action": action, "status": "completed", "result": result})
            except ToolExecutionError as exc:
                raise ToolExecutionError(
                    f"Visual workflow stopped at step {index}; {len(results)} prior steps completed. {exc}"
                ) from exc
        return {"status": "completed", "steps_completed": len(results), "results": results}


def create_computer_visual_tools(
    *,
    allowed_ocr_languages: tuple[str, ...] = ("eng",),
    max_ocr_lines: int = 100,
) -> tuple[FunctionTool, ...]:
    """Create OCR-backed desktop tools; host must install Tesseract separately."""
    pack = ComputerVisualPack(
        allowed_ocr_languages=allowed_ocr_languages, max_ocr_lines=max_ocr_lines
    )
    region_schema = {
        "type": ["array", "null"], "items": {"type": "integer"},
        "minItems": 4, "maxItems": 4,
    }
    language_schema = {"type": "string", "enum": sorted(pack.allowed_languages)}
    text_schema = {"type": "string", "minLength": 1, "maxLength": 200}
    return (
        FunctionTool(
            "computer_visual.ocr_screen",
            "Read visible screen text with OCR and return bounded line text and coordinates.",
            object_schema({"region": region_schema, "language": language_schema,
                           "max_lines": {"type": "integer", "minimum": 1, "maximum": max_ocr_lines}}),
            "computer:screen:read", pack.ocr_screen, timeout=25,
        ),
        FunctionTool(
            "computer_visual.find_text",
            "Find exact visible text lines on the screen without clicking.",
            object_schema({"text": text_schema, "region": region_schema,
                           "language": language_schema}, ["text"]),
            "computer:screen:read", pack.find_text, timeout=25,
        ),
        FunctionTool(
            "computer_visual.click_text",
            "Click the center of one uniquely matching visible text line; ambiguous matches fail closed.",
            object_schema({"text": text_schema, "region": region_schema,
                           "language": language_schema,
                           "button": {"type": "string", "enum": ["left", "middle", "right"]}},
                          ["text"]),
            "computer:screen:control", pack.click_text, timeout=25,
        ),
        FunctionTool(
            "computer_visual.wait_for_text",
            "Wait up to 15 seconds for an exact visible text line to appear.",
            object_schema({"text": text_schema,
                           "timeout_seconds": {"type": "number", "minimum": 0, "maximum": 15},
                           "poll_interval_seconds": {"type": "number", "minimum": 0.1, "maximum": 2},
                           "region": region_schema, "language": language_schema}, ["text"]),
            "computer:screen:read", pack.wait_for_text, timeout=25,
        ),
        FunctionTool(
            "computer_visual.scroll",
            "Scroll at a bounded virtual-screen coordinate.",
            object_schema({"x": {"type": "integer", "minimum": -30000, "maximum": 30000},
                           "y": {"type": "integer", "minimum": -30000, "maximum": 30000},
                           "clicks": {"type": "integer", "minimum": 1, "maximum": 100},
                           "direction": {"type": "string", "enum": ["up", "down"]}},
                          ["x", "y", "clicks"]),
            "computer:mouse:scroll", pack.scroll,
        ),
        FunctionTool(
            "computer_visual.drag",
            "Drag the pointer between two bounded virtual-screen coordinates.",
            object_schema({
                "start_x": {"type": "integer", "minimum": -30000, "maximum": 30000},
                "start_y": {"type": "integer", "minimum": -30000, "maximum": 30000},
                "end_x": {"type": "integer", "minimum": -30000, "maximum": 30000},
                "end_y": {"type": "integer", "minimum": -30000, "maximum": 30000},
                "duration_seconds": {"type": "number", "minimum": 0.1, "maximum": 5},
                "button": {"type": "string", "enum": ["left", "middle", "right"]},
            }, ["start_x", "start_y", "end_x", "end_y"]),
            "computer:mouse:drag", pack.drag,
        ),
        FunctionTool(
            "computer_visual.desktop_workflow",
            "Run a prevalidated visual workflow of OCR text targets, scrolling, dragging, typing and keys.",
            object_schema({"steps": {"type": "array", "minItems": 1, "maxItems": 30,
                                     "items": {"type": "object"}}}, ["steps"]),
            "computer:workflow:visual", pack.desktop_workflow, timeout=90,
        ),
    )

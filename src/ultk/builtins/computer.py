"""Computer, desktop and environment tools.

Desktop automation is inherently state-changing. Install only in trusted interactive
sessions, grant narrow capabilities, and do not treat this pack as a security sandbox.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from ultk.builtins._common import FunctionTool, object_schema
from ultk.exceptions import ToolExecutionError


def _optional(module: str) -> Any:
    try:
        return __import__(module)
    except ImportError as exc:
        raise ToolExecutionError(
            f"Optional dependency '{module}' is required for this operation."
        ) from exc


def _clipboard_read() -> dict[str, str]:
    pyperclip = _optional("pyperclip")
    return {"text": pyperclip.paste()}


def _clipboard_write(text: str) -> dict[str, Any]:
    pyperclip = _optional("pyperclip")
    pyperclip.copy(text)
    return {"written_characters": len(text)}


def _screenshot(path: str, image_root: str, region: list[int] | None = None) -> dict[str, Any]:
    pyautogui = _optional("pyautogui")
    root = Path(image_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = (root / path).resolve()
    if not target.is_relative_to(root) or target.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        raise ToolExecutionError("Screenshot path must be a PNG/JPEG inside image_root.")
    if region is not None and (len(region) != 4 or any(type(v) is not int or v < 0 for v in region)):
        raise ToolExecutionError("region must contain four non-negative integers.")
    image = pyautogui.screenshot(region=tuple(region) if region else None)
    image.save(target)
    return {"path": str(target), "width": image.width, "height": image.height}


def _mouse(action: str, x: int, y: int, button: str = "left", clicks: int = 1) -> dict[str, Any]:
    pyautogui = _optional("pyautogui")
    if action == "move":
        pyautogui.moveTo(x, y, duration=0.15)
    elif action == "click":
        if button not in {"left", "middle", "right"} or not 1 <= clicks <= 3:
            raise ToolExecutionError("Unsupported mouse button or click count.")
        pyautogui.click(x=x, y=y, button=button, clicks=clicks)
    else:
        raise ToolExecutionError("action must be 'move' or 'click'.")
    return {"action": action, "x": x, "y": y}


def _keyboard(action: str, text: str | None = None, key: str | None = None) -> dict[str, Any]:
    pyautogui = _optional("pyautogui")
    if action == "type":
        if text is None or len(text) > 4000:
            raise ToolExecutionError("type requires text of at most 4000 characters.")
        pyautogui.write(text, interval=0.01)
    elif action == "press":
        if key not in {"enter", "esc", "tab", "space", "backspace", "delete",
                       "up", "down", "left", "right", "home", "end"}:
            raise ToolExecutionError("Key is not in the safe key allowlist.")
        pyautogui.press(key)
    else:
        raise ToolExecutionError("action must be 'type' or 'press'.")
    return {"action": action, "characters": len(text or ""), "key": key}


def _windows() -> list[dict[str, Any]]:
    pywinctl = _optional("pywinctl")
    return [{"title": w.title[:300], "left": w.left, "top": w.top,
             "width": w.width, "height": w.height, "active": w.isActive}
            for w in pywinctl.getAllWindows() if w.title][:100]


def _activate_window(title_contains: str) -> dict[str, str]:
    pywinctl = _optional("pywinctl")
    matches = [w for w in pywinctl.getAllWindows()
               if title_contains.casefold() in w.title.casefold()]
    if len(matches) != 1:
        raise ToolExecutionError("Window selector must match exactly one visible window.")
    matches[0].activate()
    return {"title": matches[0].title, "status": "activation_requested"}


def _launch_app(alias: str, allowed_apps: dict[str, str]) -> dict[str, Any]:
    executable = allowed_apps.get(alias)
    if not executable:
        raise ToolExecutionError("Application alias is not allowlisted.")
    path = Path(executable).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ToolExecutionError("Configured application is not a file.")
    process = subprocess.Popen([str(path)], shell=False, close_fds=True,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
    return {"alias": alias, "pid": process.pid, "status": "started"}


def _environment_get(name: str, allowed_names: list[str]) -> dict[str, Any]:
    if name not in allowed_names:
        raise ToolExecutionError("Environment variable name is not allowlisted.")
    return {"name": name, "value": os.environ.get(name)}


def create_computer_tools(*, image_root: str | Path = "./screenshots",
                          allowed_apps: dict[str, str] | None = None,
                          allowed_environment_names: tuple[str, ...] = ()) -> tuple[FunctionTool, ...]:
    """Create computer tools. Dependencies pyautogui, pyperclip and pywinctl are optional."""
    root = str(Path(image_root).expanduser().resolve())
    apps = dict(allowed_apps or {})
    env_names = list(allowed_environment_names)
    return (
        FunctionTool("computer.clipboard_read", "Read current clipboard text.",
                     object_schema({}), "computer:clipboard:read", _clipboard_read),
        FunctionTool("computer.clipboard_write", "Replace clipboard contents with supplied text.",
                     object_schema({"text": {"type": "string", "maxLength": 20000}}, ["text"]),
                     "computer:clipboard:write", _clipboard_write),
        FunctionTool("computer.screenshot", "Capture the desktop to a PNG/JPEG file under image_root.",
                     object_schema({"path": {"type": "string", "minLength": 1, "maxLength": 180},
                                    "region": {"type": ["array", "null"], "items": {"type": "integer", "minimum": 0},
                                               "minItems": 4, "maxItems": 4}}, ["path"]),
                     "computer:screenshot", lambda path, region=None: _screenshot(path, root, region)),
        FunctionTool("computer.mouse", "Move the pointer or click at screen coordinates.",
                     object_schema({"action": {"type": "string", "enum": ["move", "click"]},
                                    "x": {"type": "integer", "minimum": 0, "maximum": 20000},
                                    "y": {"type": "integer", "minimum": 0, "maximum": 20000},
                                    "button": {"type": "string", "enum": ["left", "middle", "right"]},
                                    "clicks": {"type": "integer", "minimum": 1, "maximum": 3}},
                                  ["action", "x", "y"]),
                     "computer:mouse", _mouse),
        FunctionTool("computer.keyboard", "Type text or press one key from a restricted allowlist.",
                     object_schema({"action": {"type": "string", "enum": ["type", "press"]},
                                    "text": {"type": "string", "maxLength": 4000},
                                    "key": {"type": "string"}}, ["action"]),
                     "computer:keyboard", _keyboard),
        FunctionTool("computer.list_windows", "List visible desktop windows and their geometry.",
                     object_schema({}), "computer:window:read", _windows),
        FunctionTool("computer.activate_window", "Activate a window when its title substring matches exactly one window.",
                     object_schema({"title_contains": {"type": "string", "minLength": 1, "maxLength": 120}},
                                   ["title_contains"]),
                     "computer:window:control", _activate_window),
        FunctionTool("computer.launch_app", "Launch an application from configured exact executable aliases.",
                     object_schema({"alias": {"type": "string", "enum": sorted(apps)}}, ["alias"]),
                     "computer:app:launch", lambda alias: _launch_app(alias, apps)),
        FunctionTool("computer.get_environment_variable", "Read only explicitly allowlisted environment variable names.",
                     object_schema({"name": {"type": "string", "enum": env_names}}, ["name"]),
                     "computer:environment:read", lambda name: _environment_get(name, env_names)),
    )

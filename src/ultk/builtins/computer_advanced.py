"""Advanced desktop window, application lifecycle and workflow tools."""
from __future__ import annotations

import time
from typing import Any

import psutil

from ultk.exceptions import ToolExecutionError
from ultk.builtins._common import FunctionTool, object_schema


def _optional(module: str) -> Any:
    try:
        return __import__(module)
    except ImportError as exc:
        raise ToolExecutionError(f"Optional dependency '{module}' is required.") from exc


def _window_action(title_contains: str, action: str, x: int | None = None,
                   y: int | None = None, width: int | None = None,
                   height: int | None = None) -> dict[str, Any]:
    gw = _optional("pygetwindow")
    matches = [w for w in gw.getAllWindows()
               if title_contains.casefold() in w.title.casefold()]
    if len(matches) != 1:
        raise ToolExecutionError("Window selector must match exactly one window.")
    window = matches[0]
    if action == "move":
        if x is None or y is None:
            raise ToolExecutionError("move requires x and y.")
        window.moveTo(x, y)
    elif action == "resize":
        if width is None or height is None or width < 100 or height < 100:
            raise ToolExecutionError("resize requires width and height >= 100.")
        window.resizeTo(width, height)
    elif action in {"maximize", "minimize", "restore"}:
        getattr(window, action)()
    else:
        raise ToolExecutionError("Unsupported window action.")
    return {"title": window.title, "action": action, "status": "requested"}


def _app_list() -> list[dict[str, Any]]:
    rows = []
    for proc in psutil.process_iter(["pid", "name", "status", "create_time"]):
        try:
            info = proc.info
            rows.append({"pid": info["pid"], "name": info["name"],
                         "status": info["status"], "create_time": info["create_time"]})
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        if len(rows) >= 100:
            break
    return rows


def _app_action(pid: int, expected_create_time: float, action: str) -> dict[str, Any]:
    if pid == psutil.Process().pid:
        raise ToolExecutionError("ULTK cannot control its own host process.")
    try:
        proc = psutil.Process(pid)
        if abs(proc.create_time() - expected_create_time) > 0.01:
            raise ToolExecutionError("PID identity check failed.")
        if action == "terminate":
            proc.terminate()
        elif action == "kill":
            proc.kill()
        else:
            raise ToolExecutionError("action must be terminate or kill.")
        return {"pid": pid, "action": action, "status": "requested"}
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as exc:
        raise ToolExecutionError("Application process is unavailable or access was denied.") from exc


def _workflow(steps: list[dict[str, Any]]) -> dict[str, Any]:
    if not 1 <= len(steps) <= 30:
        raise ToolExecutionError("A desktop workflow must contain 1–30 steps.")
    pyautogui = _optional("pyautogui")
    results = []
    for index, step in enumerate(steps):
        action = step.get("action")
        if action == "click":
            pyautogui.click(x=step["x"], y=step["y"], clicks=step.get("clicks", 1))
        elif action == "move":
            pyautogui.moveTo(step["x"], step["y"], duration=0.15)
        elif action == "type":
            value = step.get("text", "")
            if len(value) > 1000:
                raise ToolExecutionError("Workflow text step exceeds 1000 characters.")
            pyautogui.write(value, interval=0.01)
        elif action == "press":
            key = step.get("key")
            if key not in {"enter", "esc", "tab", "space", "backspace", "delete",
                           "up", "down", "left", "right", "home", "end"}:
                raise ToolExecutionError("Workflow key is not allowlisted.")
            pyautogui.press(key)
        elif action == "wait":
            seconds = step.get("seconds", 0)
            if not 0 <= seconds <= 3:
                raise ToolExecutionError("Workflow waits are limited to 3 seconds.")
            time.sleep(seconds)
        elif action == "screenshot":
            image = pyautogui.screenshot()
            results.append({"step": index, "action": "screenshot",
                            "width": image.width, "height": image.height})
            continue
        else:
            raise ToolExecutionError(f"Unsupported desktop workflow action at step {index}.")
        results.append({"step": index, "action": action, "status": "completed"})
    return {"steps_completed": len(results), "results": results}


def create_advanced_computer_tools() -> tuple[FunctionTool, ...]:
    """Create additional desktop management tools."""
    return (
        FunctionTool("computer.window_action", "Move, resize, maximize, minimize or restore one uniquely matched window.",
                     object_schema({"title_contains": {"type": "string", "minLength": 1, "maxLength": 120},
                                    "action": {"type": "string", "enum": ["move", "resize", "maximize", "minimize", "restore"]},
                                    "x": {"type": "integer", "minimum": -10000, "maximum": 20000},
                                    "y": {"type": "integer", "minimum": -10000, "maximum": 20000},
                                    "width": {"type": "integer", "minimum": 100, "maximum": 20000},
                                    "height": {"type": "integer", "minimum": 100, "maximum": 20000}},
                                   ["title_contains", "action"]),
                     "computer:window:control", _window_action),
        FunctionTool("computer.list_applications", "List running processes with PID and creation time for safe identification.",
                     object_schema({}), "computer:app:read", _app_list),
        FunctionTool("computer.application_action", "Terminate or kill a process after PID and creation-time verification.",
                     object_schema({"pid": {"type": "integer", "minimum": 1},
                                    "expected_create_time": {"type": "number", "minimum": 0},
                                    "action": {"type": "string", "enum": ["terminate", "kill"]}},
                                   ["pid", "expected_create_time", "action"]),
                     "computer:app:control", _app_action),
        FunctionTool("computer.desktop_workflow", "Run a bounded sequence of desktop mouse, keyboard and wait actions.",
                     object_schema({"steps": {"type": "array", "minItems": 1, "maxItems": 30,
                                               "items": {"type": "object"}}}, ["steps"]),
                     "computer:workflow", _workflow, timeout=45),
    )

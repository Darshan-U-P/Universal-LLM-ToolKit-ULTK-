"""Cross-platform desktop and operating-system administration tools.

This pack complements the small GUI and PowerShell packs. It provides persistent
logical desktop sessions, monitor/window management, keyboard sequences, accessibility
inspection, bounded OS administration, filesystem metadata/permissions, hardware and
USB inventory, and OS event-log polling. Platform-specific operations fail closed when
their native backend is unavailable.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import psutil

from ultk.builtins._common import FunctionTool, object_schema
from ultk.exceptions import ToolExecutionError

_SAFE_SERVICE = re.compile(r"^[A-Za-z0-9_.@:-]{1,128}$")
_SAFE_CHANNELS = {"System", "Application", "Security", "Setup"}
_SAFE_KEYS = {
    "enter", "esc", "tab", "space", "backspace", "delete", "insert",
    "home", "end", "pageup", "pagedown", "up", "down", "left", "right",
    "shift", "ctrl", "alt", "win", "command", "option", "capslock",
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
    *list("abcdefghijklmnopqrstuvwxyz0123456789"),
}


def _optional(module: str) -> Any:
    try:
        return __import__(module)
    except ImportError as exc:
        raise ToolExecutionError(
            f"Optional dependency '{module}' is required for this platform operation."
        ) from exc


def _run(argv: list[str], *, timeout: int = 15, output_limit: int = 200_000) -> dict[str, Any]:
    """Run a fixed native command without a shell, with bounded output and timeout."""
    try:
        safe_env = {key: value for key, value in os.environ.items()
                    if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"}}
        result = subprocess.run(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            shell=False, timeout=timeout, check=False, env=safe_env,
        )
    except FileNotFoundError as exc:
        raise ToolExecutionError(f"Required platform command is unavailable: {Path(argv[0]).name}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolExecutionError("Platform operation timed out.") from exc
    except OSError as exc:
        raise ToolExecutionError(f"Platform operation failed ({type(exc).__name__}).") from exc
    return {
        "return_code": result.returncode,
        "stdout": result.stdout[:output_limit].decode("utf-8", errors="replace"),
        "stderr": result.stderr[:output_limit].decode("utf-8", errors="replace"),
        "output_truncated": len(result.stdout) > output_limit or len(result.stderr) > output_limit,
    }


class ComputerOSPack:
    def __init__(
        self, *, filesystem_root: str | Path, state_database: str | Path,
        allowed_services: frozenset[str] = frozenset(),
        allow_posix_chmod: bool = True, allow_posix_chown: bool = False,
        max_output_bytes: int = 200_000,
    ) -> None:
        self.root = Path(filesystem_root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = Path(state_database).expanduser().resolve()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.allowed_services = frozenset(allowed_services)
        self.allow_chmod = allow_posix_chmod
        self.allow_chown = allow_posix_chown
        self.max_output = max_output_bytes
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS desktop_sessions (
                session_id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at REAL NOT NULL,
                updated_at REAL NOT NULL, state_json TEXT NOT NULL, closed INTEGER NOT NULL DEFAULT 0
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS event_watches (
                watch_id TEXT PRIMARY KEY, channel TEXT NOT NULL, created_at REAL NOT NULL,
                description TEXT NOT NULL
            )""")

    @staticmethod
    def _text(value: str, label: str, limit: int = 256) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
            raise ToolExecutionError(f"Invalid {label}.")
        return value.strip()

    def _contains_symlink(self, relative_path: str) -> bool:
        candidate = Path(relative_path)
        current = self.root
        for part in candidate.parts:
            current = current / part
            if current.is_symlink():
                return True
        return False

    def resolve(self, relative_path: str) -> Path:
        value = self._text(relative_path, "relative path", 1000)
        candidate = Path(value)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ToolExecutionError("Path must be relative and cannot contain parent traversal.")
        path = (self.root / candidate).resolve()
        if not path.is_relative_to(self.root):
            raise ToolExecutionError("Path escapes the configured computer OS filesystem root.")
        return path

    # Persistent logical sessions: durable ULTK context, not OS logon sessions.
    def session_create(self, name: str, initial_state: dict[str, Any] | None = None) -> dict[str, Any]:
        label = self._text(name, "session name", 120)
        state = initial_state or {}
        if not isinstance(state, dict) or len(json.dumps(state, default=str)) > 16_000:
            raise ToolExecutionError("Initial desktop session state must be a small JSON object.")
        session_id = uuid.uuid4().hex
        now = time.time()
        with self._connect() as db:
            db.execute("INSERT INTO desktop_sessions VALUES(?,?,?,?,?,0)",
                       (session_id, label, now, now, json.dumps(state, ensure_ascii=False)))
        return {"session_id": session_id, "name": label, "created_at": now, "state": state}

    def session_update(self, session_id: str, state: dict[str, Any]) -> dict[str, Any]:
        sid = self._text(session_id, "session ID", 80)
        if not isinstance(state, dict) or len(json.dumps(state, default=str)) > 16_000:
            raise ToolExecutionError("Session state must be a small JSON object.")
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE desktop_sessions SET state_json=?,updated_at=? WHERE session_id=? AND closed=0",
                (json.dumps(state, ensure_ascii=False), time.time(), sid))
            if cursor.rowcount != 1:
                raise ToolExecutionError("Desktop session does not exist or is closed.")
        return {"session_id": sid, "status": "updated", "state": state}

    def session_get(self, session_id: str) -> dict[str, Any]:
        sid = self._text(session_id, "session ID", 80)
        with self._connect() as db:
            row = db.execute("SELECT * FROM desktop_sessions WHERE session_id=?", (sid,)).fetchone()
        if row is None:
            raise ToolExecutionError("Desktop session was not found.")
        return {"session_id": sid, "name": row["name"], "created_at": row["created_at"],
                "updated_at": row["updated_at"], "closed": bool(row["closed"]),
                "state": json.loads(row["state_json"])}

    def session_list(self, include_closed: bool = False) -> list[dict[str, Any]]:
        query = "SELECT session_id,name,created_at,updated_at,closed FROM desktop_sessions"
        if not include_closed:
            query += " WHERE closed=0"
        query += " ORDER BY updated_at DESC LIMIT 100"
        with self._connect() as db:
            return [dict(row) for row in db.execute(query).fetchall()]

    def session_close(self, session_id: str) -> dict[str, Any]:
        sid = self._text(session_id, "session ID", 80)
        with self._connect() as db:
            cursor = db.execute("UPDATE desktop_sessions SET closed=1,updated_at=? WHERE session_id=? AND closed=0",
                                (time.time(), sid))
            if cursor.rowcount != 1:
                raise ToolExecutionError("Desktop session does not exist or is already closed.")
        return {"session_id": sid, "status": "closed"}

    # Displays and windows.
    def monitors(self) -> list[dict[str, Any]]:
        try:
            screeninfo = _optional("screeninfo")
            rows = []
            for index, monitor in enumerate(screeninfo.get_monitors()):
                rows.append({"index": index, "name": monitor.name, "x": monitor.x, "y": monitor.y,
                             "width": monitor.width, "height": monitor.height,
                             "primary": bool(getattr(monitor, "is_primary", False))})
            if rows:
                return rows[:16]
        except ToolExecutionError:
            pass
        try:
            pyautogui = _optional("pyautogui")
            width, height = pyautogui.size()
            return [{"index": 0, "name": "primary", "x": 0, "y": 0,
                     "width": width, "height": height, "primary": True,
                     "note": "Fallback primary-display geometry; install screeninfo for multi-monitor enumeration."}]
        except ToolExecutionError:
            return [{"index": 0, "name": "unknown", "x": 0, "y": 0, "width": None,
                     "height": None, "primary": True, "note": "No display backend available."}]

    def windows(self) -> list[dict[str, Any]]:
        pywinctl = _optional("pywinctl")
        rows = []
        for window in pywinctl.getAllWindows():
            if not window.title:
                continue
            rows.append({"title": window.title[:300], "left": window.left, "top": window.top,
                         "width": window.width, "height": window.height,
                         "active": bool(window.isActive), "visible": bool(window.isVisible)})
            if len(rows) >= 200:
                break
        return rows

    def _window(self, selector: str) -> Any:
        needle = self._text(selector, "window selector", 180).casefold()
        pywinctl = _optional("pywinctl")
        matches = [window for window in pywinctl.getAllWindows()
                   if needle in (window.title or "").casefold()]
        if len(matches) != 1:
            raise ToolExecutionError("Window selector must match exactly one window.")
        return matches[0]

    def window_action(self, selector: str, action: str, x: int | None = None,
                      y: int | None = None, width: int | None = None,
                      height: int | None = None) -> dict[str, Any]:
        window = self._window(selector)
        if action == "move":
            if x is None or y is None:
                raise ToolExecutionError("move requires x and y.")
            window.moveTo(x, y)
        elif action == "resize":
            if width is None or height is None or width < 100 or height < 100:
                raise ToolExecutionError("resize requires width and height >= 100.")
            window.resizeTo(width, height)
        elif action in {"maximize", "minimize", "restore", "activate", "close"}:
            getattr(window, {"activate": "activate", "close": "close"}.get(action, action))()
        else:
            raise ToolExecutionError("Unsupported window action.")
        return {"title": window.title, "action": action, "status": "requested"}

    def snap_window(self, selector: str, monitor_index: int, position: str) -> dict[str, Any]:
        monitors = self.monitors()
        if type(monitor_index) is not int or not 0 <= monitor_index < len(monitors):
            raise ToolExecutionError("Monitor index is unavailable.")
        monitor = monitors[monitor_index]
        if not isinstance(monitor.get("width"), int) or not isinstance(monitor.get("height"), int):
            raise ToolExecutionError("Monitor geometry is unavailable.")
        x, y, width, height = monitor["x"], monitor["y"], monitor["width"], monitor["height"]
        half_w, half_h = width // 2, height // 2
        boxes = {
            "left": (x, y, half_w, height), "right": (x + half_w, y, width - half_w, height),
            "top": (x, y, width, half_h), "bottom": (x, y + half_h, width, height - half_h),
            "top_left": (x, y, half_w, half_h), "top_right": (x + half_w, y, width-half_w, half_h),
            "bottom_left": (x, y + half_h, half_w, height-half_h),
            "bottom_right": (x + half_w, y + half_h, width-half_w, height-half_h),
            "maximize": (x, y, width, height),
        }
        if position not in boxes:
            raise ToolExecutionError("Unsupported snap position.")
        window = self._window(selector)
        left, top, w, h = boxes[position]
        window.moveTo(left, top)
        window.resizeTo(w, h)
        return {"title": window.title, "monitor": monitor_index, "position": position,
                "geometry": {"x": left, "y": top, "width": w, "height": h}}

    def arrange_windows(self, placements: list[dict[str, Any]], monitor_index: int) -> dict[str, Any]:
        if not isinstance(placements, list) or not 1 <= len(placements) <= 16:
            raise ToolExecutionError("Provide between 1 and 16 window placements.")
        monitors = self.monitors()
        if type(monitor_index) is not int or not 0 <= monitor_index < len(monitors):
            raise ToolExecutionError("Monitor index is unavailable.")
        monitor = monitors[monitor_index]
        if not isinstance(monitor.get("width"), int) or not isinstance(monitor.get("height"), int):
            raise ToolExecutionError("Monitor geometry is unavailable.")
        # Validate every placement before moving any window.
        prepared = []
        for item in placements:
            if not isinstance(item, dict):
                raise ToolExecutionError("Each placement must be an object.")
            selector = self._text(item.get("title_contains", ""), "window selector", 180)
            x, y, width, height = (item.get(key) for key in ("x", "y", "width", "height"))
            if any(type(v) is not int for v in (x, y, width, height)) or width < 100 or height < 100:
                raise ToolExecutionError("Each placement requires integer x/y and width/height >= 100.")
            if x < 0 or y < 0 or x + width > monitor["width"] or y + height > monitor["height"]:
                raise ToolExecutionError("Window placement must remain within selected monitor bounds.")
            prepared.append((self._window(selector), monitor["x"] + x, monitor["y"] + y, width, height))
        result = []
        for window, x, y, width, height in prepared:
            window.moveTo(x, y)
            window.resizeTo(width, height)
            result.append({"title": window.title, "x": x, "y": y, "width": width, "height": height})
        return {"monitor": monitor_index, "arranged": result}

    # Keyboard shortcuts and bounded sequences.
    def keyboard_shortcut(self, keys: list[str]) -> dict[str, Any]:
        if not isinstance(keys, list) or not 1 <= len(keys) <= 5:
            raise ToolExecutionError("A shortcut must contain 1–5 keys.")
        normalized = [self._text(key, "key", 20).casefold() for key in keys]
        if any(key not in _SAFE_KEYS for key in normalized):
            raise ToolExecutionError("Shortcut contains a key outside the supported allowlist.")
        pyautogui = _optional("pyautogui")
        pyautogui.hotkey(*normalized)
        return {"keys": normalized, "status": "sent"}

    def keyboard_sequence(self, steps: list[dict[str, Any]]) -> dict[str, Any]:
        if not isinstance(steps, list) or not 1 <= len(steps) <= 30:
            raise ToolExecutionError("Keyboard sequence must contain 1–30 steps.")
        validated = []
        for step in steps:
            if not isinstance(step, dict):
                raise ToolExecutionError("Each keyboard step must be an object.")
            action = step.get("action")
            if action == "type":
                value = step.get("text")
                if not isinstance(value, str) or len(value) > 1000:
                    raise ToolExecutionError("Typed text must be a string of at most 1000 characters.")
                validated.append((action, value))
            elif action == "press":
                key = self._text(step.get("key", ""), "key", 20).casefold()
                if key not in _SAFE_KEYS:
                    raise ToolExecutionError("Key is not supported.")
                validated.append((action, key))
            elif action == "hotkey":
                keys = step.get("keys")
                if not isinstance(keys, list) or not 1 <= len(keys) <= 5 or any(
                    not isinstance(key, str) or key.casefold() not in _SAFE_KEYS for key in keys):
                    raise ToolExecutionError("Invalid hotkey step.")
                validated.append((action, [key.casefold() for key in keys]))
            elif action == "wait":
                seconds = step.get("seconds", 0)
                if type(seconds) not in {int, float} or not 0 <= seconds <= 3:
                    raise ToolExecutionError("Wait steps are limited to 3 seconds.")
                validated.append((action, float(seconds)))
            else:
                raise ToolExecutionError("Unsupported keyboard sequence action.")
        pyautogui = _optional("pyautogui")
        results = []
        for action, value in validated:
            if action == "type":
                pyautogui.write(value, interval=0.01)
            elif action == "press":
                pyautogui.press(value)
            elif action == "hotkey":
                pyautogui.hotkey(*value)
            else:
                time.sleep(value)
            results.append({"action": action, "status": "completed"})
        return {"steps_completed": len(results), "results": results}

    # Native accessibility/UI automation.
    def accessibility_inspect(self, title_contains: str, max_elements: int = 100) -> dict[str, Any]:
        if not 1 <= max_elements <= 300:
            raise ToolExecutionError("max_elements must be between 1 and 300.")
        if os.name == "nt":
            from pywinauto import Desktop
            matches = [window for window in Desktop(backend="uia").windows()
                       if title_contains.casefold() in window.window_text().casefold()]
            if len(matches) != 1:
                raise ToolExecutionError("Accessibility selector must match exactly one window.")
            rows = []
            for control in matches[0].descendants()[:max_elements]:
                try:
                    info = control.element_info
                    rows.append({"name": info.name[:300], "control_type": info.control_type,
                                 "automation_id": info.automation_id, "class_name": info.class_name,
                                 "enabled": control.is_enabled(), "visible": control.is_visible(),
                                 "rectangle": str(control.rectangle())})
                except Exception:  # noqa: BLE001
                    continue
            return {"backend": "Windows UI Automation", "window": matches[0].window_text(),
                    "elements": rows}
        if platform.system() == "Linux":
            pyatspi = _optional("pyatspi")
            desktop = pyatspi.Registry.getDesktop(0)
            rows: list[dict[str, Any]] = []
            def walk(node: Any, depth: int = 0) -> None:
                if len(rows) >= max_elements or depth > 12:
                    return
                try:
                    name = node.name or ""
                    role = node.getRoleName()
                    if name or role:
                        rows.append({"name": name[:300], "role": role})
                    for index in range(node.childCount):
                        walk(node.getChildAtIndex(index), depth + 1)
                        if len(rows) >= max_elements:
                            break
                except Exception:  # noqa: BLE001
                    return
            for index in range(desktop.childCount):
                app = desktop.getChildAtIndex(index)
                if title_contains.casefold() in (app.name or "").casefold():
                    walk(app)
            if not rows:
                raise ToolExecutionError("No matching accessible application was found.")
            return {"backend": "AT-SPI", "elements": rows}
        raise ToolExecutionError("Accessibility inspection backend is not implemented for this OS.")

    def accessibility_click(self, title_contains: str, automation_id: str) -> dict[str, Any]:
        if os.name != "nt":
            raise ToolExecutionError("Element invocation is currently supported through Windows UI Automation only.")
        from pywinauto import Desktop
        matches = [window for window in Desktop(backend="uia").windows()
                   if title_contains.casefold() in window.window_text().casefold()]
        if len(matches) != 1:
            raise ToolExecutionError("Accessibility selector must match exactly one window.")
        element_id = self._text(automation_id, "automation ID", 256)
        controls = [control for control in matches[0].descendants()
                    if control.element_info.automation_id == element_id]
        if len(controls) != 1:
            raise ToolExecutionError("Automation ID must match exactly one element.")
        if not controls[0].is_enabled() or not controls[0].is_visible():
            raise ToolExecutionError("Target UI element is not enabled and visible.")
        controls[0].click_input()
        return {"window": matches[0].window_text(), "automation_id": element_id,
                "status": "click_requested"}

    # Virtual desktops (backend-specific; no fake support on unsupported platforms).
    def virtual_desktops(self, action: str, desktop_number: int | None = None) -> dict[str, Any]:
        if os.name == "nt":
            try:
                import pyvda
            except ImportError as exc:
                raise ToolExecutionError("Install the optional pyvda package for Windows virtual desktops.") from exc
            if action == "current":
                desktop = pyvda.Desktop.current()
                return {"backend": "pyvda", "current_number": desktop.number}
            if action == "create":
                desktop = pyvda.Desktop.create()
                return {"backend": "pyvda", "created_number": desktop.number}
            if action == "switch":
                if type(desktop_number) is not int or desktop_number < 0:
                    raise ToolExecutionError("desktop_number must be a non-negative integer.")
                desktop = pyvda.Desktop(desktop_number)
                desktop.go()
                return {"backend": "pyvda", "switched_to": desktop_number}
            raise ToolExecutionError("Windows virtual desktop action must be current, create or switch.")
        if platform.system() == "Linux":
            executable = shutil.which("wmctrl")
            if not executable:
                raise ToolExecutionError("Install wmctrl and use an X11-compatible desktop session.")
            if action == "list":
                result = _run([executable, "-d"], output_limit=self.max_output)
                if result["return_code"] != 0:
                    raise ToolExecutionError("wmctrl could not enumerate virtual desktops.")
                return {"backend": "wmctrl", **result}
            if action == "switch":
                if type(desktop_number) is not int or desktop_number < 0:
                    raise ToolExecutionError("desktop_number must be non-negative.")
                result = _run([executable, "-s", str(desktop_number)], output_limit=self.max_output)
                if result["return_code"] != 0:
                    raise ToolExecutionError("wmctrl could not switch virtual desktop.")
                return {"backend": "wmctrl", "switched_to": desktop_number}
            if action == "create":
                raise ToolExecutionError("Virtual desktop creation is controlled by the Linux window manager.")
        raise ToolExecutionError("Virtual desktop management is unavailable on this platform/backend.")

    # Cross-platform services: read-only listing plus allowlisted mutations.
    def services(self) -> dict[str, Any]:
        if os.name == "nt":
            result = _run(["sc.exe", "query", "state=", "all"], output_limit=self.max_output)
        elif platform.system() == "Linux":
            result = _run(["systemctl", "list-units", "--type=service", "--all", "--no-pager",
                           "--no-legend"], output_limit=self.max_output)
        elif platform.system() == "Darwin":
            result = _run(["launchctl", "list"], output_limit=self.max_output)
        else:
            raise ToolExecutionError("Service listing is unsupported on this OS.")
        return {"platform": platform.system(), **result}

    def service_action(self, service: str, action: str) -> dict[str, Any]:
        name = self._text(service, "service name", 128)
        if not _SAFE_SERVICE.fullmatch(name) or name not in self.allowed_services:
            raise ToolExecutionError("Service is not in the host-configured exact allowlist.")
        if action not in {"start", "stop", "restart"}:
            raise ToolExecutionError("Unsupported service action.")
        if os.name == "nt":
            command = {"start": "start", "stop": "stop", "restart": "restart"}[action]
            result = _run(["sc.exe", command, name], output_limit=self.max_output)
        elif platform.system() == "Linux":
            result = _run(["systemctl", action, name], timeout=30, output_limit=self.max_output)
        else:
            raise ToolExecutionError("Service mutations are currently supported on Windows and Linux.")
        return {"service": name, "action": action, **result}

    # Filesystem permissions and ownership within a configured root.
    def file_metadata(self, relative_path: str) -> dict[str, Any]:
        path = self.resolve(relative_path)
        if not path.exists() and not path.is_symlink():
            raise ToolExecutionError("Path does not exist.")
        lexical = self.root / Path(relative_path)
        stat = lexical.lstat()
        result: dict[str, Any] = {
            "path": relative_path, "is_symlink": self._contains_symlink(relative_path),
            "is_directory": path.is_dir(), "size_bytes": stat.st_size,
            "modified_at": stat.st_mtime, "mode_octal": oct(stat.st_mode & 0o7777),
        }
        if hasattr(stat, "st_uid"):
            result["uid"] = stat.st_uid
            result["gid"] = stat.st_gid
        if hasattr(stat, "st_file_attributes"):
            result["windows_file_attributes"] = stat.st_file_attributes
        return result

    def chmod(self, relative_path: str, mode: int) -> dict[str, Any]:
        if os.name == "nt" or not self.allow_chmod:
            raise ToolExecutionError("POSIX chmod is disabled or unavailable on this platform.")
        if type(mode) is not int or not 0 <= mode <= 0o777:
            raise ToolExecutionError("mode must be an integer from 0000 to 0777.")
        path = self.resolve(relative_path)
        if self._contains_symlink(relative_path) or not path.exists():
            raise ToolExecutionError("Refusing chmod on missing paths or symlinks.")
        path.chmod(mode)
        return self.file_metadata(relative_path)

    def chown(self, relative_path: str, uid: int, gid: int) -> dict[str, Any]:
        if os.name == "nt" or not self.allow_chown or not hasattr(os, "chown"):
            raise ToolExecutionError("Ownership changes are disabled or unavailable.")
        if type(uid) is not int or type(gid) is not int or uid < -1 or gid < -1:
            raise ToolExecutionError("uid and gid must be non-negative integers or -1.")
        path = self.resolve(relative_path)
        if self._contains_symlink(relative_path) or not path.exists():
            raise ToolExecutionError("Refusing ownership changes on missing paths or symlinks.")
        os.chown(path, uid, gid, follow_symlinks=False)
        return self.file_metadata(relative_path)

    # Hardware and device inventory.
    def hardware(self) -> dict[str, Any]:
        vm = psutil.virtual_memory()
        cpu_freq = psutil.cpu_freq()
        try:
            temps = psutil.sensors_temperatures()
            temperatures = {name: [{"label": item.label, "current": item.current,
                                    "high": item.high, "critical": item.critical}
                                   for item in values[:16]] for name, values in temps.items()}
        except (AttributeError, OSError, NotImplementedError):
            temperatures = {}
        try:
            battery = psutil.sensors_battery()
            battery_info = None if battery is None else {
                "percent": battery.percent, "plugged": battery.power_plugged,
                "seconds_left": battery.secsleft if battery.secsleft >= 0 else None}
        except (AttributeError, OSError, NotImplementedError):
            battery_info = None
        disks = []
        for part in psutil.disk_partitions(all=False)[:32]:
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disks.append({"device": part.device, "mountpoint": part.mountpoint,
                              "filesystem": part.fstype, "total_bytes": usage.total,
                              "used_bytes": usage.used, "free_bytes": usage.free})
            except (PermissionError, OSError):
                continue
        return {
            "platform": platform.platform(), "processor": platform.processor(),
            "cpu_count": psutil.cpu_count(logical=True),
            "cpu_frequency_mhz": cpu_freq.current if cpu_freq else None,
            "memory_total_bytes": vm.total, "memory_available_bytes": vm.available,
            "temperatures": temperatures, "battery": battery_info, "disks": disks,
        }

    def usb_devices(self) -> dict[str, Any]:
        if platform.system() == "Linux":
            pyudev = _optional("pyudev")
            context = pyudev.Context()
            devices = []
            for device in context.list_devices(subsystem="usb", DEVTYPE="usb_device"):
                devices.append({"vendor_id": device.get("ID_VENDOR_ID"),
                                "product_id": device.get("ID_MODEL_ID"),
                                "vendor": device.get("ID_VENDOR"),
                                "model": device.get("ID_MODEL"),
                                "serial": device.get("ID_SERIAL_SHORT"),
                                "device_node": device.device_node})
                if len(devices) >= 200:
                    break
            return {"platform": "Linux", "devices": devices}
        if os.name == "nt":
            executable = shutil.which("pnputil.exe") or shutil.which("pnputil")
            if not executable:
                raise ToolExecutionError("pnputil is unavailable.")
            result = _run([executable, "/enum-devices", "/connected", "/class", "USB"],
                          output_limit=self.max_output)
            return {"platform": "Windows", **result}
        if platform.system() == "Darwin":
            executable = shutil.which("system_profiler")
            if not executable:
                raise ToolExecutionError("system_profiler is unavailable.")
            result = _run([executable, "SPUSBDataType", "-json"], timeout=30,
                          output_limit=self.max_output)
            if result["return_code"] == 0:
                try:
                    result["devices"] = json.loads(result["stdout"])
                except json.JSONDecodeError:
                    pass
            return {"platform": "macOS", **result}
        raise ToolExecutionError("USB inventory is unsupported on this platform.")

    def network_interfaces(self) -> list[dict[str, Any]]:
        stats = psutil.net_if_stats()
        addresses = psutil.net_if_addrs()
        rows = []
        for name, entries in addresses.items():
            rows.append({"name": name, "is_up": stats[name].isup if name in stats else None,
                         "speed_mbps": stats[name].speed if name in stats else None,
                         "mtu": stats[name].mtu if name in stats else None,
                         "addresses": [{"family": str(item.family), "address": item.address,
                                        "netmask": item.netmask, "broadcast": item.broadcast}
                                       for item in entries[:12]]})
        return rows[:64]

    # Event log snapshots and persistent watch definitions; callers poll on their schedule.
    def recent_events(self, channel: str = "", limit: int = 50, since_minutes: int = 60) -> dict[str, Any]:
        if not 1 <= limit <= 200 or not 1 <= since_minutes <= 10080:
            raise ToolExecutionError("limit must be 1–200 and since_minutes 1–10080.")
        if os.name == "nt":
            channel = channel or "System"
            if channel not in _SAFE_CHANNELS:
                raise ToolExecutionError("Windows event channel is not allowlisted.")
            result = _run(["wevtutil.exe", "qe", channel, "/c:" + str(limit), "/rd:true", "/f:xml"],
                          timeout=30, output_limit=self.max_output)
            if result["return_code"] != 0:
                return {"platform": "Windows", "channel": channel, **result, "events": []}
            events = []
            try:
                root = ET.fromstring("<Events>" + result["stdout"] + "</Events>")
                for event in list(root)[:limit]:
                    system = event.find("System")
                    provider = system.find("Provider") if system is not None else None
                    event_id = system.find("EventID") if system is not None else None
                    record = system.find("EventRecordID") if system is not None else None
                    time_node = system.find("TimeCreated") if system is not None else None
                    events.append({"provider": provider.get("Name") if provider is not None else None,
                                   "event_id": event_id.text if event_id is not None else None,
                                   "record_id": record.text if record is not None else None,
                                   "time": time_node.get("SystemTime") if time_node is not None else None})
            except ET.ParseError:
                events = []
            return {"platform": "Windows", "channel": channel, "events": events,
                    "output_truncated": result["output_truncated"]}
        if platform.system() == "Linux":
            if channel not in {"", "system", "user", "kernel"}:
                raise ToolExecutionError("Linux journal channel must be system, user, kernel or empty.")
            command = ["journalctl", "--no-pager", "-n", str(limit), "-o", "json"]
            if channel == "user":
                command.append("--user")
            elif channel == "kernel":
                command.append("--dmesg")
            result = _run(command, timeout=30, output_limit=self.max_output)
            events = []
            for line in result["stdout"].splitlines():
                try:
                    item = json.loads(line)
                    events.append({"timestamp": item.get("__REALTIME_TIMESTAMP"),
                                   "priority": item.get("PRIORITY"), "unit": item.get("_SYSTEMD_UNIT"),
                                   "message": str(item.get("MESSAGE", ""))[:2000]})
                except json.JSONDecodeError:
                    continue
            return {"platform": "Linux", "channel": channel or "system", "events": events,
                    "stderr": result["stderr"], "return_code": result["return_code"],
                    "output_truncated": result["output_truncated"]}
        if platform.system() == "Darwin":
            result = _run(["log", "show", "--last", f"{since_minutes}m", "--style", "json",
                           "--info", "--debug", "--limit", str(limit)],
                          timeout=30, output_limit=self.max_output)
            events = []
            if result["return_code"] == 0:
                try:
                    parsed = json.loads(result["stdout"])
                    events = parsed[:limit] if isinstance(parsed, list) else []
                except json.JSONDecodeError:
                    pass
            return {"platform": "macOS", "events": events, "stderr": result["stderr"],
                    "return_code": result["return_code"], "output_truncated": result["output_truncated"]}
        raise ToolExecutionError("Event log retrieval is unsupported on this platform.")

    def create_event_watch(self, channel: str, description: str) -> dict[str, Any]:
        label = self._text(description, "watch description", 200)
        if os.name == "nt":
            channel = channel or "System"
            if channel not in _SAFE_CHANNELS:
                raise ToolExecutionError("Windows event channel is not allowlisted.")
        if platform.system() == "Linux" and channel not in {"", "system", "user", "kernel"}:
            raise ToolExecutionError("Linux journal channel is invalid.")
        if platform.system() == "Darwin" and channel not in {"", "system"}:
            raise ToolExecutionError("macOS unified log watch supports the system channel.")
        watch_id = uuid.uuid4().hex
        with self._connect() as db:
            db.execute("INSERT INTO event_watches VALUES(?,?,?,?)",
                       (watch_id, channel, time.time(), label))
        return {"watch_id": watch_id, "channel": channel, "description": label}

    def list_event_watches(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT watch_id,channel,created_at,description FROM event_watches ORDER BY created_at DESC LIMIT 100"
            ).fetchall()]

    def delete_event_watch(self, watch_id: str) -> dict[str, Any]:
        wid = self._text(watch_id, "watch ID", 80)
        with self._connect() as db:
            cursor = db.execute("DELETE FROM event_watches WHERE watch_id=?", (wid,))
            if cursor.rowcount != 1:
                raise ToolExecutionError("Event watch was not found.")
        return {"watch_id": wid, "status": "deleted"}


def create_computer_os_tools(
    *, filesystem_root: str | Path = ".", state_database: str | Path = "./ultk_computer_os.sqlite3",
    allowed_services: frozenset[str] = frozenset(),
    allow_posix_chmod: bool = True, allow_posix_chown: bool = False,
    max_output_bytes: int = 200_000,
) -> tuple[FunctionTool, ...]:
    """Create the cross-platform computer/OS pack; optional native backends load on demand."""
    pack = ComputerOSPack(
        filesystem_root=filesystem_root, state_database=state_database,
        allowed_services=allowed_services, allow_posix_chmod=allow_posix_chmod,
        allow_posix_chown=allow_posix_chown, max_output_bytes=max_output_bytes)

    def add(name: str, description: str, props: dict[str, Any], required: list[str],
            capability: str, function: Any, timeout: int = 20) -> None:
        tools.append(FunctionTool(name, description, object_schema(props, required),
                                  capability, function, timeout=timeout, output_limit=max_output_bytes))

    tools: list[FunctionTool] = []
    text = {"type": "string", "minLength": 1, "maxLength": 1000}
    selector = {"type": "string", "minLength": 1, "maxLength": 180}
    add("computer_os.desktop_session_create", "Create a durable logical desktop session context.", {"name": {"type": "string", "minLength": 1, "maxLength": 120}, "initial_state": {"type": "object"}}, ["name"], "computer:session:create", pack.session_create)
    add("computer_os.desktop_session_update", "Update persistent JSON state for an open desktop session.", {"session_id": text, "state": {"type": "object"}}, ["session_id", "state"], "computer:session:write", pack.session_update)
    add("computer_os.desktop_session_get", "Read a persistent desktop session context.", {"session_id": text}, ["session_id"], "computer:session:read", pack.session_get)
    add("computer_os.desktop_session_list", "List persistent desktop sessions.", {"include_closed": {"type": "boolean"}}, [], "computer:session:read", pack.session_list)
    add("computer_os.desktop_session_close", "Close a logical desktop session without ending the OS logon session.", {"session_id": text}, ["session_id"], "computer:session:close", pack.session_close)
    add("computer_os.list_monitors", "Enumerate connected displays and geometry.", {}, [], "computer:display:read", pack.monitors)
    add("computer_os.list_windows", "List visible windows and geometry.", {}, [], "computer:window:read", pack.windows)
    add("computer_os.window_action", "Move, resize, maximize, minimize, restore, activate or close one uniquely selected window.", {"title_contains": selector, "action": {"type": "string", "enum": ["move", "resize", "maximize", "minimize", "restore", "activate", "close"]}, "x": {"type": "integer"}, "y": {"type": "integer"}, "width": {"type": "integer", "minimum": 100}, "height": {"type": "integer", "minimum": 100}}, ["title_contains", "action"], "computer:window:control", pack.window_action)
    add("computer_os.snap_window", "Snap one uniquely selected window to a half, quadrant or full monitor.", {"title_contains": selector, "monitor_index": {"type": "integer", "minimum": 0, "maximum": 15}, "position": {"type": "string", "enum": ["left", "right", "top", "bottom", "top_left", "top_right", "bottom_left", "bottom_right", "maximize"]}}, ["title_contains", "monitor_index", "position"], "computer:window:control", pack.snap_window)
    add("computer_os.arrange_windows", "Arrange up to 16 uniquely selected windows within one monitor.", {"monitor_index": {"type": "integer", "minimum": 0, "maximum": 15}, "placements": {"type": "array", "minItems": 1, "maxItems": 16, "items": {"type": "object", "properties": {"title_contains": selector, "x": {"type": "integer", "minimum": 0}, "y": {"type": "integer", "minimum": 0}, "width": {"type": "integer", "minimum": 100}, "height": {"type": "integer", "minimum": 100}}, "required": ["title_contains", "x", "y", "width", "height"], "additionalProperties": False}}, ["monitor_index", "placements"], "computer:window:control", pack.arrange_windows)
    add("computer_os.virtual_desktops", "List or switch Linux virtual desktops, or inspect/create/switch Windows virtual desktops where pyvda is installed.", {"action": {"type": "string", "enum": ["list", "current", "create", "switch"]}, "desktop_number": {"type": "integer", "minimum": 0}}, ["action"], "computer:desktop:control", pack.virtual_desktops)
    add("computer_os.keyboard_shortcut", "Send a bounded allowlisted keyboard shortcut.", {"keys": {"type": "array", "minItems": 1, "maxItems": 5, "items": {"type": "string"}}}, ["keys"], "computer:keyboard:shortcut", pack.keyboard_shortcut)
    add("computer_os.keyboard_sequence", "Execute a prevalidated bounded keyboard sequence of typing, keypresses, shortcuts and waits.", {"steps": {"type": "array", "minItems": 1, "maxItems": 30, "items": {"type": "object"}}}, ["steps"], "computer:keyboard:sequence", pack.keyboard_sequence, 45)
    add("computer_os.accessibility_inspect", "Inspect accessible UI elements through Windows UI Automation or Linux AT-SPI.", {"title_contains": selector, "max_elements": {"type": "integer", "minimum": 1, "maximum": 300}}, ["title_contains"], "computer:accessibility:read", pack.accessibility_inspect)
    add("computer_os.accessibility_click", "Invoke one visible enabled Windows UI Automation element by exact automation ID.", {"title_contains": selector, "automation_id": text}, ["title_contains", "automation_id"], "computer:accessibility:control", pack.accessibility_click)
    add("computer_os.list_services", "List services using Windows SCM, systemd or launchd.", {}, [], "system:services:read", pack.services, 35)
    add("computer_os.service_action", "Start, stop or restart an exact host-allowlisted Windows/Linux service.", {"service": {"type": "string", "minLength": 1, "maxLength": 128}, "action": {"type": "string", "enum": ["start", "stop", "restart"]}}, ["service", "action"], "system:services:write", pack.service_action, 40)
    add("computer_os.file_metadata", "Inspect file type, size, timestamps, ownership and permission mode within filesystem_root.", {"path": text}, ["path"], "filesystem:metadata:read", pack.file_metadata)
    add("computer_os.chmod", "Change POSIX permission bits for a non-symlink path within filesystem_root.", {"path": text, "mode": {"type": "integer", "minimum": 0, "maximum": 511}}, ["path", "mode"], "filesystem:permissions:write", pack.chmod)
    add("computer_os.chown", "Change POSIX ownership only when explicitly enabled by the host.", {"path": text, "uid": {"type": "integer", "minimum": -1}, "gid": {"type": "integer", "minimum": -1}}, ["path", "uid", "gid"], "filesystem:ownership:write", pack.chown)
    add("computer_os.hardware_info", "Inspect CPU, memory, disk, battery and available thermal sensors.", {}, [], "system:hardware:read", pack.hardware)
    add("computer_os.network_interfaces", "Inspect network interface state, addresses, MTU and link speed.", {}, [], "system:network:read", pack.network_interfaces)
    add("computer_os.usb_devices", "Enumerate connected USB devices using pyudev, pnputil or system_profiler.", {}, [], "system:devices:read", pack.usb_devices, 40)
    add("computer_os.read_recent_events", "Read a bounded snapshot of recent Windows Event Log, Linux journal or macOS unified log entries.", {"channel": {"type": "string", "maxLength": 32}, "limit": {"type": "integer", "minimum": 1, "maximum": 200}, "since_minutes": {"type": "integer", "minimum": 1, "maximum": 10080}}, [], "system:events:read", pack.recent_events, 40)
    add("computer_os.create_event_watch", "Persist a named event-log watch definition; the host polls it when scheduled.", {"channel": {"type": "string", "maxLength": 32}, "description": {"type": "string", "minLength": 1, "maxLength": 200}}, ["channel", "description"], "system:events:watch", pack.create_event_watch)
    add("computer_os.list_event_watches", "List persisted event watch definitions.", {}, [], "system:events:read", pack.list_event_watches)
    add("computer_os.delete_event_watch", "Delete an event watch definition.", {"watch_id": text}, ["watch_id"], "system:events:watch", pack.delete_event_watch)
    return tuple(tools)

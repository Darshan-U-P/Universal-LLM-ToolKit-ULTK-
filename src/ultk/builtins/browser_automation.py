"""Stateful browser sessions, interactions, workflows and persistent site monitors."""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any

from ultk.exceptions import ToolExecutionError
from ultk.builtins._common import FunctionTool, object_schema
from ultk.builtins.web import _validate_public_url


def _session_file(root: Path, session_id: str) -> Path:
    if not session_id or len(session_id) > 100:
        raise ToolExecutionError("Invalid browser session identifier.")
    digest = hashlib.sha256(session_id.encode()).hexdigest()
    return root / f"{digest}.json"


def _with_page(root: str, session_id: str, action):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ToolExecutionError("Install Playwright and Chromium to use browser automation.") from exc
    directory = Path(root).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    state = _session_file(directory, session_id)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=str(state) if state.exists() else None)
        page = context.pages[0] if context.pages else context.new_page()

        def guard(route):
            try:
                _validate_public_url(route.request.url)
                route.continue_()
            except Exception:  # noqa: BLE001 - block unsafe browser requests
                route.abort()

        page.route("**/*", guard)
        try:
            result = action(page)
            context.storage_state(path=str(state))
            return result
        finally:
            context.close()
            browser.close()


def _navigate(root: str, session_id: str, url: str) -> dict[str, Any]:
    _validate_public_url(url)
    def action(page):
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        _validate_public_url(page.url)
        return {"url": page.url, "title": page.title()}
    return _with_page(root, session_id, action)


def _interact(root: str, session_id: str, action: str, selector: str,
              value: str | None = None, key: str | None = None) -> dict[str, Any]:
    if not selector or len(selector) > 500:
        raise ToolExecutionError("A selector of at most 500 characters is required.")
    def run(page):
        locator = page.locator(selector).first
        if action == "click":
            locator.click(timeout=10000)
        elif action == "fill":
            if value is None or len(value) > 10000:
                raise ToolExecutionError("fill requires a value up to 10000 characters.")
            locator.fill(value, timeout=10000)
        elif action == "type":
            if value is None or len(value) > 2000:
                raise ToolExecutionError("type requires a value up to 2000 characters.")
            locator.press_sequentially(value, timeout=10000)
        elif action == "press":
            if key not in {"Enter", "Tab", "Escape", "ArrowUp", "ArrowDown", "ArrowLeft",
                           "ArrowRight", "Backspace", "Delete"}:
                raise ToolExecutionError("Browser key is not allowlisted.")
            locator.press(key, timeout=10000)
        elif action == "submit":
            locator.evaluate("(el) => { if (el.tagName !== 'FORM') throw new Error('not a form'); el.requestSubmit(); }")
        else:
            raise ToolExecutionError("Unsupported browser interaction.")
        return {"action": action, "selector": selector, "url": page.url}
    return _with_page(root, session_id, run)


def _snapshot(root: str, session_id: str) -> dict[str, Any]:
    return _with_page(root, session_id, lambda page: {
        "url": page.url, "title": page.title(),
        "text": page.locator("body").inner_text(timeout=5000)[:20000]})


def _workflow(root: str, session_id: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    if not 1 <= len(steps) <= 20:
        raise ToolExecutionError("Browser workflow must contain 1–20 steps.")
    def run(page):
        results = []
        for i, step in enumerate(steps):
            action = step.get("action")
            if action == "navigate":
                url = step.get("url", "")
                _validate_public_url(url)
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                _validate_public_url(page.url)
            elif action in {"click", "fill", "type", "press", "submit"}:
                selector = step.get("selector", "")
                if not selector or len(selector) > 500:
                    raise ToolExecutionError("Every interaction step needs a bounded selector.")
                locator = page.locator(selector).first
                if action == "click":
                    locator.click(timeout=10000)
                elif action == "fill":
                    locator.fill(step.get("value", "")[:10000], timeout=10000)
                elif action == "type":
                    locator.press_sequentially(step.get("value", "")[:2000], timeout=10000)
                elif action == "press":
                    key = step.get("key")
                    if key not in {"Enter", "Tab", "Escape", "ArrowUp", "ArrowDown",
                                   "ArrowLeft", "ArrowRight", "Backspace", "Delete"}:
                        raise ToolExecutionError("Workflow key is not allowlisted.")
                    locator.press(key, timeout=10000)
                else:
                    locator.evaluate("(el) => { if (el.tagName !== 'FORM') throw new Error('not a form'); el.requestSubmit(); }")
            elif action == "snapshot":
                results.append({"step": i, "title": page.title(),
                                "text": page.locator("body").inner_text()[:8000]})
                continue
            else:
                raise ToolExecutionError(f"Unsupported browser workflow action at step {i}.")
            results.append({"step": i, "action": action, "url": page.url})
        return {"steps_completed": len(results), "results": results}
    return _with_page(root, session_id, run)


class SiteMonitorStore:
    def __init__(self, path: str | Path, notifier=None):
        self.path = str(Path(path).expanduser().resolve())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.notifier = notifier
        with sqlite3.connect(self.path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS monitors(
                id TEXT PRIMARY KEY, url TEXT NOT NULL, last_hash TEXT, last_text TEXT,
                enabled INTEGER NOT NULL DEFAULT 1)""")

    def add(self, url: str) -> dict[str, Any]:
        _validate_public_url(url)
        import uuid
        monitor_id = uuid.uuid4().hex
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO monitors(id,url) VALUES (?,?)", (monitor_id,url))
        return {"monitor_id": monitor_id, "url": url}

    def list(self):
        with sqlite3.connect(self.path) as db:
            return [{"id": r[0], "url": r[1], "enabled": bool(r[2])}
                    for r in db.execute("SELECT id,url,enabled FROM monitors")]

    def check(self, monitor_id: str):
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT url,last_hash FROM monitors WHERE id=? AND enabled=1",
                             (monitor_id,)).fetchone()
        if not row:
            raise ToolExecutionError("Monitor does not exist or is disabled.")
        from ultk.builtins.web import _extract
        page = _extract(row[0])
        text = page["title"] + "\n" + page["text"]
        digest = hashlib.sha256(text.encode()).hexdigest()
        changed = row[1] is not None and row[1] != digest
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE monitors SET last_hash=?,last_text=? WHERE id=?",
                       (digest,text[:20000],monitor_id))
        event = {"monitor_id": monitor_id, "url": row[0], "changed": changed,
                 "title": page["title"], "text": text[:5000]}
        if changed and self.notifier:
            self.notifier(event)
        return event


def create_advanced_browser_tools(*, session_root: str | Path = "./browser_sessions",
                                  monitor_database: str | Path = "./site_monitors.sqlite3",
                                  notifier=None) -> tuple[FunctionTool, ...]:
    root = str(Path(session_root).expanduser().resolve())
    store = SiteMonitorStore(monitor_database, notifier)
    return (
        FunctionTool("browser.navigate", "Navigate a named persistent browser session to a public URL.",
                     object_schema({"session_id": {"type": "string", "minLength": 1, "maxLength": 100},
                                    "url": {"type": "string", "format": "uri"}}, ["session_id","url"]),
                     "browser:navigate", lambda session_id,url: _navigate(root,session_id,url), timeout=30),
        FunctionTool("browser.interact", "Click, fill, type, press or submit a form in a named browser session.",
                     object_schema({"session_id": {"type": "string", "minLength": 1, "maxLength": 100},
                                    "action": {"type": "string", "enum": ["click","fill","type","press","submit"]},
                                    "selector": {"type": "string", "minLength": 1, "maxLength": 500},
                                    "value": {"type": "string", "maxLength": 10000},
                                    "key": {"type": "string"}}, ["session_id","action","selector"]),
                     "browser:interact", lambda session_id,action,selector,value=None,key=None:
                     _interact(root,session_id,action,selector,value,key), timeout=30),
        FunctionTool("browser.snapshot", "Read visible text and title from a persistent browser session.",
                     object_schema({"session_id": {"type": "string", "minLength": 1, "maxLength": 100}},
                                   ["session_id"]),
                     "browser:read", lambda session_id: _snapshot(root,session_id), timeout=20),
        FunctionTool("browser.workflow", "Run a bounded multi-page browser workflow with persistent session state.",
                     object_schema({"session_id": {"type": "string", "minLength": 1, "maxLength": 100},
                                    "steps": {"type": "array", "minItems": 1, "maxItems": 20,
                                              "items": {"type": "object"}}}, ["session_id","steps"]),
                     "browser:workflow", lambda session_id,steps: _workflow(root,session_id,steps), timeout=90),
        FunctionTool("web.monitor_add", "Persist a public website content monitor.",
                     object_schema({"url": {"type": "string", "format": "uri"}}, ["url"]),
                     "web:monitor:write", store.add),
        FunctionTool("web.monitor_list", "List persisted website monitors.",
                     object_schema({}), "web:monitor:read", store.list),
        FunctionTool("web.monitor_check", "Check a website monitor and report content changes; invokes configured notifier on change.",
                     object_schema({"monitor_id": {"type": "string", "minLength": 1, "maxLength": 64}},
                                   ["monitor_id"]),
                     "web:monitor:check", store.check, timeout=30),
    )

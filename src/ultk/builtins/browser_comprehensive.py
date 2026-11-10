"""Expanded browser control plane: profiles, tabs, frames, network, scraping and guarded submissions."""
from __future__ import annotations
import hashlib
import json
import os
import re
import shutil
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from ultk.builtins._common import FunctionTool, object_schema
from ultk.builtins.web import _validate_public_url
from ultk.exceptions import ToolExecutionError

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_MAX_TABS = 12
_MAX_EVENTS = 200

def _name(value: str) -> str:
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise ToolExecutionError("Profile/session names must be 1–64 safe ASCII characters.")
    return value

def _url(value: str) -> str:
    if not isinstance(value, str) or len(value) > 4096:
        raise ToolExecutionError("URL must be a string of at most 4096 characters.")
    _validate_public_url(value)
    return value

def _form_snapshot(page, selector: str) -> dict[str, Any]:
    raw = page.locator(selector).first.evaluate("""el => {
      if(el.tagName!=='FORM') throw new Error('not a form');
      return {action:el.action,method:(el.method||'get').toUpperCase(),
        fields:Array.from(el.elements).filter(x=>x.name).slice(0,100).map(x=>({
          name:x.name,type:x.type||x.tagName.toLowerCase(),required:!!x.required,
          value:String(x.value||''),checked:!!x.checked,
          selected_values:x.tagName==='SELECT' ? Array.from(x.selectedOptions).map(o=>o.value) : []
        }))};
    }""")
    for field in raw["fields"]:
        full_value = field.get("value", "")
        field["value_sha256"] = hashlib.sha256(full_value.encode("utf-8")).hexdigest()
        if field["type"] in {"password", "hidden", "file"}:
            field["value"] = "[redacted]"
        else:
            field["value"] = full_value[:120]
            field["value_truncated"] = len(full_value) > 120
        selected = field.get("selected_values", [])
        field["selected_values"] = [str(x)[:100] for x in selected]
    return raw


class BrowserControlPlane:
    def __init__(
        self,
        root: str | Path,
        *,
        headless: bool = True,
        max_profiles: int = 20,
        max_tabs: int = _MAX_TABS,
        extension_dirs: tuple[str | Path, ...] = (),
        notifier=None,
        download_root: str | Path | None = None,
        max_download_bytes: int = 25_000_000,
    ) -> None:
        if not 1 <= max_profiles <= 100 or not 1 <= max_tabs <= _MAX_TABS:
            raise ValueError("max_profiles must be 1-100 and max_tabs must be 1-12.")
        if not 1 <= max_download_bytes <= 100_000_000:
            raise ValueError("max_download_bytes must be between 1 byte and 100 MB.")
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.download_root = Path(download_root or (self.root / "downloads")).expanduser().resolve()
        self.download_root.mkdir(parents=True, exist_ok=True)
        self.max_download_bytes = max_download_bytes
        self.headless, self.max_profiles, self.max_tabs = bool(headless), max_profiles, max_tabs
        self.extension_dirs = tuple(Path(x).expanduser().resolve() for x in extension_dirs)
        self.notifier = notifier
        self._profile_locks: dict[str, threading.Lock] = {}
        self._profile_locks_guard = threading.Lock()
        for extension in self.extension_dirs:
            if not extension.is_dir() or not (extension / "manifest.json").is_file():
                raise ValueError(f"Trusted browser extension directory is invalid: {extension}")
        self.db_path = self.root / "browser_profiles.sqlite3"
        with sqlite3.connect(self.db_path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS profiles(
                name TEXT PRIMARY KEY, created REAL NOT NULL, last_used REAL NOT NULL,
                tabs TEXT NOT NULL DEFAULT '[]', active_tab INTEGER NOT NULL DEFAULT 0)""")
            db.execute("""CREATE TABLE IF NOT EXISTS site_changes(
                monitor_id TEXT PRIMARY KEY, url TEXT NOT NULL, selector TEXT,
                last_hash TEXT, enabled INTEGER NOT NULL DEFAULT 1)""")

    def _profile_path(self, profile: str) -> Path:
        return self.root / (hashlib.sha256(_name(profile).encode()).hexdigest() + ".chromium")

    def _manifest(self, profile: str):
        with sqlite3.connect(self.db_path) as db:
            row = db.execute("SELECT tabs,active_tab FROM profiles WHERE name=?", (profile,)).fetchone()
        if row is None:
            raise ToolExecutionError("Browser profile does not exist.")
        try:
            tabs = json.loads(row[0])
        except (ValueError, TypeError):
            tabs = []
        return [str(x) for x in tabs if isinstance(x, str)][:self.max_tabs], int(row[1])

    def create_profile(self, name: str, clone_from: str | None = None):
        name = _name(name)
        source = None
        if clone_from is not None:
            source_name = _name(clone_from)
            if source_name == name:
                raise ToolExecutionError("A profile cannot clone itself.")
            with sqlite3.connect(self.db_path) as db:
                source_exists = db.execute("SELECT 1 FROM profiles WHERE name=?", (source_name,)).fetchone()
            if not source_exists:
                raise ToolExecutionError("Source browser profile does not exist.")
            source = self._profile_path(source_name)
        target = self._profile_path(name)
        if target.exists():
            raise ToolExecutionError("Browser profile data directory already exists; refusing to reuse stale state.")
        with sqlite3.connect(self.db_path) as db:
            if db.execute("SELECT COUNT(*) FROM profiles").fetchone()[0] >= self.max_profiles:
                raise ToolExecutionError("Browser profile limit reached.")
            if db.execute("SELECT 1 FROM profiles WHERE name=?", (name,)).fetchone():
                raise ToolExecutionError("Browser profile already exists.")
            now = time.time()
            db.execute("INSERT INTO profiles(name,created,last_used,tabs,active_tab) VALUES (?,?,?,?,0)",
                       (name, now, now, "[]"))
        try:
            if source is not None:
                with self._profile_lock(source_name):
                    if not source.is_dir():
                        raise ToolExecutionError("Source browser profile data is missing.")
                    shutil.copytree(source, target, dirs_exist_ok=True)
        except Exception:
            with sqlite3.connect(self.db_path) as db:
                db.execute("DELETE FROM profiles WHERE name=?", (name,))
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            raise
        return {"profile": name, "created": True, "cloned": clone_from is not None}

    def list_profiles(self):
        with sqlite3.connect(self.db_path) as db:
            rows = db.execute("SELECT name,created,last_used FROM profiles ORDER BY name").fetchall()
        return {"profiles": [{"name": r[0], "created_at": r[1], "last_used": r[2]} for r in rows]}

    def delete_profile(self, name: str):
        name = _name(name)
        with self._profile_lock(name):
            with sqlite3.connect(self.db_path) as db:
                cur = db.execute("DELETE FROM profiles WHERE name=?", (name,))
            path = self._profile_path(name)
            if path.exists():
                shutil.rmtree(path)
            return {"profile": name, "deleted": cur.rowcount == 1}

    @staticmethod
    def _guard_context(context):
        def guard(route):
            try:
                _url(route.request.url)
                route.continue_()
            except Exception:
                route.abort()
        context.route("**/*", guard)

    @staticmethod
    def _guard(page):
        # Standalone monitor pages do not share a BrowserContext created by _with_context.
        def guard(route):
            try:
                _url(route.request.url)
                route.continue_()
            except Exception:
                route.abort()
        page.route("**/*", guard)

    def _profile_lock(self, profile: str) -> threading.Lock:
        with self._profile_locks_guard:
            return self._profile_locks.setdefault(profile, threading.Lock())

    def _with_context(self, profile: str, action):
        profile = _name(profile)
        with self._profile_lock(profile):
            return self._with_context_locked(profile, action)

    def _with_context_locked(self, profile: str, action):
        profile = _name(profile)
        with sqlite3.connect(self.db_path) as db:
            if not db.execute("SELECT 1 FROM profiles WHERE name=?", (profile,)).fetchone():
                raise ToolExecutionError("Browser profile does not exist; create it first.")
            db.execute("UPDATE profiles SET last_used=? WHERE name=?", (time.time(), profile))
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise ToolExecutionError("Install the browser extra and Chromium browser binaries.") from exc
        user_data_dir = self._profile_path(profile)
        user_data_dir.mkdir(parents=True, exist_ok=True)
        tabs, active = self._manifest(profile)
        with sync_playwright() as p:
            launch_args = []
            if self.extension_dirs:
                if self.headless:
                    raise ToolExecutionError("Chromium extensions require headed mode.")
                paths = [str(x) for x in self.extension_dirs]
                launch_args = ["--disable-extensions-except=" + ",".join(paths),
                               "--load-extension=" + ",".join(paths)]
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir), headless=self.headless, args=launch_args,
                service_workers="block", accept_downloads=True)
            self._guard_context(context)
            try:
                initial_pages = list(context.pages)
                pages = []
                for saved_url in tabs:
                    try:
                        page = context.new_page()
                        page.goto(_url(saved_url), wait_until="domcontentloaded", timeout=20000)
                        pages.append(page)
                    except Exception:
                        try:
                            page.close()
                        except Exception:
                            pass
                if pages:
                    for initial in initial_pages:
                        try:
                            initial.close()
                        except Exception:
                            pass
                else:
                    pages = initial_pages or [context.new_page()]
                active = min(max(active, 0), len(pages)-1)
                result = action(context, pages, active)
                persisted_pages = [p for p in context.pages if p.url.startswith(("http://","https://"))][:self.max_tabs]
                new_tabs = [p.url for p in persisted_pages]
                active_page = result.pop("_active_page", None) if isinstance(result, dict) else None
                active_index = persisted_pages.index(active_page) if active_page in persisted_pages else min(active, max(0,len(new_tabs)-1))
                with sqlite3.connect(self.db_path) as db:
                    db.execute("UPDATE profiles SET tabs=?,active_tab=? WHERE name=?",
                               (json.dumps(new_tabs), active_index, profile))
                return result
            finally:
                context.close()

    def navigate(self, profile: str, url: str, wait_until: str = "domcontentloaded"):
        url = _url(url)
        if wait_until not in {"domcontentloaded","load","networkidle","commit"}:
            raise ToolExecutionError("Unsupported navigation wait condition.")
        def run(ctx,pages,active):
            page = pages[active]
            page.goto(url, wait_until=wait_until, timeout=25000)
            _url(page.url)
            return {"url":page.url,"title":page.title(),"tab_index":active}
        return self._with_context(profile,run)

    def snapshot(self, profile: str):
        def run(ctx, pages, active):
            page = pages[active]
            return {"url": page.url, "title": page.title(),
                    "text": page.locator("body").inner_text(timeout=5000)[:20000]}
        return self._with_context(profile, run)

    def tabs(self, profile: str, operation: str, url: str | None = None, index: int | None = None):
        def run(ctx,pages,active):
            if operation=="list":
                return {"tabs":[{"index":i,"url":p.url,"title":p.title(),"is_active":i==active}
                                for i,p in enumerate(ctx.pages)]}
            if operation=="new":
                if len(ctx.pages) >= self.max_tabs:
                    raise ToolExecutionError("Browser tab limit reached.")
                if not url:
                    raise ToolExecutionError("Creating a persistent tab requires a public URL.")
                page = ctx.new_page()
                self._guard(page)
                page.goto(_url(url),wait_until="domcontentloaded",timeout=25000)
                return {"created":True,"tab_index":len(ctx.pages)-1,"url":page.url,"_active_page":page}
            if index is None or not 0 <= index < len(ctx.pages):
                raise ToolExecutionError("A valid tab index is required.")
            page=ctx.pages[index]
            if operation == "select":
                return {"selected": index, "url": page.url, "_active_page": page}
            if operation=="close":
                if len(ctx.pages)==1:
                    raise ToolExecutionError("Cannot close the only browser tab.")
                page.close()
                next_active = active - 1 if index < active else active
                if index == active:
                    next_active = min(index, len(ctx.pages) - 1)
                next_active = max(0, min(next_active, len(ctx.pages) - 1))
                return {"closed": index, "_active_page": ctx.pages[next_active]}
            raise ToolExecutionError("Unknown tab operation.")
        return self._with_context(profile,run)

    def popup(self, profile: str, selector: str, timeout_ms: int = 5000):
        if not selector or len(selector) > 500 or not 500 <= timeout_ms <= 15000:
            raise ToolExecutionError("Popup selector or timeout is invalid.")
        def run(ctx,pages,active):
            try:
                with ctx.expect_page(timeout=timeout_ms) as info:
                    pages[active].locator(selector).first.click(timeout=timeout_ms)
                page = info.value
                page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
                _url(page.url)
                self._guard(page)
                return {"opened":True,"url":page.url,"title":page.title(),"tab_index":ctx.pages.index(page),"_active_page":page}
            except Exception as exc:
                raise ToolExecutionError(f"Popup was not captured ({type(exc).__name__}).") from exc
        return self._with_context(profile,run)

    def frame(self, profile: str, frame_selector: str, action: str, selector: str="body", value: str|None=None):
        if not frame_selector or len(frame_selector) > 500 or not selector or len(selector) > 500:
            raise ToolExecutionError("Frame and element selectors must be bounded.")
        def run(ctx,pages,active):
            loc=pages[active].frame_locator(frame_selector).locator(selector).first
            if action == "read":
                return {"text": loc.inner_text(timeout=10000)[:10000], "url": pages[active].url}
            if action == "click":
                loc.click(timeout=10000)
            elif action=="fill":
                if value is None or len(value) > 5000:
                    raise ToolExecutionError("Frame fill requires a value up to 5000 characters.")
                loc.fill(value,timeout=10000)
            else: raise ToolExecutionError("Frame action must be read, click or fill.")
            return {"action":action,"url":pages[active].url}
        return self._with_context(profile,run)

    def cookies(self, profile: str, operation: str, name: str|None=None):
        def run(ctx,pages,active):
            if operation=="list":
                cs=ctx.cookies()
                return {"cookies":[{"name":c["name"],"domain":c["domain"],"path":c["path"],
                    "expires":c.get("expires"),"httpOnly":c.get("httpOnly"),"secure":c.get("secure"),
                    "sameSite":c.get("sameSite")} for c in cs],"count":len(cs)}
            if operation=="clear":
                if name:
                    ctx.clear_cookies(name=name)
                else:
                    ctx.clear_cookies()
                return {"cleared":True,"name":name}
            raise ToolExecutionError("Cookie operation must be list or clear.")
        return self._with_context(profile,run)

    def scrape(self, profile: str, selector: str, attributes: list[str]|None=None, limit: int=50):
        if not selector or len(selector) > 500 or not 1 <= limit <= 200:
            raise ToolExecutionError("Scrape selector or result limit is invalid.")
        attrs=attributes or ["href"]
        if len(attrs)>8 or any(not re.fullmatch(r"[A-Za-z_:][-A-Za-z0-9_:.]{0,63}",a) for a in attrs):
            raise ToolExecutionError("Invalid attribute list.")
        def run(ctx, pages, active):
            locator = pages[active].locator(selector)
            count = min(locator.count(), limit)
            records = []
            for index in range(count):
                item = locator.nth(index)
                record = {"text": item.inner_text(timeout=5000)[:2000]}
                for attribute in attrs:
                    record[attribute] = item.get_attribute(attribute, timeout=5000)
                records.append(record)
            return {
                "url": pages[active].url,
                "selector": selector,
                "count": len(records),
                "records": records,
                "truncated": locator.count() > limit,
            }
        return self._with_context(profile,run)

    def network(self, profile: str, url: str | None = None, capture_ms: int = 1000):
        if url:
            url = _url(url)
        if type(capture_ms) is not int or not 100 <= capture_ms <= 10000:
            raise ToolExecutionError("Network capture window must be between 100 and 10000 ms.")

        def run(ctx, pages, active):
            page = pages[active]
            events: dict[str, list[dict[str, Any]]] = {
                "requests": [], "responses": [], "failures": [], "websockets": [],
            }
            counts = {key: 0 for key in events}

            def record(kind: str, event: dict[str, Any]) -> None:
                counts[kind] += 1
                if len(events[kind]) < _MAX_EVENTS:
                    events[kind].append(event)

            page.on("request", lambda request: record("requests", {
                "method": request.method, "url": request.url[:2000],
                "resource_type": request.resource_type,
            }))
            page.on("response", lambda response: record("responses", {
                "status": response.status, "url": response.url[:2000],
                "method": response.request.method,
            }))
            page.on("requestfailed", lambda request: record("failures", {
                "url": request.url[:2000], "error": (request.failure or "")[:300],
            }))
            page.on("websocket", lambda socket: record("websockets", {
                "url": socket.url[:2000],
            }))
            if url:
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(capture_ms)
            return {
                "url": page.url,
                **events,
                "event_counts": counts,
                "capture_ms": capture_ms,
                "truncated": any(count > _MAX_EVENTS for count in counts.values()),
                "websocket_frames_captured": False,
            }

        return self._with_context(profile, run)

    def challenge(self, profile: str):
        def run(ctx,pages,active):
            page = pages[active]
            title = page.title()
            body = page.locator("body").inner_text(timeout=5000)[:12000].casefold()
            indicators=[x for x in ("captcha","verify you are human","are you a robot","cloudflare","checking your browser","security challenge") if x in (title+" "+body).casefold()]
            frames=[f.url[:1000] for f in page.frames if any(x in f.url.casefold() for x in ("captcha","recaptcha","hcaptcha","challenges.cloudflare"))]
            return {"challenge_detected":bool(indicators or frames),"indicators":indicators,
                    "challenge_frames":frames,"requires_human":bool(indicators or frames),
                    "note":"ULTK detects challenges but does not solve or bypass CAPTCHA."}
        return self._with_context(profile,run)

    def auth_handoff(self, profile: str, login_url: str, login_selector: str,
                     timeout_seconds: int = 120):
        if self.headless:
            raise ToolExecutionError("Human authentication handoff requires headless=False.")
        if not login_selector or len(login_selector) > 300 or not 10 <= timeout_seconds <= 600:
            raise ToolExecutionError("Login selector or handoff timeout is invalid.")
        login_url = _url(login_url)
        def run(ctx, pages, active):
            page = pages[active]
            page.goto(login_url, wait_until="domcontentloaded", timeout=25000)
            locator = page.locator(login_selector).first
            try:
                visible = locator.is_visible(timeout=3000)
            except Exception:
                visible = False
            if not visible:
                return {"handoff_started": True, "completed": False,
                        "reason": "login_selector_not_visible",
                        "url": page.url,
                        "note": "No authentication success was inferred; verify the account state explicitly."}
            try:
                locator.wait_for(state="hidden", timeout=timeout_seconds * 1000)
            except Exception:
                return {"handoff_started": True, "completed": False,
                        "reason": "human_action_timeout", "url": page.url}
            return {"handoff_started": True, "completed": True, "url": page.url,
                    "note": "Login indicator disappeared; this is a heuristic, not identity proof."}
        return self._with_context(profile, run)

    def auth_status(self, profile: str, selectors: list[str]):
        if not 1 <= len(selectors) <= 10 or any(not isinstance(s, str) or not s or len(s) > 300 for s in selectors):
            raise ToolExecutionError("Provide 1-10 non-empty authentication selectors of at most 300 characters.")
        def run(ctx,pages,active):
            page = pages[active]
            found = []
            for selector in selectors:
                try:
                    if page.locator(selector).count():
                        found.append(selector)
                except Exception:
                    pass
            return {"url":page.url,"title":page.title(),"authenticated_heuristic":not bool(found),
                    "login_indicators_found":found,"warning":"Selector heuristic only; not authoritative identity verification."}
        return self._with_context(profile,run)

    def form_preview(self, profile: str, selector: str):
        if not selector or len(selector) > 500:
            raise ToolExecutionError("A bounded form selector is required.")
        def run(ctx,pages,active):
            snapshot = _form_snapshot(pages[active], selector)
            fingerprint = hashlib.sha256(json.dumps(snapshot,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
            return {**snapshot, "form_sha256": fingerprint}
        return self._with_context(profile,run)

    def submit_form(self, profile: str, selector: str, expected_form_sha256: str):
        if not selector or len(selector)>500 or not re.fullmatch(r"[A-Fa-f0-9]{64}", expected_form_sha256):
            raise ToolExecutionError("A bounded form selector and SHA-256 preview fingerprint are required.")
        def run(ctx,pages,active):
            page = pages[active]
            form = page.locator(selector).first
            snapshot = _form_snapshot(page, selector)
            if snapshot["method"] not in {"GET", "POST"}:
                raise ToolExecutionError("Only GET and POST form submissions are supported.")
            snapshot["action"] = page.evaluate(
                "(action) => new URL(action, location.href).href", snapshot["action"]
            )
            fingerprint = hashlib.sha256(
                json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
            ).hexdigest()
            if fingerprint.casefold()!=expected_form_sha256.casefold():
                raise ToolExecutionError("Form changed after preview; obtain a fresh preview and approval.")
            _url(snapshot["action"])
            form.evaluate("""el => {
              if (typeof el.requestSubmit !== "function") {
                throw new Error("requestSubmit is not supported");
              }
              el.requestSubmit();
            }""")
            page.wait_for_load_state("domcontentloaded",timeout=15000)
            return {"submitted":True,"url":page.url,"destination":snapshot["action"],"method":snapshot["method"],
                    "form_sha256":fingerprint}
        return self._with_context(profile,run)

    def download(
        self,
        profile: str,
        selector: str,
        filename: str | None = None,
        timeout_ms: int = 15000,
    ) -> dict[str, Any]:
        if not selector or len(selector) > 500 or not 500 <= timeout_ms <= 30000:
            raise ToolExecutionError("Download selector or timeout is invalid.")
        if filename is not None and (
            not isinstance(filename, str)
            or not filename
            or len(filename) > 180
            or filename in {".", ".."}
            or Path(filename).name != filename
            or "/" in filename
            or "\\" in filename
            or any(ord(char) < 32 for char in filename)
        ):
            raise ToolExecutionError("Download filename must be a simple file name.")

        def run(ctx, pages, active):
            page = pages[active]
            try:
                with page.expect_download(timeout=timeout_ms) as download_info:
                    page.locator(selector).first.click(timeout=min(timeout_ms, 10000))
                download = download_info.value
                suggested = download.suggested_filename or f"download-{uuid.uuid4().hex}"
                safe_suggested = re.sub(r"[^A-Za-z0-9._ -]", "_", Path(suggested.replace("\\", "/")).name)
                safe_suggested = safe_suggested.strip(" .")[:180] or f"download-{uuid.uuid4().hex}"
                final_name = filename or safe_suggested
                target = (self.download_root / final_name).resolve()
                if not target.is_relative_to(self.download_root) or target.exists():
                    raise ToolExecutionError("Download destination already exists or escapes the configured root.")
                temporary = self.download_root / f".{uuid.uuid4().hex}.part"
                try:
                    download.save_as(str(temporary))
                    size = temporary.stat().st_size
                    if size > self.max_download_bytes:
                        raise ToolExecutionError(
                            f"Download exceeded the configured {self.max_download_bytes}-byte limit."
                        )
                    digest = hashlib.sha256()
                    with temporary.open("rb") as handle:
                        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                            digest.update(chunk)
                    os.link(temporary, target)
                    temporary.unlink()
                finally:
                    if temporary.exists():
                        temporary.unlink()
                return {
                    "url": page.url,
                    "path": str(target),
                    "filename": final_name,
                    "bytes_written": size,
                    "sha256": digest.hexdigest(),
                    "status": "saved",
                }
            except ToolExecutionError:
                raise
            except Exception as exc:
                raise ToolExecutionError(f"Browser download failed ({type(exc).__name__}).") from exc

        return self._with_context(profile, run)

    def monitor_add(self,url:str,selector:str|None=None):
        _url(url)
        if selector is not None and (not selector or len(selector) > 500):
            raise ToolExecutionError("Monitor selector is invalid.")
        mid=uuid.uuid4().hex
        with sqlite3.connect(self.db_path) as db:
            db.execute(
                "INSERT INTO site_changes(monitor_id,url,selector) VALUES (?,?,?)",
                (mid, url, selector),
            )
        return {"monitor_id":mid,"url":url,"selector":selector}

    def monitor_check(self,monitor_id:str):
        if not isinstance(monitor_id, str) or len(monitor_id) != 32:
            raise ToolExecutionError("Invalid monitor identifier.")
        with sqlite3.connect(self.db_path) as db:
            row=db.execute("SELECT url,selector,last_hash FROM site_changes WHERE monitor_id=? AND enabled=1",(monitor_id,)).fetchone()
        if row is None:
            raise ToolExecutionError("Website monitor not found or disabled.")
        result = self._fetch_monitor(row[0], row[1])
        digest = hashlib.sha256((result["title"] + "\\n" + result["text"]).encode()).hexdigest()
        changed = row[2] is not None and row[2] != digest
        event = {
            "monitor_id": monitor_id,
            "url": row[0],
            "changed": changed,
            "title": result["title"],
            "text_excerpt": result["text"][:3000],
        }
        if changed and self.notifier is not None:
            try:
                self.notifier(event)
            except Exception as exc:
                raise ToolExecutionError(
                    "Website changed but the configured notifier failed; monitor checkpoint was not advanced."
                ) from exc
        with sqlite3.connect(self.db_path) as db:
            db.execute("UPDATE site_changes SET last_hash=? WHERE monitor_id=?", (digest, monitor_id))
        return event

    def monitor_list(self):
        with sqlite3.connect(self.db_path) as db:
            rows = db.execute(
                "SELECT monitor_id,url,selector,last_hash,enabled FROM site_changes ORDER BY monitor_id LIMIT 500"
            ).fetchall()
        return {
            "monitors": [
                {"monitor_id": row[0], "url": row[1], "selector": row[2],
                 "initialized": row[3] is not None, "enabled": bool(row[4])}
                for row in rows
            ],
            "count": len(rows),
        }

    def monitor_delete(self, monitor_id: str):
        if not isinstance(monitor_id, str) or not re.fullmatch(r"[A-Fa-f0-9]{32}", monitor_id):
            raise ToolExecutionError("Invalid monitor identifier.")
        with sqlite3.connect(self.db_path) as db:
            cursor = db.execute("DELETE FROM site_changes WHERE monitor_id=?", (monitor_id,))
        if cursor.rowcount != 1:
            raise ToolExecutionError("Website monitor was not found.")
        return {"monitor_id": monitor_id, "deleted": True}

    def websocket_probe(self, profile: str, ws_url: str, message: str, timeout_ms: int = 5000):
        parsed = __import__("urllib.parse", fromlist=["urlparse"]).urlparse(ws_url)
        if parsed.scheme not in {"ws", "wss"} or not parsed.hostname or len(ws_url) > 2048:
            raise ToolExecutionError("Only public ws:// or wss:// URLs are accepted.")
        _url(("https://" if parsed.scheme == "wss" else "http://") + parsed.netloc + "/")
        if not isinstance(message, str) or len(message) > 4000 or not 500 <= timeout_ms <= 10000:
            raise ToolExecutionError("WebSocket message or timeout is outside configured bounds.")
        def run(ctx, pages, active):
            return pages[active].evaluate("""async ({url,message,timeout}) => {
              return await new Promise(resolve => {
                const ws = new WebSocket(url); let settled=false;
                const finish = value => { if (!settled) { settled=true; try{ws.close();}catch{} resolve(value); } };
                const timer = setTimeout(() => finish({error:'timeout'}), timeout);
                ws.onopen = () => ws.send(message);
                ws.onmessage = event => { clearTimeout(timer); finish({received:String(event.data).slice(0,4000)}); };
                ws.onerror = () => { clearTimeout(timer); finish({error:'websocket_error'}); };
              });
            }""", {"url":ws_url,"message":message,"timeout":timeout_ms})
        return self._with_context(profile, run)

    def run_test(self, profile: str, steps: list[dict[str, Any]]):
        if not 1 <= len(steps) <= 30:
            raise ToolExecutionError("Browser test must contain 1–30 steps.")
        if any(not isinstance(step, dict) for step in steps):
            raise ToolExecutionError("Every browser test step must be an object.")
        def run(ctx, pages, active):
            page = pages[active]
            results = []
            for index, step in enumerate(steps):
                action = step.get("action")
                try:
                    if action == "navigate":
                        page.goto(_url(step.get("url","")), wait_until="domcontentloaded", timeout=20000)
                    elif action in {"click","fill"}:
                        selector = step.get("selector","")
                        if not selector or len(selector) > 500:
                            raise ToolExecutionError("Invalid test selector.")
                        loc = page.locator(selector).first
                        if action == "click":
                            loc.click(timeout=10000)
                        else:
                            value = step.get("value","")
                            if not isinstance(value, str) or len(value) > 5000:
                                raise ToolExecutionError("Invalid test value.")
                            loc.fill(value,timeout=10000)
                    elif action == "expect_text":
                        text = step.get("text","")
                        if not isinstance(text, str) or not text or len(text) > 1000:
                            raise ToolExecutionError("Invalid expected text.")
                        if text not in page.locator("body").inner_text(timeout=5000):
                            raise ToolExecutionError("Expected text was not present.")
                    elif action == "expect_visible":
                        selector = step.get("selector","")
                        if not selector or len(selector) > 500:
                            raise ToolExecutionError("Invalid visibility selector.")
                        if not page.locator(selector).first.is_visible(timeout=5000):
                            raise ToolExecutionError("Expected element was not visible.")
                    elif action == "expect_url":
                        expected = step.get("contains","")
                        if not isinstance(expected,str) or len(expected)>500 or expected not in page.url:
                            raise ToolExecutionError("Current URL did not contain the expected value.")
                    else:
                        raise ToolExecutionError("Unsupported browser test action.")
                    results.append({"step":index,"action":action,"passed":True,"url":page.url})
                except Exception as exc:
                    results.append({"step":index,"action":action,"passed":False,
                                    "error":str(exc)[:500],"url":page.url})
                    break
            return {"passed":all(x["passed"] for x in results),
                    "steps_completed":len(results),"results":results}
        return self._with_context(profile,run)

    def workflow(self, profile: str, steps: list[dict[str, Any]]):
        if not isinstance(steps, list) or not 1 <= len(steps) <= 30:
            raise ToolExecutionError("Browser profile workflow must contain 1-30 steps.")
        allowed_keys = {
            "Enter", "Tab", "Escape", "ArrowUp", "ArrowDown", "ArrowLeft",
            "ArrowRight", "Backspace", "Delete",
        }
        prepared: list[dict[str, Any]] = []
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                raise ToolExecutionError(f"Workflow step {index} must be an object.")
            action = step.get("action")
            item = {"action": action}
            if action in {"navigate", "new_tab"}:
                item["url"] = _url(step.get("url", ""))
            elif action in {"click", "expect_visible"}:
                selector = step.get("selector", "")
                if not isinstance(selector, str) or not selector or len(selector) > 500:
                    raise ToolExecutionError(f"Workflow step {index} needs a bounded selector.")
                item["selector"] = selector
            elif action in {"fill", "type"}:
                selector = step.get("selector", "")
                value = step.get("value")
                limit = 5000 if action == "fill" else 2000
                if not isinstance(selector, str) or not selector or len(selector) > 500:
                    raise ToolExecutionError(f"Workflow step {index} needs a bounded selector.")
                if not isinstance(value, str) or len(value) > limit:
                    raise ToolExecutionError(f"Workflow step {index} has an invalid text value.")
                item.update({"selector": selector, "value": value})
            elif action == "press":
                selector = step.get("selector", "")
                key = step.get("key")
                if not isinstance(selector, str) or not selector or len(selector) > 500 or key not in allowed_keys:
                    raise ToolExecutionError(f"Workflow step {index} has an invalid key target.")
                item.update({"selector": selector, "key": key})
            elif action in {"select_tab", "close_tab"}:
                tab_index = step.get("index")
                if type(tab_index) is not int or not 0 <= tab_index < self.max_tabs:
                    raise ToolExecutionError(f"Workflow step {index} has an invalid tab index.")
                item["index"] = tab_index
            elif action == "wait":
                milliseconds = step.get("milliseconds", 0)
                if type(milliseconds) is not int or not 100 <= milliseconds <= 5000:
                    raise ToolExecutionError(f"Workflow step {index} wait must be 100-5000 ms.")
                item["milliseconds"] = milliseconds
            elif action == "expect_text":
                expected = step.get("text")
                if not isinstance(expected, str) or not expected or len(expected) > 1000:
                    raise ToolExecutionError(f"Workflow step {index} has invalid expected text.")
                item["text"] = expected
            elif action == "expect_url":
                expected = step.get("contains")
                if not isinstance(expected, str) or not expected or len(expected) > 500:
                    raise ToolExecutionError(f"Workflow step {index} has an invalid URL assertion.")
                item["contains"] = expected
            elif action != "snapshot":
                raise ToolExecutionError(f"Workflow step {index} uses an unsupported action.")
            prepared.append(item)

        def run(ctx, pages, active):
            active_index = active
            results = []
            for index, step in enumerate(prepared):
                action = step["action"]
                if action == "new_tab":
                    if len(ctx.pages) >= self.max_tabs:
                        raise ToolExecutionError("Browser tab limit reached during workflow.")
                    page = ctx.new_page()
                    page.goto(step["url"], wait_until="domcontentloaded", timeout=25000)
                    _url(page.url)
                    active_index = ctx.pages.index(page)
                    result = {"url": page.url, "tab_index": active_index}
                elif action == "select_tab":
                    if step["index"] >= len(ctx.pages):
                        raise ToolExecutionError("Workflow selected a tab that does not exist.")
                    active_index = step["index"]
                    result = {"tab_index": active_index}
                elif action == "close_tab":
                    if len(ctx.pages) == 1:
                        raise ToolExecutionError("Cannot close the only browser tab.")
                    if step["index"] >= len(ctx.pages):
                        raise ToolExecutionError("Workflow closed a tab that does not exist.")
                    ctx.pages[step["index"]].close()
                    if step["index"] < active_index:
                        active_index -= 1
                    elif step["index"] == active_index:
                        active_index = min(step["index"], len(ctx.pages) - 1)
                    result = {"closed_tab": step["index"], "active_tab": active_index}
                else:
                    page = ctx.pages[active_index]
                    if action == "navigate":
                        page.goto(step["url"], wait_until="domcontentloaded", timeout=25000)
                        _url(page.url)
                        result = {"url": page.url}
                    elif action == "click":
                        page.locator(step["selector"]).first.click(timeout=10000)
                        result = {"url": page.url}
                    elif action == "fill":
                        page.locator(step["selector"]).first.fill(step["value"], timeout=10000)
                        result = {"url": page.url}
                    elif action == "type":
                        page.locator(step["selector"]).first.press_sequentially(step["value"], timeout=10000)
                        result = {"url": page.url}
                    elif action == "press":
                        page.locator(step["selector"]).first.press(step["key"], timeout=10000)
                        result = {"url": page.url}
                    elif action == "wait":
                        page.wait_for_timeout(step["milliseconds"])
                        result = {"waited_ms": step["milliseconds"]}
                    elif action == "snapshot":
                        result = {
                            "url": page.url,
                            "title": page.title(),
                            "text": page.locator("body").inner_text(timeout=5000)[:8000],
                        }
                    elif action == "expect_text":
                        body = page.locator("body").inner_text(timeout=5000)
                        if step["text"] not in body:
                            raise ToolExecutionError(f"Workflow step {index} expected text was not present.")
                        result = {"assertion": "text_present", "passed": True}
                    elif action == "expect_visible":
                        if not page.locator(step["selector"]).first.is_visible(timeout=5000):
                            raise ToolExecutionError(f"Workflow step {index} expected element was not visible.")
                        result = {"assertion": "visible", "passed": True}
                    else:
                        if step["contains"] not in page.url:
                            raise ToolExecutionError(f"Workflow step {index} URL assertion failed.")
                        result = {"assertion": "url_contains", "passed": True}
                results.append({"step": index, "action": action, **result})
            return {
                "steps_completed": len(results),
                "results": results,
                "_active_page": ctx.pages[active_index],
            }

        return self._with_context(profile, run)

    def list_extensions(self):
        return {"extensions":[{"name":path.name,"manifest_present":(path/"manifest.json").is_file()}
                              for path in self.extension_dirs],
                "note":"Only host-configured extension directories are loaded; model input cannot add extensions."}

    def _fetch_monitor(self,url,selector):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise ToolExecutionError("Install the browser extra and Chromium.") from exc
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            self._guard(page)
            try:
                page.goto(_url(url),wait_until="domcontentloaded",timeout=25000)
                loc=page.locator(selector) if selector else page.locator("body")
                return {"title":page.title(),"text":loc.inner_text(timeout=10000)[:20000]}
            finally: browser.close()


def create_comprehensive_browser_tools(
    *,
    profile_root: str | Path = "./browser_profiles",
    headless: bool = True,
    extension_dirs: tuple[str | Path, ...] = (),
    notifier=None,
    download_root: str | Path | None = None,
    max_download_bytes: int = 25_000_000,
):
    b = BrowserControlPlane(
        profile_root,
        headless=headless,
        extension_dirs=extension_dirs,
        notifier=notifier,
        download_root=download_root,
        max_download_bytes=max_download_bytes,
    )
    p={"type":"string","minLength":1,"maxLength":64}
    return (
      FunctionTool("browser.profile_create","Create a named persistent browser profile; optional clone copies saved cookies/storage state.",
        object_schema({"name":p,"clone_from":p},["name"]),"browser:profile:manage",b.create_profile),
      FunctionTool("browser.profile_list","List browser profiles and last-used timestamps.",object_schema({}),"browser:profile:read",b.list_profiles),
      FunctionTool("browser.extensions_list","List host-trusted browser extensions configured for this browser pack.",
        object_schema({}),"browser:extensions:read",b.list_extensions),
      FunctionTool("browser.profile_delete","Delete a profile and its saved authentication state.",object_schema({"name":p},["name"]),"browser:profile:manage",b.delete_profile),
      FunctionTool("browser.control_navigate","Navigate the active tab of a named profile to a public HTTP(S) URL.",
        object_schema({"profile":p,"url":{"type":"string","format":"uri"},
          "wait_until":{"type":"string","enum":["domcontentloaded","load","networkidle","commit"]}},
          ["profile","url"]),"browser:navigate",
        lambda profile,url,wait_until="domcontentloaded":b.navigate(profile,url,wait_until)),
      FunctionTool("browser.control_snapshot","Return the active tab URL, title and bounded visible text.",
        object_schema({"profile":p},["profile"]),"browser:read",b.snapshot),
      FunctionTool("browser.tabs","List, create, select or close tabs in a named profile.",
        object_schema({"profile":p,"operation":{"type":"string","enum":["list","new","select","close"]},
          "url":{"type":"string","format":"uri"},"index":{"type":"integer","minimum":0}},["profile","operation"]),
        "browser:tabs:manage",lambda profile,operation,url=None,index=None:b.tabs(profile,operation,url,index)),
      FunctionTool("browser.popup_capture","Click a selector and capture a popup/new tab.",
        object_schema({"profile":p,"selector":{"type":"string","minLength":1,"maxLength":500},
          "timeout_ms":{"type":"integer","minimum":500,"maximum":15000}},["profile","selector"]),
        "browser:popup:capture",lambda profile,selector,timeout_ms=5000:b.popup(profile,selector,timeout_ms),timeout=30),
      FunctionTool("browser.frame_interact","Read, click or fill an element inside a selected iframe.",
        object_schema({"profile":p,"frame_selector":{"type":"string","minLength":1,"maxLength":500},
          "action":{"type":"string","enum":["read","click","fill"]},"selector":{"type":"string","maxLength":500},
          "value":{"type":"string","maxLength":5000}},["profile","frame_selector","action"]),
        "browser:frame:interact",lambda profile,frame_selector,action,selector="body",value=None:b.frame(profile,frame_selector,action,selector,value)),
      FunctionTool("browser.cookies","List cookie metadata without values or clear all/one named cookie.",
        object_schema({"profile":p,"operation":{"type":"string","enum":["list","clear"]},"name":{"type":"string","maxLength":256}},["profile","operation"]),
        "browser:cookies:manage",lambda profile,operation,name=None:b.cookies(profile,operation,name)),
      FunctionTool("browser.scrape_structured","Extract bounded text and selected attributes from matching DOM elements.",
        object_schema({"profile":p,"selector":{"type":"string","minLength":1,"maxLength":500},
          "attributes":{"type":"array","items":{"type":"string","maxLength":64},"maxItems":8},
          "limit":{"type":"integer","minimum":1,"maximum":200}},["profile","selector"]),
        "browser:scrape",lambda profile,selector,attributes=None,limit=50:b.scrape(profile,selector,attributes,limit),timeout=40),
      FunctionTool("browser.download","Download a browser-triggered file to a host-configured directory with a post-download byte limit and SHA-256 digest.",
        object_schema({"profile":p,"selector":{"type":"string","minLength":1,"maxLength":500},
          "filename":{"type":"string","minLength":1,"maxLength":180},
          "timeout_ms":{"type":"integer","minimum":500,"maximum":30000}},["profile","selector"]),
        "browser:download",lambda profile,selector,filename=None,timeout_ms=15000:
          b.download(profile,selector,filename,timeout_ms),timeout=40),
      FunctionTool("browser.network_inspect","Capture bounded request, response, failure and WebSocket metadata during a navigation and observation window.",
        object_schema({"profile":p,"url":{"type":"string","format":"uri"},
          "capture_ms":{"type":"integer","minimum":100,"maximum":10000}},["profile"]),
        "browser:network:inspect",lambda profile,url=None,capture_ms=1000:b.network(profile,url,capture_ms),timeout=40),
      FunctionTool("browser.websocket_probe","Send one bounded text message to a public WebSocket and capture one bounded reply.",
        object_schema({"profile":p,"url":{"type":"string","minLength":1,"maxLength":2048},
          "message":{"type":"string","maxLength":4000},"timeout_ms":{"type":"integer","minimum":500,"maximum":10000}},
          ["profile","url","message"]),"browser:websocket:interact",
        lambda profile,url,message,timeout_ms=5000:b.websocket_probe(profile,url,message,timeout_ms),timeout=20),
      FunctionTool("browser.profile_workflow","Run a prevalidated bounded multi-tab workflow using navigation, interaction, waits and assertions.",
        object_schema({"profile":p,"steps":{"type":"array","minItems":1,"maxItems":30,"items":{"type":"object"}}},
          ["profile","steps"]),"browser:workflow",lambda profile,steps:b.workflow(profile,steps),timeout=90),
      FunctionTool("browser.test_run","Run a bounded browser application test with navigation, interaction and assertions.",
        object_schema({"profile":p,"steps":{"type":"array","minItems":1,"maxItems":30,"items":{"type":"object"}}},
          ["profile","steps"]),"browser:test:run",lambda profile,steps:b.run_test(profile,steps),timeout=90),
      FunctionTool("browser.challenge_detect","Detect CAPTCHA/anti-bot pages; does not solve or bypass challenges.",
        object_schema({"profile":p},["profile"]),"browser:challenge:inspect",b.challenge),
      FunctionTool("browser.auth_handoff","Open a visible browser for a human to complete login/MFA; waits for a host-supplied login indicator to disappear.",
        object_schema({"profile":p,"login_url":{"type":"string","format":"uri"},
          "login_selector":{"type":"string","minLength":1,"maxLength":300},
          "timeout_seconds":{"type":"integer","minimum":10,"maximum":600}},
          ["profile","login_url","login_selector"]),"browser:auth:handoff",
        lambda profile,login_url,login_selector,timeout_seconds=120:
          b.auth_handoff(profile,login_url,login_selector,timeout_seconds),timeout=620),
      FunctionTool("browser.auth_status","Use host-supplied login selectors as an authentication heuristic.",
        object_schema({"profile":p,"login_selectors":{"type":"array","items":{"type":"string","maxLength":300},"maxItems":10}},["profile","login_selectors"]),
        "browser:auth:inspect",lambda profile,login_selectors:b.auth_status(profile,login_selectors)),
      FunctionTool("browser.form_preview","Inspect form destination, method and field metadata; password values are redacted.",
        object_schema({"profile":p,"selector":{"type":"string","minLength":1,"maxLength":500}},["profile","selector"]),
        "browser:form:preview",lambda profile,selector:b.form_preview(profile,selector)),
      FunctionTool("browser.form_submit","Submit a website form only if its action, method and field snapshot match a prior preview; requires browser:submit:consequential approval.",
        object_schema({"profile":p,"selector":{"type":"string","minLength":1,"maxLength":500},
          "expected_form_sha256":{"type":"string","pattern":"^[A-Fa-f0-9]{64}$"}},
          ["profile","selector","expected_form_sha256"]),
        "browser:submit:consequential",
        lambda profile,selector,expected_form_sha256:b.submit_form(profile,selector,expected_form_sha256),timeout=40),
      FunctionTool("web.change_monitor_add","Create a persistent website change monitor scoped optionally to a CSS selector.",
        object_schema({"url":{"type":"string","format":"uri"},"selector":{"type":"string","maxLength":500}},["url"]),
        "web:monitor:write",b.monitor_add),
      FunctionTool("web.change_monitor_check","Check a website monitor for selected-content changes; notifier failure leaves the checkpoint unchanged for retry.",
        object_schema({"monitor_id":{"type":"string","minLength":32,"maxLength":32}},["monitor_id"]),
        "web:monitor:check",b.monitor_check,timeout=40),
      FunctionTool("web.change_monitor_list","List bounded website monitor definitions and initialization status.",
        object_schema({}),"web:monitor:read",b.monitor_list),
      FunctionTool("web.change_monitor_delete","Delete one website monitor definition.",
        object_schema({"monitor_id":{"type":"string","pattern":"^[A-Fa-f0-9]{32}$"}},["monitor_id"]),
        "web:monitor:write",b.monitor_delete),
    )

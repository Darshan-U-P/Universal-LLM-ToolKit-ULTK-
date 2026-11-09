"""Expanded browser control plane: profiles, tabs, frames, network, scraping and guarded submissions."""
from __future__ import annotations
import hashlib, json, re, sqlite3, time, uuid
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

class BrowserControlPlane:
    def __init__(self, root: str | Path, *, headless: bool = True,
                 max_profiles: int = 20, max_tabs: int = _MAX_TABS,
                 extension_dirs: tuple[str | Path, ...] = (), notifier=None) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.headless, self.max_profiles, self.max_tabs = bool(headless), max_profiles, max_tabs
        self.extension_dirs = tuple(Path(x).expanduser().resolve() for x in extension_dirs)
        self.notifier = notifier
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
        return self.root / (hashlib.sha256(_name(profile).encode()).hexdigest() + ".state.json")

    def _manifest(self, profile: str):
        with sqlite3.connect(self.db_path) as db:
            row = db.execute("SELECT tabs,active_tab FROM profiles WHERE name=?", (profile,)).fetchone()
        if row is None:
            raise ToolExecutionError("Browser profile does not exist.")
        try: tabs = json.loads(row[0])
        except (ValueError, TypeError): tabs = []
        return [str(x) for x in tabs if isinstance(x, str)][:self.max_tabs], int(row[1])

    def create_profile(self, name: str, clone_from: str | None = None):
        name = _name(name)
        with sqlite3.connect(self.db_path) as db:
            if db.execute("SELECT COUNT(*) FROM profiles").fetchone()[0] >= self.max_profiles:
                raise ToolExecutionError("Browser profile limit reached.")
            if db.execute("SELECT 1 FROM profiles WHERE name=?", (name,)).fetchone():
                raise ToolExecutionError("Browser profile already exists.")
            now = time.time()
            db.execute("INSERT INTO profiles(name,created,last_used,tabs,active_tab) VALUES (?,?,?,?,0)",
                       (name, now, now, "[]"))
        if clone_from:
            source = self._profile_path(_name(clone_from))
            if not source.is_file(): raise ToolExecutionError("Source profile has no saved browser state.")
            self._profile_path(name).write_bytes(source.read_bytes())
        return {"profile": name, "created": True}

    def list_profiles(self):
        with sqlite3.connect(self.db_path) as db:
            rows = db.execute("SELECT name,created,last_used FROM profiles ORDER BY name").fetchall()
        return {"profiles": [{"name": r[0], "created_at": r[1], "last_used": r[2]} for r in rows]}

    def delete_profile(self, name: str):
        name = _name(name)
        with sqlite3.connect(self.db_path) as db: cur = db.execute("DELETE FROM profiles WHERE name=?", (name,))
        path = self._profile_path(name)
        if path.exists(): path.unlink()
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

    def _with_context(self, profile: str, action):
        profile = _name(profile)
        with sqlite3.connect(self.db_path) as db:
            if not db.execute("SELECT 1 FROM profiles WHERE name=?", (profile,)).fetchone():
                raise ToolExecutionError("Browser profile does not exist; create it first.")
            db.execute("UPDATE profiles SET last_used=? WHERE name=?", (time.time(), profile))
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise ToolExecutionError("Install the browser extra and Chromium browser binaries.") from exc
        state = self._profile_path(profile)
        tabs, active = self._manifest(profile)
        with sync_playwright() as p:
            launch_args = []
            if self.extension_dirs:
                if self.headless:
                    raise ToolExecutionError("Chromium extensions require headed mode.")
                paths = [str(x) for x in self.extension_dirs]
                launch_args = ["--disable-extensions-except=" + ",".join(paths),
                               "--load-extension=" + ",".join(paths)]
            browser = p.chromium.launch(headless=self.headless, args=launch_args)
            context = browser.new_context(storage_state=str(state) if state.exists() else None,
                                          service_workers="block", accept_downloads=False)
            self._guard_context(context)
            try:
                pages = []
                for saved_url in tabs:
                    try:
                        page = context.new_page()
                        self._guard(page)
                        page.goto(_url(saved_url), wait_until="domcontentloaded", timeout=20000)
                        pages.append(page)
                    except Exception:
                        try: page.close()
                        except Exception: pass
                if not pages:
                    pages = [context.new_page()]
                    self._guard(pages[0])
                active = min(max(active, 0), len(pages)-1)
                result = action(context, pages, active)
                new_tabs = [p.url for p in context.pages if p.url.startswith(("http://","https://"))][:self.max_tabs]
                active_page = result.pop("_active_page", None) if isinstance(result, dict) else None
                active_index = context.pages.index(active_page) if active_page in context.pages else min(active, max(0,len(new_tabs)-1))
                with sqlite3.connect(self.db_path) as db:
                    db.execute("UPDATE profiles SET tabs=?,active_tab=? WHERE name=?",
                               (json.dumps(new_tabs), active_index, profile))
                context.storage_state(path=str(state))
                return result
            finally:
                context.close()
                browser.close()

    def navigate(self, profile: str, url: str, wait_until: str = "domcontentloaded"):
        url = _url(url)
        if wait_until not in {"domcontentloaded","load","networkidle","commit"}:
            raise ToolExecutionError("Unsupported navigation wait condition.")
        def run(ctx,pages,active):
            page=pages[active]; page.goto(url,wait_until=wait_until,timeout=25000); _url(page.url)
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
                if len(ctx.pages)>=self.max_tabs: raise ToolExecutionError("Browser tab limit reached.")
                page=ctx.new_page(); self._guard(page)
                if url: page.goto(_url(url),wait_until="domcontentloaded",timeout=25000)
                return {"created":True,"tab_index":len(ctx.pages)-1,"url":page.url,"_active_page":page}
            if index is None or not 0<=index<len(ctx.pages): raise ToolExecutionError("A valid tab index is required.")
            page=ctx.pages[index]
            if operation=="select": return {"selected":index,"url":page.url,"_active_page":page}
            if operation=="close":
                if len(ctx.pages)==1: raise ToolExecutionError("Cannot close the only browser tab.")
                page.close(); return {"closed":index}
            raise ToolExecutionError("Unknown tab operation.")
        return self._with_context(profile,run)

    def popup(self, profile: str, selector: str, timeout_ms: int = 5000):
        if not selector or len(selector)>500 or not 500<=timeout_ms<=15000: raise ToolExecutionError("Popup selector or timeout is invalid.")
        def run(ctx,pages,active):
            try:
                with ctx.expect_page(timeout=timeout_ms) as info: pages[active].locator(selector).first.click(timeout=timeout_ms)
                page=info.value; page.wait_for_load_state("domcontentloaded",timeout=timeout_ms); _url(page.url)
                self._guard(page)
                return {"opened":True,"url":page.url,"title":page.title(),"tab_index":ctx.pages.index(page),"_active_page":page}
            except Exception as exc: raise ToolExecutionError(f"Popup was not captured ({type(exc).__name__}).") from exc
        return self._with_context(profile,run)

    def frame(self, profile: str, frame_selector: str, action: str, selector: str="body", value: str|None=None):
        if not frame_selector or len(frame_selector)>500 or not selector or len(selector)>500: raise ToolExecutionError("Frame and element selectors must be bounded.")
        def run(ctx,pages,active):
            loc=pages[active].frame_locator(frame_selector).locator(selector).first
            if action=="read": return {"text":loc.inner_text(timeout=10000)[:10000],"url":pages[active].url}
            if action=="click": loc.click(timeout=10000)
            elif action=="fill":
                if value is None or len(value)>5000: raise ToolExecutionError("Frame fill requires a value up to 5000 characters.")
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
                if name: ctx.clear_cookies(name=name)
                else: ctx.clear_cookies()
                return {"cleared":True,"name":name}
            raise ToolExecutionError("Cookie operation must be list or clear.")
        return self._with_context(profile,run)

    def scrape(self, profile: str, selector: str, attributes: list[str]|None=None, limit: int=50):
        if not selector or len(selector)>500 or not 1<=limit<=200: raise ToolExecutionError("Scrape selector or result limit is invalid.")
        attrs=attributes or ["href"]
        if len(attrs)>8 or any(not re.fullmatch(r"[A-Za-z_:][-A-Za-z0-9_:.]{0,63}",a) for a in attrs):
            raise ToolExecutionError("Invalid attribute list.")
        def run(ctx,pages,active):
            items=pages[active].locator(selector).all()[:limit]; records=[]
            for item in items:
                rec={"text":item.inner_text(timeout=5000)[:2000]}
                for attr in attrs: rec[attr]=item.get_attribute(attr,timeout=5000)
                records.append(rec)
            return {"url":pages[active].url,"selector":selector,"count":len(records),"records":records}
        return self._with_context(profile,run)

    def network(self, profile: str, url: str|None=None):
        if url: url=_url(url)
        def run(ctx,pages,active):
            page=pages[active]; req=[]; resp=[]; fail=[]; sockets=[]
            page.on("request",lambda r:req.append({"method":r.method,"url":r.url[:2000],"resource_type":r.resource_type}))
            page.on("response",lambda r:resp.append({"status":r.status,"url":r.url[:2000],"method":r.request.method}))
            page.on("requestfailed",lambda r:fail.append({"url":r.url[:2000],"error":(r.failure or "")[:300]}))
            page.on("websocket",lambda ws:sockets.append({"url":ws.url[:2000]}))
            if url: page.goto(url,wait_until="domcontentloaded",timeout=25000)
            return {"url":page.url,"requests":req[:_MAX_EVENTS],"responses":resp[:_MAX_EVENTS],
                    "failures":fail[:_MAX_EVENTS],"websockets":sockets[:_MAX_EVENTS],
                    "truncated":any(len(x)>_MAX_EVENTS for x in (req,resp,fail,sockets))}
        return self._with_context(profile,run)

    def challenge(self, profile: str):
        def run(ctx,pages,active):
            page=pages[active]; title=page.title(); body=page.locator("body").inner_text(timeout=5000)[:12000].casefold()
            indicators=[x for x in ("captcha","verify you are human","are you a robot","cloudflare","checking your browser","security challenge") if x in (title+" "+body).casefold()]
            frames=[f.url[:1000] for f in page.frames if any(x in f.url.casefold() for x in ("captcha","recaptcha","hcaptcha","challenges.cloudflare"))]
            return {"challenge_detected":bool(indicators or frames),"indicators":indicators,
                    "challenge_frames":frames,"requires_human":bool(indicators or frames),
                    "note":"ULTK detects challenges but does not solve or bypass CAPTCHA."}
        return self._with_context(profile,run)

    def auth_status(self, profile: str, selectors: list[str]):
        if len(selectors)>10 or any(not isinstance(s,str) or len(s)>300 for s in selectors): raise ToolExecutionError("Authentication selectors are invalid.")
        def run(ctx,pages,active):
            page=pages[active]; found=[]
            for selector in selectors:
                try:
                    if page.locator(selector).count(): found.append(selector)
                except Exception: pass
            return {"url":page.url,"title":page.title(),"authenticated_heuristic":not bool(found),
                    "login_indicators_found":found,"warning":"Selector heuristic only; not authoritative identity verification."}
        return self._with_context(profile,run)

    def form_preview(self, profile: str, selector: str):
        if not selector or len(selector)>500: raise ToolExecutionError("A bounded form selector is required.")
        def run(ctx,pages,active):
            return pages[active].locator(selector).first.evaluate("""el => {
              if(el.tagName!=='FORM') throw new Error('not a form');
              return {action:el.action,method:(el.method||'get').toUpperCase(),
                fields:Array.from(el.elements).filter(x=>x.name).slice(0,100).map(x=>({
                  name:x.name,type:x.type||x.tagName.toLowerCase(),required:!!x.required,
                  value:x.type==='password'?'[redacted]':String(x.value||'').slice(0,300)}))};
            }""")
        return self._with_context(profile,run)

    def submit_form(self, profile: str, selector: str):
        if not selector or len(selector)>500: raise ToolExecutionError("A bounded form selector is required.")
        def run(ctx,pages,active):
            page=pages[active]; form=page.locator(selector).first
            dest=form.evaluate("""el => {if(el.tagName!=='FORM') throw new Error('not a form');
              const u=new URL(el.action||location.href,location.href);
              return {action:u.href,method:(el.method||'get').toUpperCase()};}""")
            _url(dest["action"])
            form.evaluate("(el) => el.requestSubmit ? el.requestSubmit() : el.submit()")
            page.wait_for_load_state("domcontentloaded",timeout=15000)
            return {"submitted":True,"url":page.url,"destination":dest["action"],"method":dest["method"]}
        return self._with_context(profile,run)

    def monitor_add(self,url:str,selector:str|None=None):
        _url(url)
        if selector is not None and (not selector or len(selector)>500): raise ToolExecutionError("Monitor selector is invalid.")
        mid=uuid.uuid4().hex
        with sqlite3.connect(self.db_path) as db: db.execute("INSERT INTO site_changes(monitor_id,url,selector) VALUES (?,?,?)",(mid,url,selector))
        return {"monitor_id":mid,"url":url,"selector":selector}

    def monitor_check(self,monitor_id:str):
        if not isinstance(monitor_id,str) or len(monitor_id)!=32: raise ToolExecutionError("Invalid monitor identifier.")
        with sqlite3.connect(self.db_path) as db:
            row=db.execute("SELECT url,selector,last_hash FROM site_changes WHERE monitor_id=? AND enabled=1",(monitor_id,)).fetchone()
        if row is None: raise ToolExecutionError("Website monitor not found or disabled.")
        result=self._fetch_monitor(row[0],row[1]); digest=hashlib.sha256(result["text"].encode()).hexdigest()
        changed=row[2] is not None and row[2]!=digest
        with sqlite3.connect(self.db_path) as db: db.execute("UPDATE site_changes SET last_hash=? WHERE monitor_id=?",(digest,monitor_id))
        event = {"monitor_id":monitor_id,"url":row[0],"changed":changed,"title":result["title"],"text_excerpt":result["text"][:3000]}
        if changed and self.notifier is not None:
            self.notifier(event)
        return event

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
                        if not selector or len(selector)>500: raise ToolExecutionError("Invalid test selector.")
                        loc = page.locator(selector).first
                        if action == "click": loc.click(timeout=10000)
                        else:
                            value = step.get("value","")
                            if not isinstance(value,str) or len(value)>5000: raise ToolExecutionError("Invalid test value.")
                            loc.fill(value,timeout=10000)
                    elif action == "expect_text":
                        text = step.get("text","")
                        if not isinstance(text,str) or not text or len(text)>1000: raise ToolExecutionError("Invalid expected text.")
                        if text not in page.locator("body").inner_text(timeout=5000):
                            raise ToolExecutionError("Expected text was not present.")
                    elif action == "expect_visible":
                        selector = step.get("selector","")
                        if not selector or len(selector)>500: raise ToolExecutionError("Invalid visibility selector.")
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

    def list_extensions(self):
        return {"extensions":[{"path":str(path),"manifest_present":(path/"manifest.json").is_file()}
                              for path in self.extension_dirs],
                "note":"Only host-configured extension directories are loaded; model input cannot add extensions."}

    def _fetch_monitor(self,url,selector):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc: raise ToolExecutionError("Install the browser extra and Chromium.") from exc
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True); page=browser.new_page(); self._guard(page)
            try:
                page.goto(_url(url),wait_until="domcontentloaded",timeout=25000)
                loc=page.locator(selector) if selector else page.locator("body")
                return {"title":page.title(),"text":loc.inner_text(timeout=10000)[:20000]}
            finally: browser.close()


def create_comprehensive_browser_tools(*,profile_root:str|Path="./browser_profiles",headless:bool=True,
                                        extension_dirs:tuple[str|Path,...]=(),notifier=None):
    b=BrowserControlPlane(profile_root,headless=headless,extension_dirs=extension_dirs,notifier=notifier)
    p={"type":"string","minLength":1,"maxLength":64}
    return (
      FunctionTool("browser.profile_create","Create a named persistent browser profile; optional clone copies saved cookies/storage state.",
        object_schema({"name":p,"clone_from":p},["name"]),"browser:profile:manage",b.create_profile),
      FunctionTool("browser.profile_list","List browser profiles and last-used timestamps.",object_schema({}),"browser:profile:read",b.list_profiles),
      FunctionTool("browser.extensions_list","List host-trusted browser extensions configured for this browser pack.",
        object_schema({}),"browser:extensions:read",b.list_extensions),
      FunctionTool("browser.profile_delete","Delete a profile and its saved authentication state.",object_schema({"name":p},["name"]),"browser:profile:manage",b.delete_profile),
      FunctionTool("browser.navigate","Navigate the active tab of a named profile to a public HTTP(S) URL.",
        object_schema({"profile":p,"url":{"type":"string","format":"uri"},
          "wait_until":{"type":"string","enum":["domcontentloaded","load","networkidle","commit"]}},
          ["profile","url"]),"browser:navigate",
        lambda profile,url,wait_until="domcontentloaded":b.navigate(profile,url,wait_until)),
      FunctionTool("browser.snapshot","Return the active tab URL, title and bounded visible text.",
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
      FunctionTool("browser.network_inspect","Capture request, response, failure and WebSocket metadata during navigation.",
        object_schema({"profile":p,"url":{"type":"string","format":"uri"}},["profile"]),
        "browser:network:inspect",lambda profile,url=None:b.network(profile,url),timeout=40),
      FunctionTool("browser.websocket_probe","Send one bounded text message to a public WebSocket and capture one bounded reply.",
        object_schema({"profile":p,"url":{"type":"string","minLength":1,"maxLength":2048},
          "message":{"type":"string","maxLength":4000},"timeout_ms":{"type":"integer","minimum":500,"maximum":10000}},
          ["profile","url","message"]),"browser:websocket:interact",
        lambda profile,url,message,timeout_ms=5000:b.websocket_probe(profile,url,message,timeout_ms),timeout=20),
      FunctionTool("browser.test_run","Run a bounded browser application test with navigation, interaction and assertions.",
        object_schema({"profile":p,"steps":{"type":"array","minItems":1,"maxItems":30,"items":{"type":"object"}}},
          ["profile","steps"]),"browser:test:run",lambda profile,steps:b.run_test(profile,steps),timeout=90),
      FunctionTool("browser.challenge_detect","Detect CAPTCHA/anti-bot pages; does not solve or bypass challenges.",
        object_schema({"profile":p},["profile"]),"browser:challenge:inspect",b.challenge),
      FunctionTool("browser.auth_status","Use host-supplied login selectors as an authentication heuristic.",
        object_schema({"profile":p,"login_selectors":{"type":"array","items":{"type":"string","maxLength":300},"maxItems":10}},["profile","login_selectors"]),
        "browser:auth:inspect",lambda profile,login_selectors:b.auth_status(profile,login_selectors)),
      FunctionTool("browser.form_preview","Inspect form destination, method and field metadata; password values are redacted.",
        object_schema({"profile":p,"selector":{"type":"string","minLength":1,"maxLength":500}},["profile","selector"]),
        "browser:form:preview",lambda profile,selector:b.form_preview(profile,selector)),
      FunctionTool("browser.form_submit","Submit a website form; requires explicit browser:submit:consequential approval.",
        object_schema({"profile":p,"selector":{"type":"string","minLength":1,"maxLength":500}},["profile","selector"]),
        "browser:submit:consequential",lambda profile,selector:b.submit_form(profile,selector),timeout=40),
      FunctionTool("web.change_monitor_add","Create a persistent website change monitor scoped optionally to a CSS selector.",
        object_schema({"url":{"type":"string","format":"uri"},"selector":{"type":"string","maxLength":500}},["url"]),
        "web:monitor:write",b.monitor_add),
      FunctionTool("web.change_monitor_check","Check a website monitor for selected-content changes.",
        object_schema({"monitor_id":{"type":"string","minLength":32,"maxLength":32}},["monitor_id"]),
        "web:monitor:check",b.monitor_check,timeout=40),
    )

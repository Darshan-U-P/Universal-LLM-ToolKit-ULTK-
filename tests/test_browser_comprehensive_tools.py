from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from ultk.builtins.browser_comprehensive import (
    BrowserControlPlane,
    _form_snapshot,
    _name,
    _url,
    create_comprehensive_browser_tools,
)
from ultk.engine import ToolEngine
from ultk.exceptions import ToolExecutionError


def test_profile_name_validation() -> None:
    assert _name("work-profile_1") == "work-profile_1"
    for invalid in ("", "../escape", "has space", "x" * 65):
        with pytest.raises(ToolExecutionError):
            _name(invalid)


def test_url_validation_rejects_non_http_and_credentials(monkeypatch) -> None:
    import ultk.builtins.browser_comprehensive as module

    monkeypatch.setattr(module, "_validate_public_url", lambda value: value)
    assert _url("https://example.com") == "https://example.com"
    for invalid in ("file:///etc/passwd", "ftp://example.com", "https://user:pass@example.com"):
        with pytest.raises(ToolExecutionError):
            _url(invalid)


def test_profile_create_clone_list_and_delete(tmp_path: Path) -> None:
    pack = BrowserControlPlane(tmp_path / "profiles")
    pack.create_profile("source")
    source_dir = pack._profile_path("source")
    source_dir.mkdir()
    (source_dir / "marker.txt").write_text("profile state", encoding="utf-8")

    pack.create_profile("clone", clone_from="source")
    assert (pack._profile_path("clone") / "marker.txt").read_text(encoding="utf-8") == "profile state"
    assert {row["name"] for row in pack.list_profiles()["profiles"]} == {"source", "clone"}
    assert pack.delete_profile("clone")["deleted"] is True
    assert pack.delete_profile("clone")["deleted"] is False


def test_profile_limits_are_validated(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        BrowserControlPlane(tmp_path / "profiles", max_tabs=13)
    with pytest.raises(ValueError):
        BrowserControlPlane(tmp_path / "profiles2", max_profiles=0)
    with pytest.raises(ValueError):
        BrowserControlPlane(tmp_path / "profiles3", max_download_bytes=0)


def test_profile_lock_is_reused_per_profile(tmp_path: Path) -> None:
    pack = BrowserControlPlane(tmp_path / "profiles")
    assert pack._profile_lock("one") is pack._profile_lock("one")
    assert pack._profile_lock("one") is not pack._profile_lock("two")


def test_tool_factory_registers_browser_surface(tmp_path: Path) -> None:
    tools = {tool.spec.name: tool for tool in create_comprehensive_browser_tools(
        profile_root=tmp_path / "profiles",
        download_root=tmp_path / "downloads",
    )}
    expected = {
        "browser.profile_create",
        "browser.profile_list",
        "browser.profile_delete",
        "browser.tabs",
        "browser.popup_capture",
        "browser.frame_interact",
        "browser.cookies",
        "browser.scrape_structured",
        "browser.download",
        "browser.network_inspect",
        "browser.websocket_probe",
        "browser.challenge_detect",
        "browser.auth_handoff",
        "browser.auth_status",
        "browser.form_preview",
        "browser.form_submit",
        "web.change_monitor_add",
        "web.change_monitor_check",
        "web.change_monitor_list",
        "web.change_monitor_delete",
    }
    assert expected <= set(tools)
    assert tools["browser.form_submit"].spec.capabilities == frozenset({"browser:submit:consequential"})
    assert tools["browser.download"].spec.capabilities == frozenset({"browser:download"})


def test_engine_installs_comprehensive_browser_tools(tmp_path: Path) -> None:
    engine = ToolEngine()
    engine.install_comprehensive_browser_tools(
        profile_root=tmp_path / "profiles",
        download_root=tmp_path / "downloads",
        max_download_bytes=12345,
    )
    names = {tool.spec.name for tool in engine.registry.list()}
    assert "browser.download" in names
    assert "browser.form_submit" in names


def test_monitor_lifecycle_and_notifier_failure_checkpoint(tmp_path: Path, monkeypatch) -> None:
    import ultk.builtins.browser_comprehensive as module

    monkeypatch.setattr(module, "_url", lambda value: value)
    notifier_calls = []
    def notifier(event):
        notifier_calls.append(event)
        raise RuntimeError("notification unavailable")

    pack = BrowserControlPlane(tmp_path / "profiles", notifier=notifier)
    monitor = pack.monitor_add("https://example.com", "main")
    assert pack.monitor_list()["count"] == 1
    monkeypatch.setattr(pack, "_fetch_monitor", lambda url, selector: {
        "title": "Updated", "text": "changed content",
    })
    with sqlite3.connect(pack.db_path) as db:
        db.execute("UPDATE site_changes SET last_hash=? WHERE monitor_id=?", ("old-hash", monitor["monitor_id"]))
    with pytest.raises(ToolExecutionError, match="checkpoint was not advanced"):
        pack.monitor_check(monitor["monitor_id"])
    with sqlite3.connect(pack.db_path) as db:
        last_hash = db.execute(
            "SELECT last_hash FROM site_changes WHERE monitor_id=?",
            (monitor["monitor_id"],),
        ).fetchone()[0]
    assert last_hash == "old-hash"
    assert len(notifier_calls) == 1
    assert pack.monitor_delete(monitor["monitor_id"])["deleted"] is True
    with pytest.raises(ToolExecutionError):
        pack.monitor_delete(monitor["monitor_id"])


class FakeDownload:
    suggested_filename = "../unsafe report.txt"

    def __init__(self, content: bytes):
        self.content = content

    def save_as(self, path: str) -> None:
        Path(path).write_bytes(self.content)


class FakeExpectDownload:
    def __init__(self, download):
        self.value = download

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class FakeLocator:
    @property
    def first(self):
        return self

    def click(self, timeout: int):
        return None


class FakePage:
    url = "https://example.com"

    def __init__(self, download):
        self.download = download

    def expect_download(self, timeout: int):
        return FakeExpectDownload(self.download)

    def locator(self, selector: str):
        return FakeLocator()


def test_download_sanitizes_suggested_filename_and_hashes_content(tmp_path: Path) -> None:
    content = b"browser download payload"
    pack = BrowserControlPlane(tmp_path / "profiles", download_root=tmp_path / "downloads")
    page = FakePage(FakeDownload(content))
    pack._with_context = lambda profile, action: action(None, [page], 0)
    result = pack.download("work", "a.download")
    path = Path(result["path"])
    assert path.parent == pack.download_root
    assert path.name == "unsafe report.txt"
    assert path.read_bytes() == content
    assert result["sha256"] == hashlib.sha256(content).hexdigest()


def test_download_rejects_path_traversal_filename(tmp_path: Path) -> None:
    pack = BrowserControlPlane(tmp_path / "profiles")
    with pytest.raises(ToolExecutionError, match="simple file name"):
        pack.download("work", "a.download", "../escape.txt")


def test_download_rejects_oversized_file_and_cleans_temporary_file(tmp_path: Path) -> None:
    pack = BrowserControlPlane(
        tmp_path / "profiles",
        download_root=tmp_path / "downloads",
        max_download_bytes=4,
    )
    page = FakePage(FakeDownload(b"too large"))
    pack._with_context = lambda profile, action: action(None, [page], 0)
    with pytest.raises(ToolExecutionError, match="byte limit"):
        pack.download("work", "a.download")
    assert list(pack.download_root.iterdir()) == []


def test_scrape_reads_at_most_configured_limit(tmp_path: Path) -> None:
    pack = BrowserControlPlane(tmp_path / "profiles")
    calls = []

    class Item:
        def inner_text(self, timeout):
            return "item"

        def get_attribute(self, name, timeout):
            return name

    class Locator:
        def count(self):
            return 5000

        def nth(self, index):
            calls.append(index)
            return Item()

    page = SimpleNamespace(url="https://example.com", locator=lambda selector: Locator())
    pack._with_context = lambda profile, action: action(None, [page], 0)
    result = pack.scrape("work", ".item", limit=25)
    assert result["count"] == 25
    assert result["truncated"] is True
    assert calls == list(range(25))


def test_auth_status_requires_nonempty_selector_list(tmp_path: Path) -> None:
    pack = BrowserControlPlane(tmp_path / "profiles")
    with pytest.raises(ToolExecutionError, match="1-10"):
        pack.auth_status("work", [])


def test_form_snapshot_redacts_password_hidden_and_file_values() -> None:
    fields = [
        {"name": "password", "type": "password", "value": "secret"},
        {"name": "csrf", "type": "hidden", "value": "token"},
        {"name": "attachment", "type": "file", "value": "C:/secret.txt"},
        {"name": "display", "type": "text", "value": "visible"},
    ]

    class Locator:
        @property
        def first(self):
            return self

        def evaluate(self, script):
            return {
                "action": "https://example.com/submit",
                "method": "POST",
                "fields": [dict(field, checked=False, selected_values=[]) for field in fields],
            }

    page = SimpleNamespace(locator=lambda selector: Locator())
    snapshot = _form_snapshot(page, "form")
    values = {field["name"]: field["value"] for field in snapshot["fields"]}
    assert values["password"] == "[redacted]"
    assert values["csrf"] == "[redacted]"
    assert values["attachment"] == "[redacted]"
    assert values["display"] == "visible"
    assert all(len(field["value_sha256"]) == 64 for field in snapshot["fields"])


def test_network_capture_window_is_bounded(tmp_path: Path) -> None:
    pack = BrowserControlPlane(tmp_path / "profiles")
    with pytest.raises(ToolExecutionError, match="100 and 10000"):
        pack.network("work", capture_ms=10001)


def test_profile_workflow_prevalidates_all_steps_before_opening_browser(tmp_path: Path, monkeypatch) -> None:
    import ultk.builtins.browser_comprehensive as module

    monkeypatch.setattr(module, "_url", lambda value: value)
    pack = BrowserControlPlane(tmp_path / "profiles")
    pack._with_context = lambda profile, action: pytest.fail("workflow should reject before opening a browser")
    with pytest.raises(ToolExecutionError, match="unsupported action"):
        pack.workflow("work", [
            {"action": "navigate", "url": "https://example.com"},
            {"action": "execute_javascript", "script": "alert(1)"},
        ])


def test_profile_workflow_executes_prevalidated_steps_and_returns_active_page(tmp_path: Path) -> None:
    pack = BrowserControlPlane(tmp_path / "profiles")

    class Locator:
        first = None

        def click(self, timeout):
            return None

        def inner_text(self, timeout):
            return "hello"

        def is_visible(self, timeout):
            return True

    locator = Locator()
    locator.first = locator

    class Page:
        url = "https://example.com"
        def __init__(self):
            self.visited = []
        def goto(self, url, wait_until, timeout):
            self.url = url
            self.visited.append(url)
        def locator(self, selector):
            return locator
        def title(self):
            return "Example"
        def wait_for_timeout(self, milliseconds):
            self.waited = milliseconds

    page = Page()
    context = SimpleNamespace(pages=[page])
    pack._with_context = lambda profile, action: action(context, [page], 0)
    result = pack.workflow("work", [
        {"action": "navigate", "url": "https://example.com/page"},
        {"action": "click", "selector": "button"},
        {"action": "expect_text", "text": "hello"},
        {"action": "wait", "milliseconds": 100},
    ])
    assert result["steps_completed"] == 4
    assert page.visited == ["https://example.com/page"]
    assert page.waited == 100
    assert result["_active_page"] is page

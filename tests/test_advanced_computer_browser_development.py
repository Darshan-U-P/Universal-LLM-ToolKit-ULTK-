from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from ultk.builtins.browser_automation import SiteMonitorStore, _clear_session, create_advanced_browser_tools
from ultk.builtins.computer_advanced import create_advanced_computer_tools
from ultk.builtins import web as web_tools
from ultk.builtins.development_advanced import (
    RestrictedInterpreter,
    create_advanced_development_tools,
)
from ultk.builtins.scheduler import PersistentScheduler
from ultk.engine import ToolEngine
from ultk.permissions import AllowListPolicy


def test_advanced_computer_pack_exposes_window_app_and_workflow_tools() -> None:
    names = {tool.spec.name for tool in create_advanced_computer_tools()}
    assert {
        "computer.window_action",
        "computer.list_applications",
        "computer.application_action",
        "computer.desktop_workflow",
    } <= names


def test_scheduler_jobs_persist_and_run_only_configured_handlers(tmp_path: Path) -> None:
    calls = []
    database = tmp_path / "scheduler.sqlite3"
    scheduler = PersistentScheduler(database, {"record": lambda payload: calls.append(payload)})
    job = scheduler.add("record", {"task": "heartbeat"}, 60)
    with sqlite3.connect(database) as db:
        db.execute("UPDATE jobs SET next_run=0 WHERE id=?", (job["job_id"],))
    result = scheduler.run_due()
    assert result["executed"] == 1
    assert calls == [{"task": "heartbeat"}]
    assert scheduler.list()[0]["last_status"] == "success"


def test_scheduler_rejects_unconfigured_handler(tmp_path: Path) -> None:
    scheduler = PersistentScheduler(tmp_path / "jobs.sqlite3", {})
    with pytest.raises(Exception, match="not configured"):
        scheduler.add("arbitrary", {}, 60)


def test_browser_pack_exposes_interaction_workflow_and_monitor_tools(tmp_path: Path) -> None:
    tools = create_advanced_browser_tools(
        session_root=tmp_path / "sessions",
        monitor_database=tmp_path / "monitors.sqlite3",
    )
    names = {tool.spec.name for tool in tools}
    assert {
        "browser.navigate",
        "browser.interact",
        "browser.clear_session",
        "browser.snapshot",
        "browser.workflow",
        "web.monitor_add",
        "web.monitor_list",
        "web.monitor_check",
    } <= names


def test_site_monitor_storage_is_persistent(tmp_path: Path) -> None:
    database = tmp_path / "monitors.sqlite3"
    first = SiteMonitorStore(database)
    assert first.list() == []
    second = SiteMonitorStore(database)
    assert second.list() == []


def test_restricted_interpreter_keeps_session_variables() -> None:
    interpreter = RestrictedInterpreter()
    interpreter.execute("session-a", "x = 20")
    result = interpreter.execute("session-a", "x * 2 + 1")
    assert result["value"] == 41


def test_restricted_interpreter_rejects_imports_and_arbitrary_calls() -> None:
    interpreter = RestrictedInterpreter()
    with pytest.raises(Exception, match="Only expressions"):
        interpreter.execute("session-a", "import os")
    with pytest.raises(Exception, match="Unsupported syntax"):
        interpreter.execute("session-a", "__import__('os')")


def test_advanced_development_pack_installs_without_external_toolchains(tmp_path: Path) -> None:
    engine = ToolEngine(policy=AllowListPolicy({"development.interpreter"}))
    engine.install_advanced_development_tools(project_root=tmp_path)
    names = {tool.spec.name for tool in engine.registry.list()}
    assert {
        "development.interpreter",
        "development.debug_python",
        "development.git_write",
        "development.compile",
        "development.package",
        "development.build",
        "development.deploy",
        "development.api_test",
        "development.ide_open",
        "development.static_analysis",
    } <= names


@pytest.mark.asyncio
async def test_advanced_tool_packs_are_capability_gated(tmp_path: Path) -> None:
    engine = ToolEngine(policy=AllowListPolicy({"development.interpreter"}))
    engine.install_advanced_development_tools(project_root=tmp_path)
    arguments = {"session_id": "s1", "source": "2 + 2"}
    denied = await engine.execute("development.interpreter", arguments)
    assert denied.is_error
    allowed = await engine.execute(
        "development.interpreter", arguments,
        granted_capabilities=frozenset({"development:interpreter"}),
    )
    assert not allowed.is_error
    assert "4" in allowed.content


def test_interpreter_rejects_oversized_range_and_string_multiplication() -> None:
    interpreter = RestrictedInterpreter()
    with pytest.raises(Exception, match="10000"):
        interpreter.execute("safe", "range(100000000)")
    with pytest.raises(Exception, match="too large"):
        interpreter.execute("safe", "'x' * 100000000")


def test_browser_session_clear_removes_persisted_state(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    root.mkdir()
    state = root / f"{hashlib.sha256(b'session-1').hexdigest()}.json"
    state.write_text("{}", encoding="utf-8")
    result = _clear_session(str(root), "session-1")
    assert result["cleared"] is True
    assert not state.exists()


def test_download_checksum_verification_is_atomic(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        web_tools,
        "_request",
        lambda url, max_bytes: ("https://example.org/file", b"payload", "application/octet-stream"),
    )
    digest = hashlib.sha256(b"payload").hexdigest()
    result = web_tools._download("https://example.org/file", "artifact.bin",
                                 str(tmp_path), expected_sha256=digest)
    assert result["checksum_verified"] is True
    assert result["sha256"] == digest
    assert (tmp_path / "artifact.bin").read_bytes() == b"payload"
    with pytest.raises(Exception, match="SHA-256"):
        web_tools._download("https://example.org/file", "wrong.bin",
                            str(tmp_path), expected_sha256="0" * 64)
    assert not (tmp_path / "wrong.bin").exists()

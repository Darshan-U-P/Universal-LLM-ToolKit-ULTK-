from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ultk.builtins.browser_automation import SiteMonitorStore, create_advanced_browser_tools
from ultk.builtins.computer_advanced import create_advanced_computer_tools
from ultk.builtins.development_advanced import (
    RestrictedInterpreter,
    create_advanced_development_tools,
)
from ultk.builtins.scheduler import PersistentScheduler, create_scheduler_tools
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

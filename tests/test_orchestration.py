"""Tests for persistent workflow orchestration contracts."""

from __future__ import annotations

import asyncio
import json

import pytest

from ultk.exceptions import WorkflowError
from ultk.models import ToolResult
from ultk.orchestration import WorkflowEngine, WorkflowStep


class FakeDispatcher:
    def __init__(self, outcomes=None):
        self.outcomes = outcomes or {}
        self.calls = []
        self.active = 0
        self.max_active = 0

    async def execute(self, request, *, session_id="default", granted_capabilities=frozenset()):
        self.calls.append((request.name, dict(request.arguments)))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.005)
            queue = self.outcomes.get(request.name, [])
            outcome = queue.pop(0) if queue else {"ok": True, "args": dict(request.arguments)}
            if isinstance(outcome, Exception):
                return ToolResult(request.id, request.name, str(outcome), True)
            if isinstance(outcome, tuple) and outcome[0] == "error":
                return ToolResult(request.id, request.name, outcome[1], True)
            return ToolResult(request.id, request.name, json.dumps(outcome))
        finally:
            self.active -= 1


def make_engine(tmp_path, dispatcher=None, **kwargs):
    return WorkflowEngine(dispatcher or FakeDispatcher(), tmp_path / "workflow.sqlite3", **kwargs)


@pytest.mark.asyncio
async def test_dag_resolves_explicit_reference_and_persists_result(tmp_path):
    dispatcher = FakeDispatcher({"data.lookup": [{"value": 42}]})
    engine = make_engine(tmp_path, dispatcher)
    run_id = engine.submit([
        WorkflowStep("source", "data.lookup", {"key": "answer"}),
        WorkflowStep("consumer", "data.consume", {"value": {"$ref": "source#/value"}},
                     depends_on=("source",)),
    ])
    result = await engine.run(run_id)
    assert result["status"] == "succeeded"
    assert dispatcher.calls[1] == ("data.consume", {"value": 42})
    assert result["steps"]["source"]["output"]["value"] == 42
    assert [event["event"] for event in engine.get_events(run_id)]


def test_rejects_cycles_and_references_without_ancestor_dependency(tmp_path):
    engine = make_engine(tmp_path)
    with pytest.raises(WorkflowError, match="cycle"):
        engine.submit([
            WorkflowStep("a", "x.a", {}, depends_on=("b",)),
            WorkflowStep("b", "x.b", {}, depends_on=("a",)),
        ])
    with pytest.raises(WorkflowError, match="ancestor"):
        engine.submit([
            WorkflowStep("a", "x.a", {}),
            WorkflowStep("b", "x.b", {"value": {"$ref": "a"}}),
        ])


@pytest.mark.asyncio
async def test_failed_dependency_skips_dependent_step(tmp_path):
    dispatcher = FakeDispatcher({"task.fail": [("error", "failure")]})
    engine = make_engine(tmp_path, dispatcher)
    run_id = engine.submit([
        WorkflowStep("bad", "task.fail", {}),
        WorkflowStep("downstream", "task.never", {}, depends_on=("bad",)),
        WorkflowStep("independent", "task.ok", {}),
    ])
    result = await engine.run(run_id)
    assert result["status"] == "failed"
    assert result["steps"]["bad"]["status"] == "failed"
    assert result["steps"]["downstream"]["status"] == "skipped"
    assert "task.never" not in [name for name, _ in dispatcher.calls]
    assert result["steps"]["independent"]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_retry_uses_bounded_exponential_backoff(tmp_path):
    dispatcher = FakeDispatcher({"task.flaky": [("error", "temporary"), {"ok": True}]})
    engine = make_engine(tmp_path, dispatcher)
    run_id = engine.submit([
        WorkflowStep("flaky", "task.flaky", {}, max_attempts=2, retry_delay_seconds=0)
    ])
    result = await engine.run(run_id)
    assert result["status"] == "succeeded"
    assert result["steps"]["flaky"]["attempts"] == 2


@pytest.mark.asyncio
async def test_concurrency_limit_applies_to_independent_steps(tmp_path):
    dispatcher = FakeDispatcher()
    engine = make_engine(tmp_path, dispatcher, max_concurrency=2)
    run_id = engine.submit([WorkflowStep(str(i), "task.run", {}) for i in range(5)])
    await engine.run(run_id)
    assert dispatcher.max_active == 2


def test_recovery_and_replay_create_new_execution(tmp_path):
    engine = make_engine(tmp_path)
    run_id = engine.submit([WorkflowStep("one", "task.one", {})])
    engine.store.mark(run_id, "one", "running", attempts=1)
    recovered = engine.recover(run_id)
    assert recovered["steps"]["one"]["status"] == "pending"
    replay_id = engine.replay(run_id)
    assert replay_id != run_id
    assert engine.get(replay_id)["steps"]["one"]["status"] == "pending"


@pytest.mark.asyncio
async def test_cancel_request_prevents_pending_steps_from_running(tmp_path):
    dispatcher = FakeDispatcher()
    engine = make_engine(tmp_path, dispatcher)
    run_id = engine.submit([WorkflowStep("one", "task.one", {})])
    engine.cancel(run_id)
    result = await engine.run(run_id)
    assert result["status"] == "cancelled"
    assert result["steps"]["one"]["status"] == "cancelled"
    assert dispatcher.calls == []

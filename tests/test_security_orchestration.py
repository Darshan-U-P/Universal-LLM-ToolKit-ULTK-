from __future__ import annotations

import pytest

from ultk.approvals import ApprovalPolicy, SQLiteApprovalStore
from ultk.audit import SQLiteAuditLogger
from ultk.execution import ToolDispatcher
from ultk.models import ToolCallRequest, ToolContext, ToolSpec
from ultk.orchestration import WorkflowEngine, WorkflowStep
from ultk.permissions import AllowListPolicy
from ultk.registry import ToolRegistry


class CounterTool:
    def __init__(self) -> None:
        self.calls = 0
        self.spec = ToolSpec(
            name="test.write",
            description="Count invocations",
            input_schema={
                "type": "object",
                "properties": {"value": {"type": "integer"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            capabilities=frozenset({"test:write"}),
        )

    async def invoke(self, arguments: dict, context: ToolContext) -> dict:
        self.calls += 1
        return {"written": arguments["value"]}


class SourceTool:
    spec = ToolSpec(
        name="test.source",
        description="Return a source value",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        capabilities=frozenset({"test:run"}),
    )

    async def invoke(self, arguments: dict, context: ToolContext) -> dict:
        return {"value": 3}


class DoubleTool:
    spec = ToolSpec(
        name="test.double",
        description="Double an input",
        input_schema={
            "type": "object",
            "properties": {"number": {"type": "integer"}},
            "required": ["number"],
            "additionalProperties": False,
        },
        capabilities=frozenset({"test:run"}),
    )

    async def invoke(self, arguments: dict, context: ToolContext) -> dict:
        return {"double": arguments["number"] * 2}


@pytest.mark.asyncio
async def test_approval_is_exact_argument_bound_and_one_time(tmp_path) -> None:
    tool = CounterTool()
    registry = ToolRegistry()
    registry.register(tool)
    store = SQLiteApprovalStore(tmp_path / "approvals.sqlite3")
    policy = ApprovalPolicy(
        AllowListPolicy({"test.write"}), store,
        approval_capabilities={"test:write"},
    )
    dispatcher = ToolDispatcher(registry, policy)
    request = ToolCallRequest("call-1", "test.write", {"value": 7})

    pending = await dispatcher.execute(
        request, session_id="session-a",
        granted_capabilities=frozenset({"test:write"}),
    )
    assert pending.is_error
    assert pending.metadata["approval_required"] is True
    approval_id = pending.metadata["approval_id"]
    assert tool.calls == 0

    store.decide(approval_id, approved=True, actor="reviewer")
    changed = await dispatcher.execute(
        ToolCallRequest("call-2", "test.write", {"value": 8}),
        session_id="session-a",
        granted_capabilities=frozenset({"test:write"}),
    )
    assert changed.is_error
    assert tool.calls == 0

    approved = await dispatcher.execute(
        ToolCallRequest("call-3", "test.write", {"value": 7}),
        session_id="session-a",
        granted_capabilities=frozenset({"test:write"}),
    )
    assert not approved.is_error
    assert tool.calls == 1

    replay = await dispatcher.execute(
        ToolCallRequest("call-4", "test.write", {"value": 7}),
        session_id="session-a",
        granted_capabilities=frozenset({"test:write"}),
    )
    assert replay.is_error
    assert tool.calls == 1


@pytest.mark.asyncio
async def test_approval_is_session_bound(tmp_path) -> None:
    tool = CounterTool()
    registry = ToolRegistry()
    registry.register(tool)
    store = SQLiteApprovalStore(tmp_path / "approvals.sqlite3")
    policy = ApprovalPolicy(
        AllowListPolicy({"test.write"}), store,
        approval_capabilities={"test:write"},
    )
    dispatcher = ToolDispatcher(registry, policy)
    request = ToolCallRequest("call-1", "test.write", {"value": 4})
    pending = await dispatcher.execute(
        request, session_id="session-a",
        granted_capabilities=frozenset({"test:write"}),
    )
    store.decide(pending.metadata["approval_id"], approved=True, actor="reviewer")
    other_session = await dispatcher.execute(
        ToolCallRequest("call-2", "test.write", {"value": 4}),
        session_id="session-b",
        granted_capabilities=frozenset({"test:write"}),
    )
    assert other_session.is_error
    assert tool.calls == 0


@pytest.mark.asyncio
async def test_audit_chain_records_authorization_and_result_without_raw_arguments(tmp_path) -> None:
    registry = ToolRegistry()
    tool = CounterTool()
    registry.register(tool)
    audit = SQLiteAuditLogger(tmp_path / "audit.sqlite3")
    dispatcher = ToolDispatcher(registry, AllowListPolicy({"test.write"}), audit)
    result = await dispatcher.execute(
        ToolCallRequest("audit-call", "test.write", {"value": 12345}),
        granted_capabilities=frozenset({"test:write"}),
    )
    assert not result.is_error
    assert audit.verify() == {"valid": True, "checked": 2, "failed_at": None}

    import sqlite3

    with sqlite3.connect(audit.database) as db:
        rows = db.execute("SELECT event_json FROM audit_events").fetchall()
    assert all("12345" not in row[0] for row in rows)


@pytest.mark.asyncio
async def test_approval_request_callback_receives_exact_action_context(tmp_path) -> None:
    tool = CounterTool()
    registry = ToolRegistry()
    registry.register(tool)
    notices = []
    store = SQLiteApprovalStore(tmp_path / "approvals.sqlite3")
    policy = ApprovalPolicy(
        AllowListPolicy({"test.write"}),
        store,
        approval_capabilities={"test:write"},
        on_request=lambda notice: notices.append(notice),
    )
    dispatcher = ToolDispatcher(registry, policy)
    result = await dispatcher.execute(
        ToolCallRequest("call-notify", "test.write", {"value": 12}),
        session_id="session-notify",
        granted_capabilities=frozenset({"test:write"}),
    )
    assert result.is_error
    assert notices[0].approval_id == result.metadata["approval_id"]
    assert notices[0].tool_name == "test.write"
    assert notices[0].arguments == {"value": 12}

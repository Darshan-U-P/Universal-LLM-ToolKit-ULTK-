"""Persistent, exact-argument human approval workflow."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from ultk.exceptions import ApprovalRequiredError
from ultk.models import ToolContext, ToolSpec
from ultk.permissions import PermissionPolicy


def _digest_arguments(arguments: dict[str, Any]) -> str:
    encoded = json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class SQLiteApprovalStore:
    """One-time approvals bound to tool, session and canonical argument digest."""

    def __init__(self, database: str | Path, *, ttl_seconds: int = 600) -> None:
        if not 1 <= ttl_seconds <= 86_400:
            raise ValueError("Approval TTL must be between 1 second and 24 hours.")
        self.database = str(Path(database).expanduser().resolve())
        Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS approvals (
                approval_id TEXT PRIMARY KEY, tool_name TEXT NOT NULL, session_id TEXT NOT NULL,
                arguments_sha256 TEXT NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL,
                expires_at REAL NOT NULL, decided_at REAL, decided_by TEXT)""")
            db.execute("""CREATE INDEX IF NOT EXISTS idx_approvals_lookup
                ON approvals(tool_name, session_id, arguments_sha256, status, expires_at)""")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def create(self, tool_name: str, session_id: str, arguments: dict[str, Any]) -> str:
        digest, now = _digest_arguments(arguments), time.time()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("""SELECT approval_id FROM approvals
                WHERE tool_name=? AND session_id=? AND arguments_sha256=?
                AND status='pending' AND expires_at>? ORDER BY created_at DESC LIMIT 1""",
                (tool_name, session_id, digest, now)).fetchone()
            if existing:
                return str(existing["approval_id"])
            approval_id = uuid.uuid4().hex
            db.execute("""INSERT INTO approvals
                (approval_id,tool_name,session_id,arguments_sha256,status,created_at,expires_at)
                VALUES (?,?,?,?, 'pending',?,?)""",
                (approval_id, tool_name, session_id, digest, now, now + self.ttl_seconds))
            return approval_id

    def decide(self, approval_id: str, *, approved: bool, actor: str) -> dict[str, Any]:
        if not actor.strip() or len(actor) > 200:
            raise ValueError("A non-empty approval actor (max 200 characters) is required.")
        now = time.time()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status,expires_at FROM approvals WHERE approval_id=?",
                             (approval_id,)).fetchone()
            if row is None:
                return {"approval_id": approval_id, "updated": False, "reason": "not_found"}
            if row["status"] != "pending":
                return {"approval_id": approval_id, "updated": False, "reason": "already_decided"}
            if float(row["expires_at"]) <= now:
                db.execute("UPDATE approvals SET status='expired',decided_at=? WHERE approval_id=?",
                           (now, approval_id))
                return {"approval_id": approval_id, "updated": False, "reason": "expired"}
            status = "approved" if approved else "denied"
            db.execute("""UPDATE approvals SET status=?,decided_at=?,decided_by=?
                          WHERE approval_id=? AND status='pending'""",
                       (status, now, actor, approval_id))
        return {"approval_id": approval_id, "updated": True, "status": status}

    def consume(self, tool_name: str, session_id: str, arguments: dict[str, Any]) -> bool:
        now, digest = time.time(), _digest_arguments(arguments)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT approval_id FROM approvals
                WHERE tool_name=? AND session_id=? AND arguments_sha256=?
                AND status='approved' AND expires_at>? ORDER BY decided_at DESC LIMIT 1""",
                (tool_name, session_id, digest, now)).fetchone()
            if row is None:
                return False
            cursor = db.execute("""UPDATE approvals SET status='consumed'
                                   WHERE approval_id=? AND status='approved'""",
                                (row["approval_id"],))
            return cursor.rowcount == 1

    def list_pending(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500.")
        with self._connect() as db:
            rows = db.execute("""SELECT approval_id,tool_name,session_id,arguments_sha256,
                created_at,expires_at FROM approvals WHERE status='pending' AND expires_at>?
                ORDER BY created_at LIMIT ?""", (time.time(), limit)).fetchall()
        return [dict(row) for row in rows]


class ApprovalPolicy:
    """Wrap a policy and require one-time approval for selected capabilities."""

    def __init__(self, base_policy: PermissionPolicy, store: SQLiteApprovalStore, *,
                 approval_capabilities: set[str] | frozenset[str]) -> None:
        self.base_policy = base_policy
        self.store = store
        self.approval_capabilities = frozenset(approval_capabilities)

    async def authorize(self, spec: ToolSpec, context: ToolContext) -> bool:
        if not await self.base_policy.authorize(spec, context):
            return False
        if not spec.capabilities.intersection(self.approval_capabilities):
            return True
        arguments = dict(context.arguments)
        if self.store.consume(spec.name, context.session_id, arguments):
            return True
        approval_id = self.store.create(spec.name, context.session_id, arguments)
        raise ApprovalRequiredError(approval_id)

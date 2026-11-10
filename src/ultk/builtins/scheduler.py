"""Persistent scheduler primitives backed by SQLite.

The host application must call scheduler.run_due periodically (for example, once per minute).
Jobs survive process restarts; this module does not silently start a background daemon.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ultk.builtins._common import FunctionTool, object_schema
from ultk.exceptions import ToolExecutionError


class PersistentScheduler:
    def __init__(self, database: str | Path,
                 handlers: dict[str, Callable[[dict[str, Any]], Any]]) -> None:
        self.database = str(Path(database).expanduser().resolve())
        self.handlers = dict(handlers)
        Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, handler TEXT NOT NULL, payload TEXT NOT NULL,
                interval_seconds INTEGER NOT NULL, next_run REAL NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1, last_status TEXT)""")

    def _connect(self):
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def add(self, handler: str, payload: dict[str, Any], interval_seconds: int) -> dict[str, Any]:
        if handler not in self.handlers:
            raise ToolExecutionError("Handler is not configured by the host application.")
        if not 60 <= interval_seconds <= 31_536_000:
            raise ToolExecutionError("Intervals must be between 60 seconds and one year.")
        serialized = json.dumps(payload)
        if len(serialized.encode("utf-8")) > 10000:
            raise ToolExecutionError("Scheduled job payload exceeds 10 KB.")
        job_id = uuid.uuid4().hex
        with self._connect() as db:
            db.execute("INSERT INTO jobs VALUES (?, ?, ?, ?, ?, 1, NULL)",
                       (job_id, handler, serialized, interval_seconds,
                        time.time() + interval_seconds))
        return {"job_id": job_id, "next_run_in_seconds": interval_seconds}

    def list(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT id,handler,interval_seconds,next_run,enabled,last_status FROM jobs ORDER BY next_run"
            )]

    def remove(self, job_id: str) -> dict[str, Any]:
        with self._connect() as db:
            cur = db.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        return {"job_id": job_id, "removed": cur.rowcount == 1}

    def run_due(self, limit: int = 10) -> dict[str, Any]:
        now = time.time()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT * FROM jobs WHERE enabled=1 AND next_run<=? ORDER BY next_run LIMIT ?",
                (now, limit),
            ).fetchall()
            for row in rows:
                # Claim jobs in one transaction so concurrent workers do not double-dispatch.
                db.execute(
                    "UPDATE jobs SET next_run=? WHERE id=? AND next_run<=?",
                    (now + row["interval_seconds"], row["id"], now),
                )
        completed = []
        for row in rows:
            try:
                self.handlers[row["handler"]](json.loads(row["payload"]))
                status = "success"
            except Exception as exc:  # noqa: BLE001 - isolate scheduled task failures
                status = f"error:{type(exc).__name__}"
            with self._connect() as db:
                db.execute("UPDATE jobs SET last_status=? WHERE id=?", (status, row["id"]))
            completed.append({"job_id": row["id"], "status": status})
        return {"executed": len(completed), "jobs": completed}

def create_scheduler_tools(database: str | Path,
                           handlers: dict[str, Callable[[dict[str, Any]], Any]]) -> tuple[FunctionTool, ...]:
    scheduler = PersistentScheduler(database, handlers)
    return (
        FunctionTool("scheduler.add_job", "Schedule a host-configured handler to run at a fixed interval.",
                     object_schema({"handler": {"type": "string", "enum": sorted(handlers)},
                                    "payload": {"type": "object"},
                                    "interval_seconds": {"type": "integer", "minimum": 60, "maximum": 31536000}},
                                   ["handler", "payload", "interval_seconds"]),
                     "scheduler:write", scheduler.add),
        FunctionTool("scheduler.list_jobs", "List persistent scheduled jobs and their next run time.",
                     object_schema({}), "scheduler:read", scheduler.list),
        FunctionTool("scheduler.remove_job", "Remove a persistent scheduled job.",
                     object_schema({"job_id": {"type": "string", "minLength": 1, "maxLength": 64}},
                                   ["job_id"]),
                     "scheduler:write", scheduler.remove),
        FunctionTool("scheduler.run_due", "Execute due jobs; the host should invoke this periodically.",
                     object_schema({"limit": {"type": "integer", "minimum": 1, "maximum": 10}}),
                     "scheduler:execute", lambda limit=10: scheduler.run_due(limit)),
    )

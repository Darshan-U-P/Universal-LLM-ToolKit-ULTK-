"""Append-only SQLite audit trail with a tamper-evident hash chain."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class SQLiteAuditLogger:
    """Persist metadata-only events; raw argument values and tool outputs are omitted."""

    def __init__(self, database: str | Path) -> None:
        self.database = str(Path(database).expanduser().resolve())
        Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS audit_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_json TEXT NOT NULL,
                previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL UNIQUE)""")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def record(self, *, call_id: str, tool_name: str, session_id: str, outcome: str,
               is_error: bool, argument_sha256: str, argument_keys: list[str],
               granted_capabilities: list[str], approval_id: str | None = None,
               error_type: str | None = None) -> str:
        event = {
            "timestamp": time.time(), "call_id": call_id, "tool_name": tool_name,
            "session_id": session_id, "outcome": outcome, "is_error": is_error,
            "argument_sha256": argument_sha256, "argument_keys": sorted(argument_keys),
            "granted_capabilities": sorted(granted_capabilities),
            "approval_id": approval_id, "error_type": error_type,
        }
        event_json = _canonical(event)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT event_hash FROM audit_events ORDER BY sequence DESC LIMIT 1").fetchone()
            previous_hash = str(previous["event_hash"]) if previous else "0" * 64
            event_hash = hashlib.sha256((previous_hash + event_json).encode("utf-8")).hexdigest()
            db.execute("""INSERT INTO audit_events(event_json,previous_hash,event_hash)
                          VALUES (?,?,?)""", (event_json, previous_hash, event_hash))
        return event_hash

    def verify(self) -> dict[str, Any]:
        expected_previous, checked = "0" * 64, 0
        with self._connect() as db:
            rows = db.execute("""SELECT event_json,previous_hash,event_hash
                                 FROM audit_events ORDER BY sequence""").fetchall()
        for row in rows:
            event_json = str(row["event_json"])
            actual_previous, actual_hash = str(row["previous_hash"]), str(row["event_hash"])
            calculated = hashlib.sha256(
                (expected_previous + event_json).encode("utf-8")).hexdigest()
            if actual_previous != expected_previous or actual_hash != calculated:
                return {"valid": False, "checked": checked, "failed_at": checked + 1}
            expected_previous, checked = actual_hash, checked + 1
        return {"valid": True, "checked": checked, "failed_at": None}

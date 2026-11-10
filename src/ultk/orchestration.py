"""Persistent, dependency-aware workflow execution.

Runs are durable at step boundaries. A process crash during a running tool call can
cause that step to be retried after recovery; tools with external side effects should
therefore be idempotent or use their own idempotency keys.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, ClassVar

from ultk.exceptions import WorkflowError
from ultk.execution import ToolDispatcher
from ultk.models import ToolCallRequest, ToolResult


@dataclass(frozen=True, slots=True)
class WorkflowStep:
    step_id: str
    tool_name: str
    arguments: Mapping[str, Any]
    depends_on: tuple[str, ...] = ()
    max_attempts: int = 1
    retry_delay_seconds: float = 1.0


def _refs(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        if set(value) == {"$ref"} and isinstance(value["$ref"], str):
            found.add(value["$ref"].partition("#")[0])
        else:
            for item in value.values():
                found.update(_refs(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_refs(item))
    return found


def _resolve(value: Any, outputs: Mapping[str, Any]) -> Any:
    if isinstance(value, dict):
        if set(value) == {"$ref"}:
            reference = value["$ref"]
            if not isinstance(reference, str) or not reference:
                raise WorkflowError("$ref must be a non-empty string.")
            step_id, marker, pointer = reference.partition("#")
            if step_id not in outputs:
                raise WorkflowError(f"Referenced output is unavailable: {step_id}")
            result = outputs[step_id]
            if marker and pointer:
                if not pointer.startswith("/"):
                    raise WorkflowError("JSON Pointer must begin with '/'.")
                for part in pointer[1:].split("/"):
                    part = part.replace("~1", "/").replace("~0", "~")
                    try:
                        result = result[int(part)] if isinstance(result, list) else result[part]
                    except (KeyError, IndexError, ValueError, TypeError) as exc:
                        raise WorkflowError(f"Reference path not found: {reference}") from exc
            return result
        return {key: _resolve(item, outputs) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve(item, outputs) for item in value]
    return value


class WorkflowStore:
    """SQLite-backed workflow definitions, checkpoints and append-only events."""

    def __init__(self, database: str | Path) -> None:
        self.database = str(Path(database).expanduser().resolve())
        Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS workflow_runs (
                    run_id TEXT PRIMARY KEY, definition_json TEXT NOT NULL,
                    status TEXT NOT NULL, cancel_requested INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workflow_steps (
                    run_id TEXT NOT NULL, step_id TEXT NOT NULL, tool_name TEXT NOT NULL,
                    arguments_json TEXT NOT NULL, depends_json TEXT NOT NULL,
                    max_attempts INTEGER NOT NULL, retry_delay REAL NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL,
                    output_json TEXT, error TEXT, next_attempt_at REAL NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL, PRIMARY KEY(run_id, step_id),
                    FOREIGN KEY(run_id) REFERENCES workflow_runs(run_id)
                );
                CREATE TABLE IF NOT EXISTS workflow_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                    step_id TEXT, event TEXT NOT NULL, detail_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_workflow_steps_status
                    ON workflow_steps(run_id, status, next_attempt_at);
                CREATE INDEX IF NOT EXISTS idx_workflow_events_run
                    ON workflow_events(run_id, sequence);
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.database, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _event(self, db: sqlite3.Connection, run_id: str, event: str,
               step_id: str | None = None, detail: Mapping[str, Any] | None = None) -> None:
        db.execute(
            "INSERT INTO workflow_events(run_id,step_id,event,detail_json,created_at) "
            "VALUES (?,?,?,?,?)",
            (run_id, step_id, event, json.dumps(dict(detail or {}), default=str), time.time()),
        )

    def create(self, steps: Sequence[WorkflowStep], run_id: str) -> str:
        definition = [asdict(step) for step in steps]
        now = time.time()
        with self._connect() as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "INSERT INTO workflow_runs(run_id,definition_json,status,created_at,updated_at) "
                    "VALUES (?,?, 'queued',?,?)",
                    (run_id, json.dumps(definition, ensure_ascii=False), now, now),
                )
                for step in steps:
                    db.execute(
                        """INSERT INTO workflow_steps
                        (run_id,step_id,tool_name,arguments_json,depends_json,max_attempts,
                         retry_delay,status,updated_at)
                        VALUES (?,?,?,?,?,?,?,'pending',?)""",
                        (run_id, step.step_id, step.tool_name,
                         json.dumps(dict(step.arguments), ensure_ascii=False),
                         json.dumps(step.depends_on), step.max_attempts,
                         step.retry_delay_seconds, now),
                    )
                self._event(db, run_id, "created", detail={"step_count": len(steps)})
            except sqlite3.IntegrityError as exc:
                raise WorkflowError(f"Workflow run already exists: {run_id}") from exc
        return run_id

    def snapshot(self, run_id: str) -> dict[str, Any]:
        with self._connect() as db:
            run = db.execute("SELECT * FROM workflow_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise WorkflowError(f"Workflow run not found: {run_id}")
            rows = db.execute(
                "SELECT * FROM workflow_steps WHERE run_id=? ORDER BY rowid", (run_id,)
            ).fetchall()
        return {
            "run_id": run_id, "status": run["status"],
            "cancel_requested": bool(run["cancel_requested"]),
            "created_at": run["created_at"], "updated_at": run["updated_at"],
            "steps": {
                row["step_id"]: {
                    "tool_name": row["tool_name"], "status": row["status"],
                    "attempts": row["attempts"], "output": json.loads(row["output_json"])
                    if row["output_json"] is not None else None,
                    "error": row["error"], "next_attempt_at": row["next_attempt_at"],
                } for row in rows
            },
        }

    def events(self, run_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
        if not 1 <= limit <= 5000:
            raise ValueError("event limit must be between 1 and 5000")
        with self._connect() as db:
            rows = db.execute(
                "SELECT sequence,step_id,event,detail_json,created_at FROM workflow_events "
                "WHERE run_id=? ORDER BY sequence LIMIT ?", (run_id, limit)
            ).fetchall()
        return [{"sequence": row["sequence"], "step_id": row["step_id"],
                 "event": row["event"], "detail": json.loads(row["detail_json"]),
                 "created_at": row["created_at"]} for row in rows]

    def cancel(self, run_id: str) -> None:
        with self._connect() as db:
            cur = db.execute(
                "UPDATE workflow_runs SET cancel_requested=1,updated_at=? WHERE run_id=?",
                (time.time(), run_id),
            )
            if cur.rowcount != 1:
                raise WorkflowError(f"Workflow run not found: {run_id}")
            self._event(db, run_id, "cancellation_requested")

    def mark(self, run_id: str, step_id: str, status: str, *,
             attempts: int | None = None, output: Any = None, error: str | None = None,
             next_attempt_at: float = 0) -> None:
        now = time.time()
        with self._connect() as db:
            if attempts is None:
                db.execute(
                    """UPDATE workflow_steps SET status=?,output_json=?,error=?,
                       next_attempt_at=?,updated_at=? WHERE run_id=? AND step_id=?""",
                    (status, json.dumps(output, ensure_ascii=False, default=str)
                     if output is not None else None, error, next_attempt_at,
                     now, run_id, step_id),
                )
            else:
                db.execute(
                    """UPDATE workflow_steps SET status=?,attempts=?,output_json=?,error=?,
                       next_attempt_at=?,updated_at=? WHERE run_id=? AND step_id=?""",
                    (status, attempts, json.dumps(output, ensure_ascii=False, default=str)
                     if output is not None else None, error, next_attempt_at,
                     now, run_id, step_id),
                )
            self._event(db, run_id, status, step_id,
                        {"attempts": attempts, "error": error})

    def set_run_status(self, run_id: str, status: str) -> None:
        now = time.time()
        with self._connect() as db:
            db.execute("UPDATE workflow_runs SET status=?,updated_at=? WHERE run_id=?",
                       (status, now, run_id))
            self._event(db, run_id, "run_" + status)


class WorkflowEngine:
    """Execute bounded DAGs with SQLite checkpoints, retry and cooperative cancellation."""

    TERMINAL: ClassVar[frozenset[str]] = frozenset(\n        {"succeeded", "failed", "skipped", "cancelled"}\n    )

    def __init__(self, dispatcher: ToolDispatcher, database: str | Path = "./ultk_workflows.sqlite3",
                 *, max_steps: int = 100, max_concurrency: int = 4) -> None:
        if not 1 <= max_steps <= 500 or not 1 <= max_concurrency <= 64:
            raise ValueError("Workflow limits must be max_steps 1..500 and concurrency 1..64.")
        self.dispatcher = dispatcher
        self.store = WorkflowStore(database)
        self.max_steps = max_steps
        self.max_concurrency = max_concurrency

    @staticmethod
    def validate(steps: Sequence[WorkflowStep]) -> None:
        if not steps:
            raise WorkflowError("A workflow requires at least one step.")
        ids: dict[str, WorkflowStep] = {}
        for step in steps:
            if (not step.step_id or len(step.step_id) > 100 or step.step_id in ids
                    or not step.tool_name or not isinstance(step.arguments, Mapping)):
                raise WorkflowError("Step IDs must be unique and each step needs a tool and object arguments.")
            if not 1 <= step.max_attempts <= 10 or not 0 <= step.retry_delay_seconds <= 300:
                raise WorkflowError("Retries must be 1..10 and retry delay 0..300 seconds.")
            ids[step.step_id] = step
        for step in steps:
            if len(set(step.depends_on)) != len(step.depends_on):
                raise WorkflowError(f"Duplicate dependencies in step {step.step_id}.")
            if step.step_id in step.depends_on or any(dep not in ids for dep in step.depends_on):
                raise WorkflowError(f"Unknown or self dependency in step {step.step_id}.")
        visiting: set[str] = set()
        visited: set[str] = set()
        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise WorkflowError("Workflow dependency graph contains a cycle.")
            if step_id in visited:
                return
            visiting.add(step_id)
            for dep in ids[step_id].depends_on:
                visit(dep)
            visiting.remove(step_id)
            visited.add(step_id)
        for step_id in ids:
            visit(step_id)
        def ancestors(step_id: str) -> set[str]:
            result: set[str] = set()
            for dep in ids[step_id].depends_on:
                result.add(dep)
                result.update(ancestors(dep))
            return result
        for step in steps:
            for ref in _refs(dict(step.arguments)):
                if ref not in ancestors(step.step_id):
                    raise WorkflowError(f"Referenced step '{ref}' must be an ancestor of '{step.step_id}'.")
        if len(steps) > 500:
            raise WorkflowError("Workflow exceeds the absolute 500-step limit.")

    def submit(self, steps: Sequence[WorkflowStep], *, run_id: str | None = None) -> str:
        self.validate(steps)
        if len(steps) > self.max_steps:
            raise WorkflowError(f"Workflow exceeds configured limit of {self.max_steps} steps.")
        return self.store.create(steps, run_id or uuid.uuid4().hex)

    async def run(self, run_id: str, *, session_id: str = "default",
                  granted_capabilities: frozenset[str] = frozenset(),
                  fail_fast: bool = False) -> dict[str, Any]:
        snapshot = self.store.snapshot(run_id)
        if snapshot["status"] in {"succeeded", "failed", "cancelled"}:
            return snapshot
        self.store.set_run_status(run_id, "running")
        semaphore = asyncio.Semaphore(self.max_concurrency)
        while True:
            snapshot = self.store.snapshot(run_id)
            if snapshot["cancel_requested"]:
                for sid, step in snapshot["steps"].items():
                    if step["status"] in {"pending", "running", "retry_wait"}:
                        self.store.mark(run_id, sid, "cancelled", error="Workflow cancellation requested.")
                self.store.set_run_status(run_id, "cancelled")
                return self.store.snapshot(run_id)
            states = snapshot["steps"]
            if all(item["status"] in self.TERMINAL for item in states.values()):
                status = "failed" if any(item["status"] in {"failed", "skipped"} for item in states.values()) else "succeeded"
                self.store.set_run_status(run_id, status)
                return self.store.snapshot(run_id)
            ready: list[str] = []
            for sid, item in states.items():
                if item["status"] not in {"pending", "retry_wait"} or item["next_attempt_at"] > time.time():
                    continue
                rowdeps = self._dependencies(run_id, sid)
                depstates = [states[d]["status"] for d in rowdeps]
                if any(s in {"failed", "skipped", "cancelled"} for s in depstates):
                    self.store.mark(run_id, sid, "skipped", error="A dependency did not succeed.")
                elif all(s == "succeeded" for s in depstates):
                    ready.append(sid)
            if not ready:
                snapshot = self.store.snapshot(run_id)
                if all(item["status"] in self.TERMINAL for item in snapshot["steps"].values()):
                    continue
                retry_times = [item["next_attempt_at"] for item in snapshot["steps"].values()
                               if item["status"] == "retry_wait"]
                if retry_times:
                    await asyncio.sleep(max(0.05, min(1.0, min(retry_times) - time.time())))
                    continue
                # Running steps from an interrupted process are recoverable by resume().
                if any(item["status"] == "running" for item in snapshot["steps"].values()):
                    raise WorkflowError("Workflow has in-flight steps; call recover() before resuming.")
                raise WorkflowError("Workflow cannot progress; inspect its dependency checkpoints.")
            ready = ready[:self.max_concurrency]

            async def execute(sid: str) -> tuple[str, ToolResult]:
                item = states[sid]
                args = _resolve(json.loads(self._step_arguments(run_id, sid)), {
                    key: value["output"] for key, value in states.items()
                    if value["status"] == "succeeded"
                })
                attempts = item["attempts"] + 1
                self.store.mark(run_id, sid, "running", attempts=attempts)
                async with semaphore:
                    result = await self.dispatcher.execute(
                        ToolCallRequest(uuid.uuid4().hex, item["tool_name"], args),
                        session_id=session_id, granted_capabilities=granted_capabilities)
                if result.is_error:
                    max_attempts, delay = self._retry_config(run_id, sid)
                    if attempts < max_attempts and not result.metadata.get("approval_required"):
                        wait = min(300.0, delay * (2 ** (attempts - 1)))
                        self.store.mark(run_id, sid, "retry_wait", attempts=attempts,
                                        error=result.content, next_attempt_at=time.time() + wait)
                    else:
                        self.store.mark(run_id, sid, "failed", attempts=attempts, error=result.content)
                else:
                    try:
                        output = json.loads(result.content)
                    except json.JSONDecodeError:
                        output = result.content
                    self.store.mark(run_id, sid, "succeeded", attempts=attempts, output=output)
                return sid, result

            outcomes = await asyncio.gather(*(execute(sid) for sid in ready))
            if fail_fast and any(result.is_error for _, result in outcomes):
                for sid, item in self.store.snapshot(run_id)["steps"].items():
                    if item["status"] in {"pending", "retry_wait"}:
                        self.store.mark(run_id, sid, "cancelled", error="Stopped after step failure.")
                self.store.set_run_status(run_id, "failed")
                return self.store.snapshot(run_id)

    def _step_arguments(self, run_id: str, step_id: str) -> str:
        with self.store._connect() as db:
            row = db.execute("SELECT arguments_json FROM workflow_steps WHERE run_id=? AND step_id=?",
                             (run_id, step_id)).fetchone()
        if row is None:
            raise WorkflowError(f"Unknown workflow step: {step_id}")
        return str(row["arguments_json"])

    def _dependencies(self, run_id: str, step_id: str) -> list[str]:
        with self.store._connect() as db:
            row = db.execute("SELECT depends_json FROM workflow_steps WHERE run_id=? AND step_id=?",
                             (run_id, step_id)).fetchone()
        if row is None:
            raise WorkflowError(f"Unknown workflow step: {step_id}")
        return json.loads(row["depends_json"])

    def _retry_config(self, run_id: str, step_id: str) -> tuple[int, float]:
        with self.store._connect() as db:
            row = db.execute("SELECT max_attempts,retry_delay FROM workflow_steps WHERE run_id=? AND step_id=?",
                             (run_id, step_id)).fetchone()
        return int(row["max_attempts"]), float(row["retry_delay"])

    def recover(self, run_id: str) -> dict[str, Any]:
        """Reset orphaned in-flight steps to pending; recovery is at-least-once."""
        snapshot = self.store.snapshot(run_id)
        for sid, item in snapshot["steps"].items():
            if item["status"] == "running":
                self.store.mark(run_id, sid, "pending",
                                error="Recovered after interrupted execution; previous side effect may have occurred.")
        self.store.set_run_status(run_id, "queued")
        return self.store.snapshot(run_id)

    def cancel(self, run_id: str) -> None:
        self.store.cancel(run_id)

    def get(self, run_id: str) -> dict[str, Any]:
        return self.store.snapshot(run_id)

    def get_events(self, run_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
        return self.store.events(run_id, limit=limit)


    def replay(self, run_id: str, *, new_run_id: str | None = None) -> str:
        """Create a fresh run from the original definition; this re-executes tools."""
        with self.store._connect() as db:
            row = db.execute(
                "SELECT definition_json FROM workflow_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        if row is None:
            raise WorkflowError(f"Workflow run not found: {run_id}")
        definition = json.loads(row["definition_json"])
        steps = [WorkflowStep(
            step_id=item["step_id"], tool_name=item["tool_name"],
            arguments=item["arguments"], depends_on=tuple(item["depends_on"]),
            max_attempts=item["max_attempts"],
            retry_delay_seconds=item["retry_delay_seconds"],
        ) for item in definition]
        return self.submit(steps, run_id=new_run_id)

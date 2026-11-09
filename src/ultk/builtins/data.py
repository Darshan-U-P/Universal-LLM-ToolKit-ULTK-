"""Bounded CSV/JSON file and SQLite database tools."""

from __future__ import annotations

import csv
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ultk.builtins._common import FunctionTool, object_schema
from ultk.exceptions import ToolExecutionError


def _rooted_path(root: Path, relative_path: str) -> Path:
    if not relative_path or len(relative_path) > 500:
        raise ToolExecutionError("A relative file path of at most 500 characters is required.")
    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise ToolExecutionError("Absolute paths are not allowed.")
    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root):
        raise ToolExecutionError("Path escapes the configured data root.")
    return resolved


def _atomic_write(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=target.parent, prefix=".ultk-data-", delete=False
        ) as handle:
            handle.write(data)
            temporary_path = handle.name
        os.replace(temporary_path, target)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)


def _read_json(root: Path, relative_path: str, max_bytes: int) -> dict[str, Any]:
    path = _rooted_path(root, relative_path)
    if not path.is_file():
        raise ToolExecutionError("JSON file does not exist.")
    if path.stat().st_size > max_bytes:
        raise ToolExecutionError("JSON file exceeds the configured size limit.")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ToolExecutionError("File is not valid UTF-8 JSON.") from exc
    return {"path": relative_path, "value": value}


def _write_json(root: Path, relative_path: str, value: Any, max_bytes: int) -> dict[str, Any]:
    path = _rooted_path(root, relative_path)
    try:
        data = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ToolExecutionError("Value is not valid JSON data.") from exc
    if len(data) > max_bytes:
        raise ToolExecutionError("Serialized JSON exceeds the configured size limit.")
    _atomic_write(path, data)
    return {"path": relative_path, "bytes_written": len(data)}


def _read_csv(root: Path, relative_path: str, max_bytes: int,
              max_rows: int) -> dict[str, Any]:
    path = _rooted_path(root, relative_path)
    if not path.is_file():
        raise ToolExecutionError("CSV file does not exist.")
    if path.stat().st_size > max_bytes:
        raise ToolExecutionError("CSV file exceeds the configured size limit.")
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise ToolExecutionError("CSV file has no header row.")
            rows = []
            for index, row in enumerate(reader):
                if index >= max_rows:
                    raise ToolExecutionError("CSV row count exceeds the configured limit.")
                rows.append(dict(row))
    except UnicodeDecodeError as exc:
        raise ToolExecutionError("CSV file must use UTF-8 encoding.") from exc
    return {"path": relative_path, "columns": reader.fieldnames, "rows": rows,
            "row_count": len(rows)}


def _write_csv(root: Path, relative_path: str, columns: list[str],
               rows: list[dict[str, Any]], max_bytes: int,
               max_rows: int) -> dict[str, Any]:
    if not columns or len(columns) > 500 or len(set(columns)) != len(columns):
        raise ToolExecutionError("CSV columns must be unique and contain 1–500 names.")
    if len(rows) > max_rows:
        raise ToolExecutionError("CSV row count exceeds the configured limit.")
    if any(not isinstance(row, dict) or set(row) - set(columns) for row in rows):
        raise ToolExecutionError("Every CSV row must be an object with only configured columns.")
    import io

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="raise")
    writer.writeheader()
    writer.writerows(rows)
    data = buffer.getvalue().encode("utf-8")
    if len(data) > max_bytes:
        raise ToolExecutionError("Serialized CSV exceeds the configured size limit.")
    path = _rooted_path(root, relative_path)
    _atomic_write(path, data)
    return {"path": relative_path, "row_count": len(rows), "bytes_written": len(data)}


class SQLiteDataStore:
    """Read-only SQLite queries by default; optional DML is explicitly enabled."""

    _READ_ACTIONS = {
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_FUNCTION,
        getattr(sqlite3, "SQLITE_RECURSIVE", -1),
    }
    _WRITE_ACTIONS = _READ_ACTIONS | {
        sqlite3.SQLITE_INSERT,
        sqlite3.SQLITE_UPDATE,
        sqlite3.SQLITE_DELETE,
        sqlite3.SQLITE_TRANSACTION,
    }

    def __init__(self, database: str | Path, *, allow_writes: bool = False,
                 max_rows: int = 1000) -> None:
        self.database = Path(database).expanduser().resolve()
        self.allow_writes = allow_writes
        self.max_rows = max_rows
        if max_rows < 1 or max_rows > 10000:
            raise ValueError("max_rows must be between 1 and 10000.")

    def _connect(self, *, readonly: bool) -> sqlite3.Connection:
        if readonly and not self.database.is_file():
            raise ToolExecutionError("Configured SQLite database does not exist.")
        if not readonly:
            self.database.parent.mkdir(parents=True, exist_ok=True)
        uri_path = quote(str(self.database), safe="/:")
        mode = "ro" if readonly else "rwc"
        connection = sqlite3.connect(
            f"file:{uri_path}?mode={mode}", uri=True, timeout=5
        )
        connection.row_factory = sqlite3.Row
        allowed = self._READ_ACTIONS if readonly else self._WRITE_ACTIONS

        def authorize(action: int, arg1: str | None, arg2: str | None,
                      database_name: str | None, trigger_name: str | None) -> int:
            if action not in allowed:
                return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_FUNCTION and (arg2 or arg1 or "").casefold() == "load_extension":
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(authorize)
        return connection

    @staticmethod
    def _validate_sql(sql: str, parameters: list[Any]) -> None:
        if not sql.strip() or len(sql) > 10000:
            raise ToolExecutionError("SQL must contain 1–10000 characters.")
        if not isinstance(parameters, list) or len(parameters) > 1000:
            raise ToolExecutionError("SQL parameters must be a list of at most 1000 values.")
        allowed_types = (str, int, float, bool, type(None), bytes)
        if any(not isinstance(value, allowed_types) for value in parameters):
            raise ToolExecutionError("SQL parameters must be scalar SQLite values.")

    def _query(self, sql: str, parameters: list[Any]) -> dict[str, Any]:
        self._validate_sql(sql, parameters)
        connection = self._connect(readonly=True)
        try:
            cursor = connection.execute(sql, parameters)
            rows = cursor.fetchmany(self.max_rows + 1)
            if len(rows) > self.max_rows:
                raise ToolExecutionError("Query result exceeds the configured row limit.")
            columns = [item[0] for item in (cursor.description or [])]
            normalized = [
                {key: (value.hex() if isinstance(value, bytes) else value)
                 for key, value in zip(columns, tuple(row), strict=True)}
                for row in rows
            ]
            return {"columns": columns, "rows": normalized, "row_count": len(normalized)}
        finally:
            connection.close()

    def _schema(self) -> dict[str, Any]:
        connection = self._connect(readonly=True)
        try:
            rows = connection.execute(
                """SELECT name, type, sql FROM sqlite_master
                   WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'
                   ORDER BY type, name"""
            ).fetchall()
            return {"objects": [dict(row) for row in rows]}
        finally:
            connection.close()

    def _write(self, sql: str, parameters: list[Any]) -> dict[str, Any]:
        if not self.allow_writes:
            raise ToolExecutionError("Database writes were not enabled by the host.")
        self._validate_sql(sql, parameters)
        connection = self._connect(readonly=False)
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(sql, parameters)
            rows = cursor.fetchmany(self.max_rows + 1) if cursor.description else []
            if len(rows) > self.max_rows:
                raise ToolExecutionError("Write RETURNING result exceeds the configured row limit.")
            columns = [item[0] for item in (cursor.description or [])]
            normalized = [
                {key: (value.hex() if isinstance(value, bytes) else value)
                 for key, value in zip(columns, tuple(row), strict=True)}
                for row in rows
            ]
            row_count = cursor.rowcount
            last_row_id = cursor.lastrowid
            connection.commit()
            return {"row_count": row_count, "last_row_id": last_row_id,
                    "columns": columns, "rows": normalized}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def create_data_tools(*, root_dir: str | Path,
                      sqlite_database: str | Path | None = None,
                      allow_database_writes: bool = False,
                      max_file_bytes: int = 5_000_000,
                      max_rows: int = 1000) -> tuple[FunctionTool, ...]:
    root = Path(root_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if max_file_bytes < 1 or max_file_bytes > 50_000_000:
        raise ValueError("max_file_bytes must be between 1 and 50 MB.")
    if max_rows < 1 or max_rows > 10000:
        raise ValueError("max_rows must be between 1 and 10000.")
    tools: list[FunctionTool] = [
        FunctionTool(
            "data.json_read", "Read a bounded UTF-8 JSON file under the configured data root.",
            object_schema({"path": {"type": "string", "minLength": 1, "maxLength": 500}},
                          ["path"]),
            "data:file:read",
            lambda path: _read_json(root, path, max_file_bytes),
        ),
        FunctionTool(
            "data.json_write", "Atomically write JSON under the configured data root.",
            object_schema({"path": {"type": "string", "minLength": 1, "maxLength": 500},
                           "value": {}}, ["path", "value"]),
            "data:file:write",
            lambda path, value: _write_json(root, path, value, max_file_bytes),
        ),
        FunctionTool(
            "data.csv_read", "Read a bounded UTF-8 CSV file as column names and row objects.",
            object_schema({"path": {"type": "string", "minLength": 1, "maxLength": 500}},
                          ["path"]),
            "data:file:read",
            lambda path: _read_csv(root, path, max_file_bytes, max_rows),
        ),
        FunctionTool(
            "data.csv_write", "Atomically write CSV rows under the configured data root.",
            object_schema({
                "path": {"type": "string", "minLength": 1, "maxLength": 500},
                "columns": {"type": "array", "items": {"type": "string"},
                            "minItems": 1, "maxItems": 500},
                "rows": {"type": "array", "items": {"type": "object"},
                         "maxItems": max_rows},
            }, ["path", "columns", "rows"]),
            "data:file:write",
            lambda path, columns, rows: _write_csv(
                root, path, columns, rows, max_file_bytes, max_rows),
        ),
    ]
    if sqlite_database is not None:
        store = SQLiteDataStore(
            sqlite_database, allow_writes=allow_database_writes, max_rows=max_rows
        )
        tools.extend([
            FunctionTool(
                "database.query",
                "Run a read-only parameterized SQLite query; schema changes and writes are denied.",
                object_schema({
                    "sql": {"type": "string", "minLength": 1, "maxLength": 10000},
                    "parameters": {"type": "array", "maxItems": 1000,
                                   "items": {"type": ["string", "integer", "number",
                                                     "boolean", "null"]}},
                }, ["sql"]),
                "database:read",
                lambda sql, parameters=None: store._query(sql, parameters or []),
            ),
            FunctionTool(
                "database.get_schema", "List SQLite tables and views with their definitions.",
                object_schema({}), "database:read", store._schema,
            ),
        ])
        if allow_database_writes:
            tools.append(FunctionTool(
                "database.execute_write",
                "Execute one parameterized SQLite INSERT, UPDATE or DELETE statement.",
                object_schema({
                    "sql": {"type": "string", "minLength": 1, "maxLength": 10000},
                    "parameters": {"type": "array", "maxItems": 1000,
                                   "items": {"type": ["string", "integer", "number",
                                                     "boolean", "null"]}},
                }, ["sql"]),
                "database:write",
                lambda sql, parameters=None: store._write(sql, parameters or []),
            ))
    return tuple(tools)

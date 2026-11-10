from __future__ import annotations

import sqlite3

import pytest

from ultk.builtins.data import (
    SQLiteDataStore,
    _read_csv,
    _read_json,
    _write_csv,
    _write_json,
)
from ultk.engine import ToolEngine
from ultk.exceptions import ToolExecutionError
from ultk.permissions import AllowListPolicy


def test_json_and_csv_files_round_trip_within_root(tmp_path) -> None:
    _write_json(tmp_path, "records/data.json", {"ok": True, "items": [1, 2]}, 10000)
    assert _read_json(tmp_path, "records/data.json", 10000)["value"]["items"] == [1, 2]

    _write_csv(
        tmp_path, "records/data.csv", ["id", "label"],
        [{"id": 1, "label": "alpha"}, {"id": 2, "label": "beta"}],
        10000, 10,
    )
    result = _read_csv(tmp_path, "records/data.csv", 10000, 10)
    assert result["columns"] == ["id", "label"]
    assert result["row_count"] == 2


def test_data_files_reject_path_traversal(tmp_path) -> None:
    with pytest.raises(ToolExecutionError, match="Absolute paths|escapes"):
        _write_json(tmp_path, "../outside.json", {"unsafe": True}, 10000)


def test_sqlite_query_is_read_only_and_parameterized(tmp_path) -> None:
    database = tmp_path / "app.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, label TEXT)")
        connection.execute("INSERT INTO items(label) VALUES ('alpha')")
    store = SQLiteDataStore(database)
    result = store._query("SELECT id, label FROM items WHERE id = ?", [1])
    assert result["rows"] == [{"id": 1, "label": "alpha"}]
    with pytest.raises(ToolExecutionError):
        store._query("DELETE FROM items WHERE id = ?", [1])
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1


def test_sqlite_write_requires_host_opt_in_and_allows_only_dml(tmp_path) -> None:
    database = tmp_path / "app.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, label TEXT)")
    readonly = SQLiteDataStore(database, allow_writes=False)
    with pytest.raises(Exception, match="not enabled"):
        readonly._write("INSERT INTO items(label) VALUES (?)", ["alpha"])

    writable = SQLiteDataStore(database, allow_writes=True)
    result = writable._write("INSERT INTO items(label) VALUES (?)", ["alpha"])
    assert result["row_count"] == 1
    with pytest.raises(ToolExecutionError):
        writable._write("DROP TABLE items", [])
    assert writable._schema()["objects"][0]["name"] == "items"


def test_data_tools_install_database_writes_only_when_explicit(tmp_path) -> None:
    engine = ToolEngine(policy=AllowListPolicy({"data.csv_read", "database.query"}))
    engine.install_data_tools(root_dir=tmp_path / "data", sqlite_database=tmp_path / "db.sqlite3")
    names = {tool.spec.name for tool in engine.registry.list()}
    assert "data.csv_read" in names
    assert "database.query" in names
    assert "database.execute_write" not in names

    writable = ToolEngine(policy=AllowListPolicy({"database.execute_write"}))
    writable.install_data_tools(
        root_dir=tmp_path / "writable-data",
        sqlite_database=tmp_path / "writable.sqlite3",
        allow_database_writes=True,
    )
    writable_names = {tool.spec.name for tool in writable.registry.list()}
    assert "database.execute_write" in writable_names

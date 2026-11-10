from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ultk.builtins.database import DatabasePack, create_database_tools
from ultk.engine import ToolEngine
from ultk.exceptions import ToolExecutionError
from ultk.permissions import AllowListPolicy


def make_pack(tmp_path: Path) -> DatabasePack:
    path = tmp_path / "test.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, active INTEGER)")
        db.execute("INSERT INTO users(name, active) VALUES ('Ada', 1), ('Lin', 0)")
    return DatabasePack({"local": {"backend": "sqlite", "path": str(path)}},
                        max_rows=50, max_result_bytes=10000, max_batch=10)


def test_sqlite_discovery_select_and_parameter_binding(tmp_path: Path) -> None:
    pack = make_pack(tmp_path)
    assert pack.sql_tables("local")["tables"][0]["name"] == "users"
    columns = pack.sql_describe("local", "users")["columns"]
    assert {c["name"] for c in columns} >= {"id", "name", "active"}
    result = pack.sql_select("local", "users", filters=[
        {"field": "name", "operator": "eq", "value": "Ada' OR 1=1 --"}
    ])
    assert result["count"] == 0
    assert pack.sql_select("local", "users")["count"] == 2


def test_sqlite_insert_update_delete_require_filters(tmp_path: Path) -> None:
    pack = make_pack(tmp_path)
    pack.sql_insert("local", "users", {"name": "Grace", "active": 1})
    assert pack.sql_select("local", "users")["count"] == 3
    with pytest.raises(ToolExecutionError, match="filter"):
        pack.sql_update("local", "users", {"active": 0}, [])
    with pytest.raises(ToolExecutionError, match="filters"):
        pack.sql_delete("local", "users", [])
    pack.sql_update("local", "users", {"active": 0},
                    [{"field": "name", "operator": "eq", "value": "Grace"}])
    assert pack.sql_select("local", "users", filters=[
        {"field": "active", "operator": "eq", "value": 0}
    ])["count"] == 2
    pack.sql_delete("local", "users", [{"field": "name", "operator": "eq", "value": "Grace"}])
    assert pack.sql_select("local", "users")["count"] == 2


def test_sqlite_transaction_commits_and_rolls_back(tmp_path: Path) -> None:
    pack = make_pack(tmp_path)
    result = pack.sql_transaction("local", [
        {"operation": "insert", "table": "users", "values": {"name": "Katherine", "active": 1}},
        {"operation": "update", "table": "users", "values": {"active": 0},
         "filters": [{"field": "name", "value": "Ada"}]},
    ])
    assert result["committed"] is True
    assert pack.sql_select("local", "users")["count"] == 3
    with pytest.raises(ToolExecutionError):
        pack.sql_transaction("local", [
            {"operation": "insert", "table": "users", "values": {"name": "Rolled back", "active": 1}},
            {"operation": "delete", "table": "users", "filters": []},
        ])
    assert pack.sql_select("local", "users")["count"] == 3


def test_sql_identifier_and_filter_validation(tmp_path: Path) -> None:
    pack = make_pack(tmp_path)
    with pytest.raises(ToolExecutionError, match="Identifiers"):
        pack.sql_select("local", "users; DROP TABLE users")
    with pytest.raises(ToolExecutionError, match="operator"):
        pack.sql_select("local", "users", filters=[
            {"field": "name", "operator": "raw_sql", "value": "1=1"}
        ])


def test_mongodb_filter_rejects_code_execution_operators() -> None:
    with pytest.raises(ToolExecutionError, match="disallowed"):
        DatabasePack._mongo_filter({"$where": "this.password"})
    with pytest.raises(ToolExecutionError, match="disallowed"):
        DatabasePack._mongo_filter({"name": {"$regex": ".*"}})
    assert DatabasePack._mongo_filter({"$and": [{"age": {"$gte": 18}}]})


def test_profiles_are_host_configured_and_backend_scoped(tmp_path: Path) -> None:
    pack = make_pack(tmp_path)
    with pytest.raises(ToolExecutionError, match="Unknown profile"):
        pack.sql_tables("model_supplied_dsn")
    with pytest.raises(ToolExecutionError, match="incompatible"):
        pack._cfg("local", "mongodb")


def test_installer_registers_only_configured_backends(tmp_path: Path) -> None:
    engine = ToolEngine(policy=AllowListPolicy({
        "database:schema:read", "database:read", "database:write",
        "database:delete", "database:transaction",
    }))
    engine.install_database_tools({
        "local": {"backend": "sqlite", "path": str(tmp_path / "db.sqlite3")},
        "cache": {"backend": "redis", "url": "redis://localhost:6379/0", "key_prefix": "ultk:"},
        "documents": {"backend": "mongodb", "uri": "mongodb://localhost:27017", "database": "test"},
    })
    names = {tool.spec.name for tool in engine.registry.list()}
    assert "database.sql_select" in names
    assert "database.mongo_find" in names
    assert "database.mongo_transaction" in names
    assert "database.redis_set" in names
    assert "database.sql_transaction" in names
    assert all("mysql" not in name and "postgres" not in name for name in names)


def test_factory_exports_public_database_pack(tmp_path: Path) -> None:
    tools = create_database_tools({
        "db": {"backend": "sqlite", "path": str(tmp_path / "db.sqlite3")}
    })
    assert {tool.spec.name for tool in tools} >= {
        "database.sql_list_tables", "database.sql_select", "database.sql_insert",
        "database.sql_update", "database.sql_delete", "database.sql_transaction",
    }
    assert next(t for t in tools if t.spec.name == "database.sql_delete").spec.capabilities == frozenset({"database:delete"})

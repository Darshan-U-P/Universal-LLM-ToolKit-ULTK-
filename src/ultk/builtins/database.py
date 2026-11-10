"""Host-configured SQL, MongoDB and Redis integration tools.

Credentials and connection parameters are trusted host configuration. Model calls select
a named profile; they cannot provide DSNs, credentials, arbitrary SQL or executable code.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from ultk.builtins._common import FunctionTool, object_schema
from ultk.exceptions import ToolExecutionError

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_OPS = {"eq": "=", "ne": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}


def _ident(value: str) -> str:
    if not isinstance(value, str) or not _IDENT.fullmatch(value):
        raise ToolExecutionError("Identifiers must be simple alphanumeric names.")
    return value


def _safe(value: Any, depth: int = 0) -> Any:
    if depth > 16:
        raise ToolExecutionError("Database result nesting exceeds the limit.")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ToolExecutionError("Non-finite numbers are not supported.")
        return value
    if isinstance(value, (Decimal, date, datetime)):
        return str(value) if isinstance(value, Decimal) else value.isoformat()
    if isinstance(value, bytes):
        import base64
        return {"$binary_base64": base64.b64encode(value[:1_000_000]).decode("ascii")}
    if isinstance(value, (list, tuple)):
        if len(value) > 1000:
            raise ToolExecutionError("Array result exceeds 1000 elements.")
        return [_safe(item, depth + 1) for item in value]
    if isinstance(value, dict):
        if len(value) > 1000 or not all(isinstance(k, str) for k in value):
            raise ToolExecutionError("Object result exceeds the key limit.")
        return {k: _safe(v, depth + 1) for k, v in value.items()}
    if hasattr(value, "binary"):
        return str(value)
    return str(value)


def _bounded(value: Any, limit: int) -> Any:
    value = _safe(value)
    if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > limit:
        raise ToolExecutionError("Database result exceeds the configured output byte limit.")
    return value


class DatabasePack:
    def __init__(self, profiles: dict[str, dict[str, Any]], max_rows: int,
                 max_result_bytes: int, max_batch: int) -> None:
        if not 1 <= len(profiles) <= 32:
            raise ValueError("Provide between 1 and 32 host-configured profiles.")
        self.profiles = {}
        for name, cfg in profiles.items():
            if not isinstance(name, str) or not _IDENT.fullmatch(name):
                raise ValueError("Profile names must be simple identifiers.")
            if not isinstance(cfg, dict) or cfg.get("backend") not in {
                "sqlite", "mysql", "postgresql", "mongodb", "redis"
            }:
                raise ValueError(f"Unsupported database profile: {name}")
            if cfg["backend"] == "redis" and (not isinstance(cfg.get("key_prefix"), str) or not cfg.get("key_prefix")):
                raise ValueError(f"Redis profile {name!r} requires a non-empty key_prefix.")
            if cfg["backend"] == "mongodb" and (not cfg.get("uri") or not cfg.get("database")):
                raise ValueError(f"MongoDB profile {name!r} requires host-configured uri and database.")
            self.profiles[name] = dict(cfg)
        self.max_rows, self.max_bytes, self.max_batch = max_rows, max_result_bytes, max_batch

    def _cfg(self, profile: str, backend: str | None = None) -> dict[str, Any]:
        cfg = self.profiles.get(profile)
        if cfg is None or (backend and cfg["backend"] != backend):
            raise ToolExecutionError("Unknown profile or incompatible database backend.")
        return cfg

    def _connect_sql(self, profile: str):
        cfg = self._cfg(profile)
        backend = cfg["backend"]
        if backend == "sqlite":
            path = cfg.get("path")
            if not isinstance(path, str) or not path:
                raise ToolExecutionError("SQLite profile requires a host-configured path.")
            target = Path(path).expanduser().resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(target), timeout=float(cfg.get("timeout", 10)))
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=10000")
            return conn, backend
        if backend == "mysql":
            try:
                import mysql.connector
            except ImportError as exc:
                raise ToolExecutionError("Install the database-mysql extra.") from exc
            allowed = {"host", "port", "user", "password", "database", "unix_socket",
                       "connection_timeout", "charset", "ssl_ca", "ssl_cert", "ssl_key"}
            opts = {k: v for k, v in cfg.items() if k in allowed}
            if not opts.get("database") or not (opts.get("host") or opts.get("unix_socket")):
                raise ToolExecutionError("MySQL profile requires host/socket and database.")
            return mysql.connector.connect(**opts), backend
        if backend == "postgresql":
            try:
                import psycopg
            except ImportError as exc:
                raise ToolExecutionError("Install the database-postgresql extra.") from exc
            allowed = {"host", "port", "dbname", "user", "password", "connect_timeout",
                       "sslmode", "sslrootcert", "sslcert", "sslkey", "application_name"}
            opts = {k: v for k, v in cfg.items() if k in allowed}
            if not opts.get("host") or not opts.get("dbname"):
                raise ToolExecutionError("PostgreSQL profile requires host and dbname.")
            return psycopg.connect(**opts), backend
        raise ToolExecutionError("Profile is not a SQL database.")

    def _run_sql(self, profile: str, sql: str, params: tuple[Any, ...] = (),
                 fetch: bool = False) -> tuple[list[dict[str, Any]], int]:
        conn, backend = self._connect_sql(profile)
        cur = None
        try:
            cur = conn.cursor()
            cur.execute(sql if backend == "sqlite" else sql.replace("?", "%s"), params)
            rows = []
            if fetch:
                names = [c[0] for c in (cur.description or [])]
                for row in cur.fetchmany(self.max_rows + 1):
                    if len(rows) >= self.max_rows:
                        raise ToolExecutionError("Query exceeded the configured row limit.")
                    rows.append(_safe(dict(row)) if isinstance(row, (dict, sqlite3.Row))
                                else {names[i]: _safe(v) for i, v in enumerate(row)})
            count = max(0, int(cur.rowcount or 0))
            if not fetch:
                conn.commit()
            return rows, count
        except Exception:
            conn.rollback()
            raise
        finally:
            if cur is not None:
                cur.close()
            conn.close()

    def _where(self, filters: list[dict[str, Any]] | None) -> tuple[str, list[Any]]:
        clauses, params = [], []
        for item in filters or []:
            field, op, value = _ident(item.get("field")), item.get("operator", "eq"), item.get("value")
            if op == "is_null":
                clauses.append(f"{field} IS NULL")
            elif op == "not_null":
                clauses.append(f"{field} IS NOT NULL")
            elif op == "in":
                if not isinstance(value, list) or not 1 <= len(value) <= 100:
                    raise ToolExecutionError("IN requires 1–100 values.")
                clauses.append(f"{field} IN ({','.join('?' for _ in value)})")
                params.extend(value)
            elif op in _OPS:
                clauses.append(f"{field} {_OPS[op]} ?")
                params.append(value)
            else:
                raise ToolExecutionError("Unsupported SQL filter operator.")
        return (" WHERE " + " AND ".join(clauses) if clauses else ""), params

    def sql_tables(self, profile: str) -> dict[str, Any]:
        backend = self._cfg(profile)["backend"]
        if backend == "sqlite":
            sql = "SELECT name, type FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name"
            rows, _ = self._run_sql(profile, sql, fetch=True)
        elif backend == "mysql":
            rows, _ = self._run_sql(profile, "SELECT table_name AS name, table_type AS type FROM information_schema.tables WHERE table_schema=DATABASE() ORDER BY table_name", fetch=True)
        elif backend == "postgresql":
            rows, _ = self._run_sql(profile, "SELECT table_name AS name, table_type AS type FROM information_schema.tables WHERE table_schema=current_schema() ORDER BY table_name", fetch=True)
        else:
            raise ToolExecutionError("Profile is not a SQL database.")
        return {"backend": backend, "tables": rows}

    def sql_describe(self, profile: str, table: str) -> dict[str, Any]:
        table = _ident(table)
        backend = self._cfg(profile)["backend"]
        if backend == "sqlite":
            rows, _ = self._run_sql(profile, f"PRAGMA table_info({table})", fetch=True)
        elif backend == "mysql":
            rows, _ = self._run_sql(profile, "SELECT column_name AS name,data_type AS type,is_nullable AS nullable,column_default AS default_value FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=? ORDER BY ordinal_position", (table,), True)
        elif backend == "postgresql":
            rows, _ = self._run_sql(profile, "SELECT column_name AS name,data_type AS type,is_nullable AS nullable,column_default AS default_value FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=? ORDER BY ordinal_position", (table,), True)
        else:
            raise ToolExecutionError("Profile is not a SQL database.")
        return {"table": table, "columns": rows}

    def sql_select(self, profile: str, table: str, columns: list[str] | None = None,
                   filters: list[dict[str, Any]] | None = None, order_by: str | None = None,
                   descending: bool = False, limit: int | None = None, offset: int = 0) -> dict[str, Any]:
        table = _ident(table)
        limit = min(100, self.max_rows) if limit is None else limit
        if not 1 <= limit <= self.max_rows or not 0 <= offset <= 1_000_000:
            raise ToolExecutionError("Select limit/offset outside configured bounds.")
        fields = "*" if not columns else ",".join(_ident(c) for c in columns)
        where, params = self._where(filters)
        order = f" ORDER BY {_ident(order_by)} {'DESC' if descending else 'ASC'}" if order_by else ""
        rows, _ = self._run_sql(profile, f"SELECT {fields} FROM {table}{where}{order} LIMIT ? OFFSET ?", tuple(params + [limit, offset]), True)
        return {"rows": _bounded(rows, self.max_bytes), "count": len(rows)}

    def sql_insert(self, profile: str, table: str, values: dict[str, Any]) -> dict[str, Any]:
        table = _ident(table)
        if not isinstance(values, dict) or not 1 <= len(values) <= 100:
            raise ToolExecutionError("Insert requires 1–100 values.")
        keys = [_ident(k) for k in values]
        _, count = self._run_sql(profile, f"INSERT INTO {table} ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})", tuple(values.values()))
        return {"rows_affected": count}

    def sql_update(self, profile: str, table: str, values: dict[str, Any],
                   filters: list[dict[str, Any]]) -> dict[str, Any]:
        table = _ident(table)
        if not filters or not isinstance(values, dict) or not 1 <= len(values) <= 100:
            raise ToolExecutionError("UPDATE requires values and at least one filter.")
        keys = [_ident(k) for k in values]
        where, params = self._where(filters)
        _, count = self._run_sql(profile, f"UPDATE {table} SET " + ",".join(f"{k}=?" for k in keys) + where, tuple(values.values()) + tuple(params))
        return {"rows_affected": count}

    def sql_delete(self, profile: str, table: str, filters: list[dict[str, Any]]) -> dict[str, Any]:
        table = _ident(table)
        where, params = self._where(filters)
        if not where:
            raise ToolExecutionError("DELETE without filters is refused.")
        _, count = self._run_sql(profile, f"DELETE FROM {table}{where}", tuple(params))
        return {"rows_affected": count}

    def sql_transaction(self, profile: str, operations: list[dict[str, Any]]) -> dict[str, Any]:
        if not 1 <= len(operations) <= self.max_batch:
            raise ToolExecutionError("Transaction operation count is outside configured bounds.")
        conn, backend = self._connect_sql(profile)
        cur, results = None, []
        try:
            cur = conn.cursor()
            for op in operations:
                kind, table = op.get("operation"), _ident(op.get("table"))
                if kind == "insert":
                    values = op.get("values")
                    if not isinstance(values, dict) or not 1 <= len(values) <= 100:
                        raise ToolExecutionError("Transaction insert requires 1–100 values.")
                    keys = [_ident(k) for k in values]
                    sql, params = f"INSERT INTO {table} ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})", tuple(values.values())
                elif kind in {"update", "delete"}:
                    where, where_params = self._where(op.get("filters"))
                    if not where:
                        raise ToolExecutionError("Transaction update/delete requires filters.")
                    if kind == "delete":
                        sql, params = f"DELETE FROM {table}{where}", tuple(where_params)
                    else:
                        values = op.get("values")
                        if not isinstance(values, dict) or not 1 <= len(values) <= 100:
                            raise ToolExecutionError("Transaction update requires 1–100 values.")
                        keys = [_ident(k) for k in values]
                        sql = f"UPDATE {table} SET " + ",".join(f"{k}=?" for k in keys) + where
                        params = tuple(values.values()) + tuple(where_params)
                else:
                    raise ToolExecutionError("Unsupported transaction operation.")
                cur.execute(sql if backend == "sqlite" else sql.replace("?", "%s"), params)
                results.append({"operation": kind, "rows_affected": max(0, int(cur.rowcount or 0))})
            conn.commit()
            return {"committed": True, "operations": results}
        except Exception:
            conn.rollback()
            raise
        finally:
            if cur is not None:
                cur.close()
            conn.close()

    @staticmethod
    def _mongo_filter(value: dict[str, Any]) -> dict[str, Any]:
        allowed = {"$and", "$or", "$in", "$nin", "$gt", "$gte", "$lt", "$lte", "$ne", "$eq", "$exists"}
        def check(item: Any, depth: int = 0) -> None:
            if depth > 8:
                raise ToolExecutionError("MongoDB filter nesting exceeds the limit.")
            if isinstance(item, dict):
                for key, child in item.items():
                    if key.startswith("$") and key not in allowed:
                        raise ToolExecutionError("MongoDB filter contains a disallowed operator.")
                    if key in {"$and", "$or"} and (not isinstance(child, list) or len(child) > 20):
                        raise ToolExecutionError("MongoDB logical filters require bounded arrays.")
                    check(child, depth + 1)
            elif isinstance(item, list):
                if len(item) > 100:
                    raise ToolExecutionError("MongoDB filter array exceeds the limit.")
                for child in item:
                    check(child, depth + 1)
        if not isinstance(value, dict):
            raise ToolExecutionError("MongoDB filter must be an object.")
        check(value)
        return value

    def mongo_collections(self, profile: str) -> dict[str, Any]:
        cfg = self._cfg(profile, "mongodb")
        try:
            from pymongo import MongoClient
        except ImportError as exc:
            raise ToolExecutionError("Install the database-mongodb extra.") from exc
        client = MongoClient(cfg["uri"], serverSelectionTimeoutMS=int(cfg.get("server_selection_timeout_ms", 5000)))
        try:
            return {"collections": sorted(client[cfg["database"]].list_collection_names())[:self.max_rows]}
        finally:
            client.close()

    def mongo_find(self, profile: str, collection: str, filter: dict[str, Any] | None = None,
                   projection: dict[str, Any] | None = None, limit: int = 100) -> dict[str, Any]:
        cfg = self._cfg(profile, "mongodb")
        if not 1 <= limit <= self.max_rows:
            raise ToolExecutionError("MongoDB limit outside configured bounds.")
        try:
            from pymongo import MongoClient
        except ImportError as exc:
            raise ToolExecutionError("Install the database-mongodb extra.") from exc
        client = MongoClient(cfg["uri"], serverSelectionTimeoutMS=int(cfg.get("server_selection_timeout_ms", 5000)))
        try:
            docs = list(client[cfg["database"]][_ident(collection)].find(self._mongo_filter(filter or {}), projection).limit(limit + 1))
            if len(docs) > limit:
                raise ToolExecutionError("MongoDB query exceeded its result limit.")
            return {"documents": _bounded(docs, self.max_bytes), "count": len(docs)}
        finally:
            client.close()

    def mongo_insert(self, profile: str, collection: str, document: dict[str, Any]) -> dict[str, Any]:
        cfg = self._cfg(profile, "mongodb")
        if not isinstance(document, dict) or not document or len(json.dumps(document, default=str)) > 50000:
            raise ToolExecutionError("MongoDB document must be non-empty and under 50 KB.")
        try:
            from pymongo import MongoClient
        except ImportError as exc:
            raise ToolExecutionError("Install the database-mongodb extra.") from exc
        client = MongoClient(cfg["uri"], serverSelectionTimeoutMS=int(cfg.get("server_selection_timeout_ms", 5000)))
        try:
            result = client[cfg["database"]][_ident(collection)].insert_one(document)
            return {"inserted_id": str(result.inserted_id)}
        finally:
            client.close()

    def mongo_update(self, profile: str, collection: str, filter: dict[str, Any],
                     values: dict[str, Any], many: bool = False) -> dict[str, Any]:
        cfg = self._cfg(profile, "mongodb")
        if not filter or not isinstance(values, dict) or not values or any(k.startswith("$") for k in values):
            raise ToolExecutionError("MongoDB update requires a safe non-empty filter and values.")
        try:
            from pymongo import MongoClient
        except ImportError as exc:
            raise ToolExecutionError("Install the database-mongodb extra.") from exc
        client = MongoClient(cfg["uri"], serverSelectionTimeoutMS=int(cfg.get("server_selection_timeout_ms", 5000)))
        try:
            coll = client[cfg["database"]][_ident(collection)]
            result = coll.update_many(self._mongo_filter(filter), {"$set": values}) if many else coll.update_one(self._mongo_filter(filter), {"$set": values})
            return {"matched": result.matched_count, "modified": result.modified_count}
        finally:
            client.close()

    def mongo_delete(self, profile: str, collection: str, filter: dict[str, Any],
                     many: bool = False) -> dict[str, Any]:
        cfg = self._cfg(profile, "mongodb")
        if not filter:
            raise ToolExecutionError("MongoDB delete requires a non-empty filter.")
        try:
            from pymongo import MongoClient
        except ImportError as exc:
            raise ToolExecutionError("Install the database-mongodb extra.") from exc
        client = MongoClient(cfg["uri"], serverSelectionTimeoutMS=int(cfg.get("server_selection_timeout_ms", 5000)))
        try:
            coll = client[cfg["database"]][_ident(collection)]
            result = coll.delete_many(self._mongo_filter(filter)) if many else coll.delete_one(self._mongo_filter(filter))
            return {"deleted_count": result.deleted_count}
        finally:
            client.close()

    def mongo_transaction(self, profile: str, operations: list[dict[str, Any]]) -> dict[str, Any]:
        cfg = self._cfg(profile, "mongodb")
        if not 1 <= len(operations) <= self.max_batch:
            raise ToolExecutionError("MongoDB transaction size outside configured bounds.")
        try:
            from pymongo import MongoClient
        except ImportError as exc:
            raise ToolExecutionError("Install the database-mongodb extra.") from exc
        client = MongoClient(cfg["uri"], serverSelectionTimeoutMS=int(cfg.get("server_selection_timeout_ms", 5000)))
        results = []
        try:
            with client.start_session() as session:
                with session.start_transaction():
                    for op in operations:
                        kind, collection = op.get("operation"), _ident(op.get("collection"))
                        coll = client[cfg["database"]][collection]
                        if kind == "insert":
                            document = op.get("document")
                            if not isinstance(document, dict) or not document:
                                raise ToolExecutionError("MongoDB transaction insert requires a document.")
                            result = coll.insert_one(document, session=session)
                            results.append({"operation": kind, "inserted_id": str(result.inserted_id)})
                        elif kind in {"update", "delete"}:
                            filter_doc = self._mongo_filter(op.get("filter", {}))
                            if not filter_doc:
                                raise ToolExecutionError("MongoDB transaction update/delete requires a filter.")
                            many = bool(op.get("many", False))
                            if kind == "update":
                                values = op.get("values")
                                if not isinstance(values, dict) or not values or any(k.startswith("$") for k in values):
                                    raise ToolExecutionError("MongoDB transaction update requires safe values.")
                                result = coll.update_many(filter_doc, {"$set": values}, session=session) if many else coll.update_one(filter_doc, {"$set": values}, session=session)
                                results.append({"operation": kind, "matched": result.matched_count, "modified": result.modified_count})
                            else:
                                result = coll.delete_many(filter_doc, session=session) if many else coll.delete_one(filter_doc, session=session)
                                results.append({"operation": kind, "deleted_count": result.deleted_count})
                        else:
                            raise ToolExecutionError("Unsupported MongoDB transaction operation.")
            return {"committed": True, "operations": results}
        finally:
            client.close()

    def _redis(self, profile: str):
        cfg = self._cfg(profile, "redis")
        try:
            import redis
        except ImportError as exc:
            raise ToolExecutionError("Install the database-redis extra.") from exc
        return cfg, redis.Redis.from_url(cfg["url"], socket_timeout=float(cfg.get("socket_timeout", 5)))

    @staticmethod
    def _key(cfg: dict[str, Any], key: str) -> str:
        prefix = cfg.get("key_prefix", "")
        if not isinstance(prefix, str) or len(prefix) > 200 or not isinstance(key, str) or not key or len(key) > 500:
            raise ToolExecutionError("Invalid Redis key or host-configured prefix.")
        if prefix and key.startswith(prefix):
            raise ToolExecutionError("Pass a key relative to the configured prefix.")
        return prefix + key

    def redis_get(self, profile: str, key: str) -> dict[str, Any]:
        cfg, client = self._redis(profile)
        key = self._key(cfg, key)
        try:
            raw = client.get(key)
            if raw is None:
                return {"key": key, "exists": False, "value": None}
            try:
                value = raw.decode("utf-8")
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    pass
            except UnicodeDecodeError:
                import base64
                value = {"$binary_base64": base64.b64encode(raw).decode("ascii")}
            return {"key": key, "exists": True, "value": _bounded(value, self.max_bytes)}
        finally:
            client.close()

    def redis_set(self, profile: str, key: str, value: Any,
                  ttl_seconds: int | None = None) -> dict[str, Any]:
        cfg, client = self._redis(profile)
        key = self._key(cfg, key)
        if ttl_seconds is not None and not 1 <= ttl_seconds <= 31_536_000:
            raise ToolExecutionError("TTL must be between 1 second and one year.")
        payload = json.dumps(_safe(value), ensure_ascii=False)
        if len(payload.encode("utf-8")) > 1_000_000:
            raise ToolExecutionError("Redis values are limited to 1 MB.")
        try:
            client.set(key, payload, ex=ttl_seconds)
            return {"key": key, "stored": True, "ttl_seconds": ttl_seconds}
        finally:
            client.close()

    def redis_delete(self, profile: str, key: str) -> dict[str, Any]:
        cfg, client = self._redis(profile)
        key = self._key(cfg, key)
        try:
            return {"key": key, "deleted": bool(client.delete(key))}
        finally:
            client.close()

    def redis_scan(self, profile: str, match: str = "*", count: int = 100) -> dict[str, Any]:
        cfg, client = self._redis(profile)
        if not 1 <= count <= self.max_rows or not isinstance(match, str) or len(match) > 200:
            raise ToolExecutionError("Redis scan arguments outside configured bounds.")
        prefix = cfg.get("key_prefix", "")
        if not prefix:
            raise ToolExecutionError("Redis SCAN requires a non-empty host-configured key_prefix.")
        try:
            keys = []
            for key in client.scan_iter(match=prefix + match, count=min(count, 100)):
                keys.append(key.decode("utf-8", errors="replace"))
                if len(keys) >= count:
                    break
            return {"keys": keys, "count": len(keys), "truncated": len(keys) == count}
        finally:
            client.close()

    def redis_transaction(self, profile: str, operations: list[dict[str, Any]]) -> dict[str, Any]:
        cfg, client = self._redis(profile)
        if not 1 <= len(operations) <= self.max_batch:
            raise ToolExecutionError("Redis transaction size outside configured bounds.")
        try:
            pipe = client.pipeline(transaction=True)
            for op in operations:
                key, kind = self._key(cfg, op.get("key", "")), op.get("operation")
                if kind == "set":
                    value = json.dumps(_safe(op.get("value")), ensure_ascii=False)
                    ttl = op.get("ttl_seconds")
                    if len(value.encode("utf-8")) > 1_000_000 or (ttl is not None and not 1 <= ttl <= 31_536_000):
                        raise ToolExecutionError("Redis transaction value or TTL exceeds limits.")
                    pipe.set(key, value, ex=ttl)
                elif kind == "delete":
                    pipe.delete(key)
                elif kind == "increment":
                    pipe.incrby(key, int(op.get("amount", 1)))
                elif kind == "expire":
                    ttl = op.get("ttl_seconds")
                    if not isinstance(ttl, int) or not 1 <= ttl <= 31_536_000:
                        raise ToolExecutionError("Invalid Redis transaction TTL.")
                    pipe.expire(key, ttl)
                else:
                    raise ToolExecutionError("Unsupported Redis transaction operation.")
            return {"results": _bounded(pipe.execute(), self.max_bytes)}
        finally:
            client.close()


def create_database_tools(profiles: dict[str, dict[str, Any]], *, max_rows: int = 500,
                          max_result_bytes: int = 100_000, max_batch: int = 100) -> tuple[FunctionTool, ...]:
    """Create optional database tools from trusted, named host connection profiles."""
    pack = DatabasePack(profiles, max_rows, max_result_bytes, max_batch)
    tools: list[FunctionTool] = []
    sql = sorted(k for k, v in pack.profiles.items() if v["backend"] in {"sqlite", "mysql", "postgresql"})
    mongo = sorted(k for k, v in pack.profiles.items() if v["backend"] == "mongodb")
    redis_profiles = sorted(k for k, v in pack.profiles.items() if v["backend"] == "redis")

    def add(name: str, desc: str, props: dict[str, Any], required: list[str],
            cap: str, fn: Any, timeout: float = 20) -> None:
        tools.append(FunctionTool(name, desc, object_schema(props, required), cap, fn,
                                  timeout=timeout, output_limit=max_result_bytes + 2000))

    def profile_schema(names: list[str]) -> dict[str, Any]:
        return {"type": "string", "enum": names}

    if sql:
        p = profile_schema(sql)
        add("database.sql_list_tables", "List SQL tables and views.", {"profile": p}, ["profile"], "database:schema:read", pack.sql_tables)
        add("database.sql_describe_table", "Describe SQL table columns and types.", {"profile": p, "table": {"type": "string"}}, ["profile", "table"], "database:schema:read", pack.sql_describe)
        add("database.sql_select", "Select bounded rows using validated identifiers and bound filter parameters.", {"profile": p, "table": {"type": "string"}, "columns": {"type": "array", "items": {"type": "string"}, "maxItems": 100}, "filters": {"type": "array", "items": {"type": "object"}, "maxItems": 20}, "order_by": {"type": "string"}, "descending": {"type": "boolean"}, "limit": {"type": "integer", "minimum": 1, "maximum": max_rows}, "offset": {"type": "integer", "minimum": 0, "maximum": 1000000}}, ["profile", "table"], "database:read", pack.sql_select)
        add("database.sql_insert", "Insert one SQL row with bound parameters.", {"profile": p, "table": {"type": "string"}, "values": {"type": "object", "minProperties": 1, "maxProperties": 100}}, ["profile", "table", "values"], "database:write", pack.sql_insert)
        add("database.sql_update", "Update matching SQL rows; an explicit filter is mandatory.", {"profile": p, "table": {"type": "string"}, "values": {"type": "object", "minProperties": 1}, "filters": {"type": "array", "items": {"type": "object"}, "minItems": 1, "maxItems": 20}}, ["profile", "table", "values", "filters"], "database:write", pack.sql_update)
        add("database.sql_delete", "Delete matching SQL rows; an explicit filter is mandatory.", {"profile": p, "table": {"type": "string"}, "filters": {"type": "array", "items": {"type": "object"}, "minItems": 1, "maxItems": 20}}, ["profile", "table", "filters"], "database:delete", pack.sql_delete)
        add("database.sql_transaction", "Run bounded atomic SQL insert/update/delete operations.", {"profile": p, "operations": {"type": "array", "items": {"type": "object"}, "minItems": 1, "maxItems": max_batch}}, ["profile", "operations"], "database:transaction", pack.sql_transaction, 30)

    if mongo:
        p = profile_schema(mongo)
        add("database.mongo_list_collections", "List MongoDB collections.", {"profile": p}, ["profile"], "database:schema:read", pack.mongo_collections)
        add("database.mongo_find", "Find bounded MongoDB documents with a restricted structured filter.", {"profile": p, "collection": {"type": "string"}, "filter": {"type": "object"}, "projection": {"type": "object"}, "limit": {"type": "integer", "minimum": 1, "maximum": max_rows}}, ["profile", "collection"], "database:read", pack.mongo_find)
        add("database.mongo_insert", "Insert one MongoDB document.", {"profile": p, "collection": {"type": "string"}, "document": {"type": "object", "minProperties": 1}}, ["profile", "collection", "document"], "database:write", pack.mongo_insert)
        add("database.mongo_update", "Set fields on matching MongoDB documents; filter is mandatory.", {"profile": p, "collection": {"type": "string"}, "filter": {"type": "object", "minProperties": 1}, "values": {"type": "object", "minProperties": 1}, "many": {"type": "boolean"}}, ["profile", "collection", "filter", "values"], "database:write", pack.mongo_update)
        add("database.mongo_delete", "Delete matching MongoDB documents; filter is mandatory.", {"profile": p, "collection": {"type": "string"}, "filter": {"type": "object", "minProperties": 1}, "many": {"type": "boolean"}}, ["profile", "collection", "filter"], "database:delete", pack.mongo_delete)
        add("database.mongo_transaction", "Run a bounded MongoDB transaction on a transaction-capable deployment.", {"profile": p, "operations": {"type": "array", "items": {"type": "object"}, "minItems": 1, "maxItems": max_batch}}, ["profile", "operations"], "database:transaction", pack.mongo_transaction, 30)

    if redis_profiles:
        p = profile_schema(redis_profiles)
        add("database.redis_get", "Read a Redis key under the configured key prefix.", {"profile": p, "key": {"type": "string", "maxLength": 500}}, ["profile", "key"], "database:read", pack.redis_get)
        add("database.redis_set", "Set a JSON value with an optional TTL.", {"profile": p, "key": {"type": "string"}, "value": {}, "ttl_seconds": {"type": "integer", "minimum": 1, "maximum": 31536000}}, ["profile", "key", "value"], "database:write", pack.redis_set)
        add("database.redis_delete", "Delete a Redis key under the configured prefix.", {"profile": p, "key": {"type": "string"}}, ["profile", "key"], "database:delete", pack.redis_delete)
        add("database.redis_scan", "Scan a bounded number of Redis keys under the configured prefix.", {"profile": p, "match": {"type": "string", "maxLength": 200}, "count": {"type": "integer", "minimum": 1, "maximum": max_rows}}, ["profile"], "database:read", pack.redis_scan)
        add("database.redis_transaction", "Run a bounded atomic Redis transaction.", {"profile": p, "operations": {"type": "array", "items": {"type": "object"}, "minItems": 1, "maxItems": max_batch}}, ["profile", "operations"], "database:transaction", pack.redis_transaction, 30)
    return tuple(tools)

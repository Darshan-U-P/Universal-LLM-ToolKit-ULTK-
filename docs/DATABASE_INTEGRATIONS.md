# Database integrations

ULTK provides one optional, provider-independent database pack for SQLite, MySQL, PostgreSQL,
MongoDB and Redis. Drivers are imported lazily; install only the drivers used by the host.

## Installation

- SQLite: Python standard library; no extra.
- MySQL: \`pip install -e ".[database-mysql]"\`
- PostgreSQL: \`pip install -e ".[database-postgresql]"\` (psycopg 3)
- MongoDB: \`pip install -e ".[database-mongodb]"\` (PyMongo)
- Redis: \`pip install -e ".[database-redis]"\`
- All remote drivers: \`pip install -e ".[databases]"\`

## Host configuration

Pass a mapping of trusted profile names to dictionaries to
\`ToolEngine.install_database_tools(profiles=...)\`. The model receives only profile names
embedded in the tool schemas. It cannot submit a URI, DSN, username, password, TLS option or
driver configuration.

\`\`\`python
from ultk import ToolEngine

engine = ToolEngine(policy=your_policy)
engine.install_database_tools(profiles={
    "app_sqlite": {"backend": "sqlite", "path": "./data/app.sqlite3"},
    "warehouse": {
        "backend": "postgresql", "host": "db.internal", "port": 5432,
        "dbname": "warehouse", "user": "ultk_reader",
        "password": secret_manager.get("warehouse-password"),
        "sslmode": "verify-full",
    },
    "mysql_app": {
        "backend": "mysql", "host": "mysql.internal", "database": "app",
        "user": "ultk_writer", "password": secret_manager.get("mysql-password"),
        "port": 3306,
    },
    "mongo_docs": {
        "backend": "mongodb", "uri": secret_manager.get("mongo-uri"),
        "database": "documents",
    },
    "cache": {
        "backend": "redis", "url": secret_manager.get("redis-url"),
        "key_prefix": "ultk:",
    },
})
\`\`\`

The secret-manager reference above is illustrative host code, not a ULTK API. Never put real
credentials in prompts, tool arguments, source control or model-visible tool output. Use TLS,
network allowlists, authentication and least-privilege service accounts.

## Tools and capabilities

| Backend | Tools | Capabilities |
|---|---|---|
| SQLite / MySQL / PostgreSQL | \`database.sql_list_tables\`, \`database.sql_describe_table\` | \`database:schema:read\` |
| SQL | \`database.sql_select\` | \`database:read\` |
| SQL | \`database.sql_insert\`, \`database.sql_update\` | \`database:write\` |
| SQL | \`database.sql_delete\` | \`database:delete\` |
| SQL | \`database.sql_transaction\` | \`database:transaction\` |
| MongoDB | \`database.mongo_list_collections\` | \`database:schema:read\` |
| MongoDB | \`database.mongo_find\` | \`database:read\` |
| MongoDB | \`database.mongo_insert\`, \`database.mongo_update\` | \`database:write\` |
| MongoDB | \`database.mongo_delete\` | \`database:delete\` |
| Redis | \`database.redis_get\`, \`database.redis_scan\` | \`database:read\` |
| Redis | \`database.redis_set\` | \`database:write\` |
| Redis | \`database.redis_delete\` | \`database:delete\` |
| Redis | \`database.redis_transaction\` | \`database:transaction\` |

## SQL behavior

SQL is declarative rather than free-form. Table/column identifiers must match a conservative
identifier grammar. Filter values are sent as driver parameters, never interpolated into SQL.
Supported filter operators: \`eq\`, \`ne\`, \`gt\`, \`gte\`, \`lt\`, \`lte\`, \`in\`, \`is_null\`,
and \`not_null\`. SELECT has bounded rows/offset and optional ordering. UPDATE and DELETE
require at least one filter; unbounded mutations are rejected. Transactions accept bounded
insert/update/delete operation arrays and roll back as a unit on failure.

## MongoDB behavior

Find supports structured MongoDB filters, optional projection and bounded results. Bounded multi-document insert/update/delete transactions use PyMongo sessions and require a replica set or sharded cluster. Filter
operators are restricted to logical and comparison operators; executable operators such as
\`$where\`, \`$function\`, \`$expr\` and unknown operators are rejected. Update uses \`$set\`
with model-supplied field names and requires a non-empty filter. Delete also requires a
non-empty filter. Multi-document writes are opt-in via the \`many\` argument.

## Redis behavior

Values are JSON-encoded. Set supports a bounded TTL; SCAN is bounded by a maximum result count.
A host-configured \`key_prefix\` scopes key access; callers provide relative keys. Redis
transactions use MULTI/EXEC and support set, delete, increment and expire operations.

## Security and operational boundaries

- Profiles are host-controlled and credentials are not exposed to model arguments.
- Read, write, delete, schema inspection and transaction capabilities are separate.
- Use database-native read-only/read-write roles and narrow schema/table/collection grants.
- Require human approval for consequential mutations, account data changes and destructive jobs.
- Apply TLS certificate verification, network egress controls, connection limits and server-side
  query timeouts. Host-supplied connection settings are trusted configuration.
- Output/row/batch bounds limit result volume but do not make a database query cheap; add
  server-side indexes, statement timeouts, quotas and workload isolation.
- SQLite paths are host configuration, not model-selected. Protect the database file and parent
  directory with OS permissions.
- This pack is not a network sandbox, secret manager, SQL policy engine or distributed transaction
  coordinator. MongoDB transactions use driver sessions and require a deployment that supports transactions (normally a replica set or sharded cluster); standalone MongoDB deployments reject them.
- Remote service integration, failover, pool lifecycle, advanced schema migrations, arbitrary SQL,
  stored procedures, Mongo aggregation pipelines, Redis scripting/streams/pub-sub and ORM mapping
  are not included.

The test suite uses SQLite for deterministic integration tests and mocks/reject-path checks for
remote-specific safety. Live MySQL, PostgreSQL, MongoDB and Redis service tests remain necessary
before production deployment.

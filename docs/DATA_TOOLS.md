# Data and Database Tools

The data pack adds bounded UTF-8 CSV/JSON file operations and a SQLite adapter. File operations are confined to a host-configured root, enforce byte/row limits, and use atomic replacement for writes.

## Install

```python
engine.install_data_tools(
    root_dir="./workspace/data",
    sqlite_database="./workspace/app.sqlite3",
    allow_database_writes=False,
    max_file_bytes=5_000_000,
    max_rows=1000,
)
```

Tools:
- `data.json_read`, `data.json_write`
- `data.csv_read`, `data.csv_write`
- `database.query` — parameterized, read-only SQL
- `database.get_schema` — list tables and views
- `database.execute_write` — registered only when the host explicitly sets `allow_database_writes=True`

All tools require both a tool allowlist entry and the matching capability grant. Database read operations open SQLite in read-only URI mode and install an authorizer that denies schema changes, writes, attach/detach, PRAGMA and other unapproved actions. Write mode is separately opt-in and allows DML only (INSERT, UPDATE and DELETE); schema changes remain denied. SQL parameters are passed separately to SQLite, never interpolated into SQL text.

## Limits and caveats

- SQLite is the only database backend in this increment. PostgreSQL, MySQL, SQL Server, NoSQL and vector databases are not implemented here.
- The SQLite authorizer is defense in depth, not a substitute for database-level accounts, file permissions or a dedicated database service.
- File root checks do not constitute an OS sandbox and do not eliminate all symlink/TOCTOU races.
- No dataframe engine, ETL scheduler, workbook engine or visualization subsystem is included yet.
- Verify Windows URI handling, concurrent writes, large results, malicious SQL and file race behavior in the deferred validation phase.

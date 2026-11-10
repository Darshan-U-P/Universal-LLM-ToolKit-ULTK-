"""Repeatable ULTK persistent-memory load benchmark.

Run after installing the package:
    python benchmarks/benchmark_memory.py --records 10000 --queries 250 --workers 8
Use --database to benchmark a dedicated persistent test database. The default uses a
temporary directory and never touches a production memory database.
"""
from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ultk.builtins.memory import PersistentMemory


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=int, default=10_000)
    parser.add_argument("--queries", type=int, default=250)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--database", type=Path)
    args = parser.parse_args()
    if not 1 <= args.records <= 1_000_000:
        parser.error("--records must be between 1 and 1,000,000")
    if not 1 <= args.queries <= 100_000:
        parser.error("--queries must be between 1 and 100,000")
    if not 1 <= args.workers <= 32:
        parser.error("--workers must be between 1 and 32")

    temporary = tempfile.TemporaryDirectory() if args.database is None else None
    database = args.database or Path(temporary.name) / "memory-benchmark.sqlite3"
    store = PersistentMemory(database, namespace="benchmark", max_items=1_000_000)

    def write(index: int) -> None:
        store.remember(
            "benchmark-session",
            f"Benchmark document {index}: subsystem {index % 97}, component {index % 211}, "
            f"topic {index % 53}, workload memory retrieval validation.",
            kind="semantic",
            tags=["benchmark"],
            confidence=0.8,
        )

    write_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        list(executor.map(write, range(args.records)))
    write_seconds = time.perf_counter() - write_started

    latencies: list[float] = []
    query_started = time.perf_counter()
    for index in range(args.queries):
        started = time.perf_counter()
        store.recall(
            "benchmark-session",
            f"subsystem {index % 97} component {index % 211}",
            limit=10,
        )
        latencies.append((time.perf_counter() - started) * 1000)
    query_seconds = time.perf_counter() - query_started

    report = {
        "records_written": args.records,
        "queries_executed": args.queries,
        "workers": args.workers,
        "write_seconds": round(write_seconds, 3),
        "writes_per_second": round(args.records / max(write_seconds, 1e-9), 2),
        "query_seconds": round(query_seconds, 3),
        "queries_per_second": round(args.queries / max(query_seconds, 1e-9), 2),
        "query_latency_ms": {
            "p50": round(percentile(latencies, 0.50), 3),
            "p95": round(percentile(latencies, 0.95), 3),
            "max": round(max(latencies, default=0.0), 3),
            "mean": round(statistics.fmean(latencies), 3) if latencies else 0.0,
        },
        "diagnostics": {
            "database_bytes": Path(database).stat().st_size,
            "integrity_check": None,
        },
        "database": str(database),
    }
    with store.db() as connection:
        report["diagnostics"]["integrity_check"] = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]
        report["diagnostics"]["record_count"] = connection.execute(
            "SELECT COUNT(*) FROM memory_items WHERE ns=?", ("benchmark",)
        ).fetchone()[0]
    print(json.dumps(report, indent=2))
    if temporary is not None:
        temporary.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

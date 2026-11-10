import asyncio
import json
from concurrent.futures import ProcessPoolExecutor

from ultk.builtins.memory import PersistentMemory
from ultk.engine import ToolEngine
from ultk.permissions import AllowListPolicy


def _process_append(database, worker):
    store = PersistentMemory(database, namespace="multi-process")
    for index in range(15):
        store.context_append("shared-session", "user", f"worker-{worker}-entry-{index}")
    return True


def test_engine_automatically_extracts_and_summarizes_at_configured_cadence(tmp_path):
    database = tmp_path / "automatic.sqlite3"

    def extractor(messages):
        return [{
            "content": "The project uses Python for its automation runtime.",
            "kind": "semantic",
            "scope": "user",
            "confidence": 0.9,
            "tags": ["project-fact"],
        }]

    def summarizer(payload):
        if payload["task"] == "summarize_conversation":
            return {
                "summary": "The session discussed the Python automation runtime.",
                "facts": ["Python is used for the automation runtime."],
                "decisions": [],
                "open_loops": [],
            }
        return {"summary": "Consolidated memory."}

    engine = ToolEngine(policy=AllowListPolicy({"memory.context_append"}))
    engine.install_memory_tools(
        database=database,
        namespace="tenant",
        extractor=extractor,
        summarizer=summarizer,
        auto_extract_every=2,
        auto_summarize_every=2,
    )

    async def append(content):
        result = await engine.execute(
            "memory.context_append",
            {"role": "user", "content": content},
            session_id="session-a",
            granted_capabilities=frozenset({"memory:context:write", "memory:write", "memory:maintenance"}),
        )
        return json.loads(result.content)

    first = asyncio.run(append("First user message."))
    second = asyncio.run(append("Second user message."))

    assert first["automatic_memory"] == {}
    assert second["automatic_memory"]["extraction"]["extracted"] == 1
    assert second["automatic_memory"]["summary"]["summarized"] is True
    store = PersistentMemory(database, namespace="tenant")
    recalled = store.recall("session-b", "Python automation runtime", limit=10)
    assert recalled["count"] >= 2


def test_multi_process_sqlite_context_writers_do_not_lose_entries(tmp_path):
    database = str(tmp_path / "multiprocess.sqlite3")
    with ProcessPoolExecutor(max_workers=4) as pool:
        assert all(pool.map(_process_append, [database] * 4, range(4)))

    store = PersistentMemory(database, namespace="multi-process")
    context = store.context_get("shared-session", limit=200)
    assert context["count"] == 60
    sequences = [entry["seq"] for entry in context["entries"]]
    assert len(set(sequences)) == 60
    with store.db() as connection:
        count = connection.execute(
            "SELECT user_messages FROM memory_session_stats WHERE ns=? AND sid=?",
            ("multi-process", "shared-session"),
        ).fetchone()[0]
    assert count == 60


def test_memory_scale_smoke_1500_records_and_bounded_recall(tmp_path):
    store = PersistentMemory(tmp_path / "scale.sqlite3", namespace="scale", max_items=2000)
    for index in range(1500):
        store.remember(
            "load-session",
            f"Document {index} describes subsystem {index % 17} and component {index % 31}.",
            kind="semantic",
            tags=["load-test"],
        )

    result = store.recall("load-session", "subsystem 7 component 14", limit=20)
    assert result["count"] > 0
    assert result["count"] <= 20
    diagnostics = store
    with diagnostics.db() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM memory_items WHERE ns=?", ("scale",)
        ).fetchone()[0]
    assert count == 1500

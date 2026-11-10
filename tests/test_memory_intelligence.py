from concurrent.futures import ThreadPoolExecutor

from ultk.builtins.memory import PersistentMemory
from ultk.builtins.memory_intelligence import MemoryIntelligence


def _same_vector(_: str) -> list[float]:
    return [1.0] + [0.0] * 7


def test_automatic_extraction_is_bounded_provenanced_and_deduplicated(tmp_path):
    store = PersistentMemory(tmp_path / "memory.sqlite3", namespace="tenant", embedder=_same_vector)
    store.context_append("session-a", "user", "I prefer Python for data engineering examples.")
    calls = []

    def extractor(messages):
        calls.append(messages)
        return [
            {
                "content": "User prefers Python for data engineering examples.",
                "kind": "semantic",
                "scope": "user",
                "confidence": 0.91,
                "tags": ["preference", "language"],
            },
            {
                "content": "password=do-not-store-this",
                "kind": "semantic",
                "scope": "user",
                "confidence": 0.99,
            },
        ]

    intelligence = MemoryIntelligence(
        store, extractor=extractor, summarizer=None, max_context_entries=20
    )
    first = intelligence.extract_context(session_id="session-a", limit=10)
    second = intelligence.extract_context(session_id="session-a", limit=10)

    assert first["extracted"] == 1
    assert first["skipped"] == 1
    assert second["extracted"] == 0
    assert second["skipped"] == 2
    assert len(calls) == 2
    result = store.recall("session-b", "Python data engineering", limit=5)
    assert result["count"] == 1
    assert result["memories"][0]["metadata"]["provenance"]["source"] == "automatic_context_extraction"


def test_intelligent_summarization_persists_summary_facts_and_decisions(tmp_path):
    store = PersistentMemory(tmp_path / "memory.sqlite3", namespace="tenant", embedder=_same_vector)
    store.context_append("session-a", "user", "We chose SQLite for local persistence.")
    store.context_append("session-a", "assistant", "The next task is concurrency testing.")

    def summarizer(payload):
        assert payload["task"] == "summarize_conversation"
        return {
            "summary": "The project uses SQLite for local persistent memory.",
            "facts": ["SQLite is the selected local persistence backend."],
            "decisions": ["Use SQLite for the local memory store."],
            "open_loops": ["Complete concurrent-write testing."],
        }

    intelligence = MemoryIntelligence(
        store, extractor=None, summarizer=summarizer, max_context_entries=20
    )
    result = intelligence.summarize_context(session_id="session-a", limit=20)

    assert result["summarized"] is True
    assert result["facts_stored"] == 1
    assert result["decisions_stored"] == 1
    assert result["open_loops"] == ["Complete concurrent-write testing."]
    recalled = store.recall("session-b", "SQLite local persistent memory", limit=10)
    assert any(item["tags"] == ["conversation-summary"] for item in recalled["memories"])


def test_related_consolidation_preserves_source_provenance_and_removes_sources(tmp_path):
    store = PersistentMemory(tmp_path / "memory.sqlite3", namespace="tenant", embedder=_same_vector)
    first = store.remember("session-a", "Darshan prefers Python examples.", kind="semantic", tags=["preference"])
    second = store.remember("session-a", "Python examples are preferred by Darshan.", kind="semantic", tags=["style"])

    def summarizer(payload):
        assert payload["task"] == "consolidate_memories"
        assert len(payload["memories"]) == 2
        return {"summary": "Darshan prefers Python examples."}

    intelligence = MemoryIntelligence(
        store, extractor=None, summarizer=summarizer, max_context_entries=20
    )
    result = intelligence.consolidate_related(session_id="session-a", query="Python", limit=10)

    assert result["consolidated"] is True
    assert result["source_records_deleted"] == 2
    assert store.forget("session-a", first["memory_id"])["forgotten"] is False
    assert store.forget("session-a", second["memory_id"])["forgotten"] is False
    merged = store.recall("session-b", "Python", limit=10)["memories"]
    assert len(merged) == 1
    assert "consolidated" in merged[0]["tags"]
    assert len(merged[0]["metadata"]["provenance"]["source_memory_ids"]) == 2


def test_sqlite_diagnostics_report_integrity_and_namespace_counts(tmp_path):
    store = PersistentMemory(tmp_path / "memory.sqlite3", namespace="tenant")
    store.remember("session-a", "A durable test fact.", kind="semantic")
    store.context_append("session-a", "user", "Working context.")
    report = MemoryIntelligence(
        store, extractor=None, summarizer=None
    ).diagnostics()

    assert report["healthy"] is True
    assert report["integrity_check"] == "ok"
    assert report["journal_mode"].lower() == "wal"
    assert report["memory_counts"] == [{"kind": "semantic", "scope": "user", "count": 1}]
    assert report["context_entries"] == 1
    assert len(report["namespace_fingerprint"]) == 16


def test_concurrent_context_appends_have_unique_ordered_sequences(tmp_path):
    store = PersistentMemory(tmp_path / "memory.sqlite3", namespace="tenant")

    def append(index):
        return store.context_append("one-session", "user", f"entry-{index}")

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(append, range(80)))

    assert len(results) == 80
    entries = store.context_get("one-session", limit=200)["entries"]
    sequences = [entry["seq"] for entry in entries]
    assert len(entries) == 80
    assert len(set(sequences)) == 80
    assert sorted(sequences) == list(range(1, 81))


def test_concurrent_memory_writes_do_not_exceed_capacity_or_lose_records(tmp_path):
    store = PersistentMemory(tmp_path / "memory.sqlite3", namespace="tenant", max_items=100)

    def remember(index):
        return store.remember("session", f"independent fact number {index}", kind="semantic")

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(remember, range(60)))

    assert len(results) == 60
    with store.db() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM memory_items WHERE ns=?", ("tenant",)
        ).fetchone()[0]
    assert count == 60

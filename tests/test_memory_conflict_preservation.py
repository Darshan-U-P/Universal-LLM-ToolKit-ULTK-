from ultk.builtins.memory import PersistentMemory
from ultk.builtins.memory_intelligence import MemoryIntelligence


def test_consolidation_preserves_conflicting_source_memories(tmp_path):
    store = PersistentMemory(
        tmp_path / "conflicts.sqlite3",
        namespace="tenant",
        embedder=lambda _: [1.0] + [0.0] * 7,
    )
    first = store.remember("session", "The service retention period is 30 days.", kind="semantic")
    second = store.remember("session", "The service retention period is 90 days.", kind="semantic")

    def summarizer(payload):
        return {
            "summary": "The service retention period has conflicting values.",
            "conflicts": ["One source says 30 days; another says 90 days."],
        }

    result = MemoryIntelligence(
        store, extractor=None, summarizer=summarizer
    ).consolidate_related(session_id="session", query="service retention period", limit=10)

    assert result["consolidated"] is False
    assert result["reason"] == "conflicting_information"
    assert result["source_records_retained"] == 2
    assert store.forget("session", first["memory_id"])["forgotten"] is True
    assert store.forget("session", second["memory_id"])["forgotten"] is True

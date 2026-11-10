"""Host-adapted automatic extraction, summarization and diagnostics for ULTK memory.

Adapters are trusted host callables. They receive bounded, role-tagged data and return
structured JSON-compatible values; model credentials and model selection never enter tool input.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections import defaultdict
from typing import Any, Callable

from ultk.builtins._common import object_schema
from ultk.builtins.memory import MemoryTool, PersistentMemory, _fingerprint, _metadata
from ultk.exceptions import ToolExecutionError

_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:password|passwd|api[_ -]?key|secret|access[_ -]?token)\s*[:=]\s*\S+"),
    re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)
_ALLOWED_KINDS = {"episodic", "semantic", "procedural"}


def _contains_secret(value: str) -> bool:
    return any(pattern.search(value) for pattern in _SECRET_PATTERNS)


def _safe_text(value: Any, *, limit: int = 4000) -> str:
    if not isinstance(value, str):
        raise ToolExecutionError("Adapter output text fields must be strings.")
    value = value.strip()
    if not value or len(value) > limit:
        raise ToolExecutionError("Adapter output text is empty or exceeds its size limit.")
    if _contains_secret(value):
        raise ToolExecutionError("Potential credential material was rejected by the memory safety filter.")
    return value


class MemoryIntelligence:
    """Orchestrates host-provided extraction/summarization over the persistent store."""

    def __init__(
        self,
        store: PersistentMemory,
        *,
        extractor: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None,
        summarizer: Callable[[dict[str, Any]], dict[str, Any]] | None,
        max_context_entries: int = 100,
        max_candidates: int = 30,
    ) -> None:
        if not 1 <= max_context_entries <= 200:
            raise ValueError("max_context_entries must be between 1 and 200.")
        if not 1 <= max_candidates <= 100:
            raise ValueError("max_candidates must be between 1 and 100.")
        self.store = store
        self.extractor = extractor
        self.summarizer = summarizer
        self.max_context_entries = max_context_entries
        self.max_candidates = max_candidates

    def extract_context(self, *, session_id: str, limit: int = 50) -> dict[str, Any]:
        if self.extractor is None:
            raise ToolExecutionError("Automatic extraction is not configured; inject a trusted host extractor.")
        if not 1 <= limit <= self.max_context_entries:
            raise ToolExecutionError("limit is outside the configured context bound.")
        context = self.store.context_get(session_id, limit=limit)["entries"]
        if not context:
            return {"extracted": 0, "skipped": 0, "reason": "empty_context"}
        try:
            candidates = self.extractor(context)
        except Exception as exc:
            raise ToolExecutionError(f"Memory extraction adapter failed ({type(exc).__name__}).") from exc
        if not isinstance(candidates, list) or len(candidates) > self.max_candidates:
            raise ToolExecutionError("Extractor must return a bounded list of memory objects.")
        extracted: list[dict[str, Any]] = []
        skipped = 0
        for candidate in candidates:
            if not isinstance(candidate, dict):
                skipped += 1
                continue
            try:
                body = _safe_text(candidate.get("content"), limit=8000)
                kind = candidate.get("kind", "semantic")
                scope = candidate.get("scope", "user")
                if kind not in _ALLOWED_KINDS or scope not in {"user", "session"}:
                    skipped += 1
                    continue
                confidence = candidate.get("confidence", 0.7)
                if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0.0 <= confidence <= 1.0:
                    skipped += 1
                    continue
                if confidence < 0.55:
                    skipped += 1
                    continue
                tags = candidate.get("tags", [])
                if not isinstance(tags, list) or len(tags) > 20 or any(
                    not isinstance(tag, str) or not tag.strip() or len(tag) > 64 for tag in tags
                ):
                    skipped += 1
                    continue
                metadata = candidate.get("metadata", {})
                if not isinstance(metadata, dict):
                    skipped += 1
                    continue
                metadata = dict(metadata)
                metadata["provenance"] = {
                    "source": "automatic_context_extraction",
                    "session_id": session_id,
                    "extracted_at": time.time(),
                    "extractor": getattr(self.extractor, "__name__", type(self.extractor).__name__),
                }
                metadata = _metadata(metadata)
                if _contains_secret(json.dumps(metadata, ensure_ascii=False)):
                    skipped += 1
                    continue
                fingerprint = _fingerprint(body)
                with self.store.db() as connection:
                    duplicate = connection.execute(
                        "SELECT id FROM memory_items WHERE ns=? AND fingerprint=? AND (scope='user' OR sid=?) LIMIT 1",
                        (self.store.namespace, fingerprint, session_id),
                    ).fetchone()
                if duplicate:
                    skipped += 1
                    continue
                result = self.store.remember(
                    session_id, body, kind=kind, scope=scope, tags=tags,
                    metadata=metadata, confidence=float(confidence),
                )
                extracted.append({"memory_id": result["memory_id"], "kind": kind, "confidence": float(confidence)})
            except ToolExecutionError:
                skipped += 1
        return {"extracted": len(extracted), "skipped": skipped, "memories": extracted}

    def summarize_context(self, *, session_id: str, limit: int = 80) -> dict[str, Any]:
        if self.summarizer is None:
            raise ToolExecutionError("Summarization is not configured; inject a trusted host summarizer.")
        if not 1 <= limit <= self.max_context_entries:
            raise ToolExecutionError("limit is outside the configured context bound.")
        messages = self.store.context_get(session_id, limit=limit)["entries"]
        if not messages:
            return {"summarized": False, "reason": "empty_context"}
        payload = {"task": "summarize_conversation", "messages": messages}
        try:
            result = self.summarizer(payload)
        except Exception as exc:
            raise ToolExecutionError(f"Memory summarizer failed ({type(exc).__name__}).") from exc
        if not isinstance(result, dict):
            raise ToolExecutionError("Summarizer must return an object.")
        summary = _safe_text(result.get("summary"), limit=12000)
        facts = result.get("facts", [])
        decisions = result.get("decisions", [])
        open_loops = result.get("open_loops", [])
        for field, values in (("facts", facts), ("decisions", decisions), ("open_loops", open_loops)):
            if not isinstance(values, list) or len(values) > self.max_candidates:
                raise ToolExecutionError(f"Summarizer {field} must be a bounded list.")
        provenance = {
            "source": "session_summary",
            "session_id": session_id,
            "summarized_at": time.time(),
            "message_sequences": [item["seq"] for item in messages],
        }
        summary_record = self.store.remember(
            session_id, summary, kind="episodic", scope="user",
            tags=["conversation-summary"], metadata={"provenance": provenance}, confidence=0.85,
        )
        stored_facts: list[str] = []
        for value in facts:
            fact = _safe_text(value, limit=4000)
            self.store.remember(
                session_id, fact, kind="semantic", scope="user",
                tags=["conversation-fact"], metadata={"provenance": provenance}, confidence=0.75,
            )
            stored_facts.append(fact)
        stored_decisions: list[str] = []
        for value in decisions:
            decision = _safe_text(value, limit=4000)
            self.store.remember(
                session_id, decision, kind="episodic", scope="user",
                tags=["decision"], metadata={"provenance": provenance}, confidence=0.8,
            )
            stored_decisions.append(decision)
        return {
            "summarized": True,
            "summary_memory_id": summary_record["memory_id"],
            "facts_stored": len(stored_facts),
            "decisions_stored": len(stored_decisions),
            "open_loops": [_safe_text(item, limit=2000) for item in open_loops],
        }

    def consolidate_related(self, *, session_id: str, query: str, limit: int = 20) -> dict[str, Any]:
        """Summarize only very high-similarity same-kind memories; source records remain on failure."""
        if self.summarizer is None:
            raise ToolExecutionError("Consolidation is not configured; inject a trusted host summarizer.")
        if not isinstance(query, str) or not query.strip() or len(query) > 4000 or not 2 <= limit <= 30:
            raise ToolExecutionError("Invalid consolidation query or limit.")
        recalled = self.store.recall(session_id, query, limit=limit, min_score=0.25)["memories"]
        if len(recalled) < 2:
            return {"consolidated": False, "reason": "not_enough_candidates", "candidates": len(recalled)}
        groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for item in recalled:
            groups[(item["kind"], item["scope"])].append(item)
        group = max(groups.values(), key=len)
        if len(group) < 2:
            return {"consolidated": False, "reason": "no_compatible_group", "candidates": len(recalled)}
        # Require strong vector agreement to avoid collapsing merely related or contradictory facts.
        selected: list[dict[str, Any]] = []
        with self.store.db() as connection:
            for item in group:
                row = connection.execute(
                    "SELECT vector FROM memory_items WHERE ns=? AND id=?",
                    (self.store.namespace, item["memory_id"]),
                ).fetchone()
                if row is not None:
                    item["_vector"] = json.loads(row["vector"])
                    selected.append(item)
        anchor = selected[0]["_vector"]
        compatible = [
            item for item in selected
            if len(item["_vector"]) == len(anchor)
            and sum(a * b for a, b in zip(anchor, item["_vector"])) >= 0.985
        ]
        if len(compatible) < 2:
            return {"consolidated": False, "reason": "similarity_threshold_not_met", "candidates": len(recalled)}
        source_ids = [item["memory_id"] for item in compatible]
        payload = {
            "task": "consolidate_memories",
            "instruction": "Produce one faithful summary. Preserve distinctions and uncertainty; do not infer facts.",
            "memories": [{key: value for key, value in item.items() if key != "_vector"} for item in compatible],
        }
        try:
            result = self.summarizer(payload)
        except Exception as exc:
            raise ToolExecutionError(f"Consolidation summarizer failed ({type(exc).__name__}).") from exc
        if not isinstance(result, dict):
            raise ToolExecutionError("Consolidation summarizer must return an object.")
        merged = _safe_text(result.get("summary"), limit=12000)
        first = compatible[0]
        tags = sorted({tag for item in compatible for tag in item["tags"]} | {"consolidated"})
        metadata = {
            "provenance": {
                "source": "intelligent_consolidation",
                "source_memory_ids": source_ids,
                "consolidated_at": time.time(),
            }
        }
        created = self.store.remember(
            session_id, merged, kind=first["kind"], scope=first["scope"],
            tags=tags, metadata=metadata,
            confidence=max(float(item["confidence"]) for item in compatible),
        )
        deleted = 0
        try:
            for memory_id in source_ids:
                if self.store.forget(session_id, memory_id)["forgotten"]:
                    deleted += 1
        except Exception:
            # The replacement is durable; retaining any source is safer than data loss.
            return {"consolidated": True, "summary_memory_id": created["memory_id"],
                    "source_records_deleted": deleted, "source_records_retained": len(source_ids) - deleted}
        return {"consolidated": True, "summary_memory_id": created["memory_id"],
                "source_records_deleted": deleted, "source_records_retained": 0}

    def diagnostics(self) -> dict[str, Any]:
        started = time.perf_counter()
        with self.store.db() as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            counts = connection.execute(
                "SELECT kind,scope,COUNT(*) AS count FROM memory_items WHERE ns=? GROUP BY kind,scope",
                (self.store.namespace,),
            ).fetchall()
            context_count = connection.execute(
                "SELECT COUNT(*) FROM memory_context WHERE ns=?", (self.store.namespace,)
            ).fetchone()[0]
            journal = connection.execute("PRAGMA journal_mode").fetchone()[0]
        import os
        size = os.path.getsize(self.store.database) if os.path.exists(self.store.database) else 0
        return {
            "healthy": integrity == "ok",
            "integrity_check": integrity,
            "journal_mode": journal,
            "database_bytes": size,
            "memory_counts": [dict(row) for row in counts],
            "context_entries": context_count,
            "namespace_fingerprint": hashlib.sha256(self.store.namespace.encode()).hexdigest()[:16],
            "diagnostic_duration_ms": round((time.perf_counter() - started) * 1000, 3),
        }


def create_memory_intelligence_tools(
    store: PersistentMemory,
    *,
    extractor: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
    summarizer: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    max_context_entries: int = 100,
    max_candidates: int = 30,
) -> tuple[MemoryTool, ...]:
    intelligence = MemoryIntelligence(
        store, extractor=extractor, summarizer=summarizer,
        max_context_entries=max_context_entries, max_candidates=max_candidates,
    )
    return (
        MemoryTool(
            "memory.extract_context",
            "Extract durable, validated memories from the active session context using the trusted host extractor.",
            object_schema({"limit": {"type": "integer", "minimum": 1, "maximum": max_context_entries}}),
            "memory:write", intelligence.extract_context,
        ),
        MemoryTool(
            "memory.summarize_context",
            "Summarize active session context and persist its summary, facts and decisions.",
            object_schema({"limit": {"type": "integer", "minimum": 1, "maximum": max_context_entries}}),
            "memory:maintenance", intelligence.summarize_context,
        ),
        MemoryTool(
            "memory.consolidate_related",
            "Consolidate only strongly similar same-kind memories using the trusted host summarizer.",
            object_schema({
                "query": {"type": "string", "minLength": 1, "maxLength": 4000},
                "limit": {"type": "integer", "minimum": 2, "maximum": 30},
            }, ["query"]),
            "memory:maintenance", intelligence.consolidate_related,
        ),
        MemoryTool(
            "memory.diagnostics",
            "Run bounded SQLite integrity and memory-capacity diagnostics for the configured namespace.",
            object_schema({}),
            "memory:maintenance", lambda **_: intelligence.diagnostics(),
        ),
    )

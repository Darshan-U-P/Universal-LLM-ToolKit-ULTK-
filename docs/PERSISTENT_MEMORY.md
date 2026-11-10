# Persistent memory

ULTK provides restart-safe, namespace-isolated conversation context and long-term memory.
Install it with a host-selected database path and namespace:

    engine.install_memory_tools(
        database="./data/user-memory.sqlite3",
        namespace=authenticated_user_id,
    )

The namespace is fixed by the host at installation time; it is never a model argument. In a
multi-user service, bind each engine/store to the authenticated principal or use a trusted
namespace router. Never derive identity from prompt text. The active dispatcher session ID is
injected from ToolContext, so a model cannot spoof the session identifier.

## Memory layers and lifecycle

- Working/session context: context_append, context_get and context_clear store bounded,
  role-tagged conversation/task entries for one session. The host agent appends messages as they
  enter the conversation.
- Episodic memory: remember(kind="episodic") stores events, interactions and outcomes.
- Semantic memory: remember(kind="semantic") stores durable facts and knowledge.
- Procedural memory: remember(kind="procedural") stores reusable procedures and workflows.
- Recall: memory.recall performs hybrid lexical/vector similarity ranking with confidence and
  recency weighting; it returns bounded results and records access counts.
- Maintenance: memory.update corrects records, memory.forget hard-deletes a record, and
  memory.consolidate merges exact normalized-text duplicates and combines tags/metadata.

User-scope memories are visible across sessions in the same host namespace. Session-scope
memories are visible only in the creating session. Conversation context is always session-scoped.
Cross-namespace and cross-session private records cannot be accessed by ID.

## Embeddings and retrieval

The default offline embedder generates deterministic feature-hash vectors from token features.
These vectors enable persistence and cosine similarity without downloading weights, but are
lexical features, not semantic language understanding. For semantic embeddings, supply a trusted
host callable embedder(text) -> list[float] to install_memory_tools. It must return consistent,
finite vectors of 8–8192 dimensions. ULTK normalizes and persists the vectors and computes cosine
similarity. The host owns the model, weights, inference runtime, licensing, privacy and lifecycle.
No model-controlled tool argument can replace the embedder.

## Tools and capabilities

| Tool | Capability | Purpose |
|---|---|---|
| memory.context_append | memory:context:write | Append current session context |
| memory.context_get | memory:context:read | Read current session context |
| memory.context_clear | memory:context:delete | Clear current session context |
| memory.remember | memory:write | Store episodic/semantic/procedural memory |
| memory.recall | memory:read | Hybrid similarity retrieval |
| memory.update | memory:write | Correct a stored memory |
| memory.forget | memory:delete | Permanently delete a memory |
| memory.consolidate | memory:maintenance | Merge exact duplicates |

Grant capabilities independently. Deletion and consolidation can be placed behind host approval.

## Persistence, isolation and privacy

SQLite is the default persistence backend. It uses parameterized statements, WAL mode,
per-operation connections, bounded inputs and a host-defined path. Data survives process
restarts. Protect the database and backups with OS permissions and encryption at rest. SQLite
does not provide multi-host distributed coordination.

The namespace is an application isolation boundary, not authentication. The host must authenticate
users and bind each engine to the correct namespace. For stronger isolation, use separate database
files and OS identities. Memory can contain sensitive personal data: obtain consent, minimize
retention, do not store secrets, and provide access/export/deletion workflows. Hard deletion does
not erase copies retained in WAL files, backups, filesystem snapshots or external embedding logs;
apply backup expiry and retention policies.

ULTK does not silently ingest every LLM turn or infer consent. When trusted extraction and
summarization adapters are configured, the host agent may invoke the explicit intelligence tools
or schedule them at session boundaries. The host remains responsible for deciding what context is
eligible for processing.

## Limits and boundaries

Default capacity is 100,000 memories per namespace. Context is bounded to 200 entries and 40,000
characters; memory content is limited to 20,000 characters. Recall scans at most the newest 5,000
visible records and returns at most 50. Large corpora should use a dedicated indexed vector store.

The base maintenance tool merges exact normalized-text duplicates. The optional intelligence
consolidator can summarize only strongly similar same-kind/scope records through a trusted host
summarizer; it is deliberately conservative and is not a contradiction solver. No automatic
deletion/decay is performed; confidence and recency affect ranking.
This subsystem is not a secret manager, secure enclave, backup service, identity provider or
distributed consistency protocol.


## Automatic extraction and intelligent consolidation

The memory pack can run extraction and summarization through trusted host adapters. Configure
them when installing the tools:

    engine.install_memory_tools(
        database="./data/user-memory.sqlite3",
        namespace=authenticated_user_id,
        embedder=embedding_callable,
        extractor=extractor_callable,
        summarizer=summarizer_callable,
    )

The extractor contract is `extractor(messages) -> list[dict]`, where each item contains
`content` and may include `kind`, `scope`, `tags`, `metadata` and `confidence`. It receives
bounded role-tagged session context, not credentials or provider configuration. Candidates are
size/type checked, low-confidence items are rejected, likely credential strings are filtered,
exact duplicates are skipped, and provenance records the source session and extraction time.
The host remains responsible for obtaining consent and selecting which context is eligible.

The summarizer contract is `summarizer(payload) -> dict`. For
`task=summarize_conversation`, return `summary` plus optional bounded `facts`, `decisions`
and `open_loops` arrays. For `task=consolidate_memories`, return a faithful `summary` of
the supplied source records. ULTK stores summaries and extracted facts with provenance.
Related-memory consolidation is conservative: it requires same-kind/scope records and a high
vector-similarity threshold, records source IDs, writes the replacement before deleting source
records, and retains sources if cleanup fails. If the summarizer returns a non-empty `conflicts` list, ULTK retains every source record and reports the conflict rather than merging. This is adapter-assisted conflict preservation, not an independent truth-verification system.

New tools: `memory.extract_context`, `memory.summarize_context`,
`memory.consolidate_related` and `memory.diagnostics`. Grant `memory:write` for extraction
and `memory:maintenance` for summarization, consolidation and diagnostics. These are explicit
tool calls; hosts may schedule them after a turn or at session boundaries. ULTK does not silently
ingest every message or run an implicit background model.

## Operational validation

`memory.diagnostics` runs SQLite `PRAGMA integrity_check` and reports namespace-scoped record
counts, context count, journal mode, database size and diagnostic duration. SQLite writes use an
explicit busy timeout and `BEGIN IMMEDIATE` for sequence allocation and capacity-checked inserts
to serialize concurrent writers. CI tests exercise concurrent context appends and memory writes,
restart persistence, namespace isolation, extraction filtering, provenance, summarization,
consolidation and integrity reporting.

A passing test suite is not a substitute for production qualification. Before deployment, run
workload-specific load tests, multi-process tests for the chosen storage layer, backup/restore
drills, disk-full and corruption recovery tests, real embedder retrieval evaluation, retention/
deletion verification for WAL and backups, and platform-specific Windows/macOS testing. SQLite
remains a single-host store; use a suitable shared database/vector service for multi-host scale.


## Automatic host scheduling defaults

The engine's automatic hooks are opt-in by adapter presence. With an extractor configured,
automatic extraction runs every 4 user messages by default. With a summarizer configured,
session summarization runs every 20 user messages by default. Configure
`auto_extract_every` and `auto_summarize_every` on `install_memory_tools`; pass `None` to
disable a hook while retaining the explicit tools. The counters are persisted per namespace/session
and are independent of the bounded context retention window. Automatic hooks execute synchronously
as part of the context-append tool call, so adapters should use bounded inference timeouts and
resource limits. Adapter failures are reported in the append result without discarding the context
entry.


### Repeatable load benchmark

Run the included benchmark against a temporary database:

    python benchmarks/benchmark_memory.py --records 10000 --queries 250 --workers 8

Increase the record count up to one million and adjust worker/query counts for the target
deployment. Use `--database` only with a dedicated test database; do not point the benchmark at
production user memory. The report includes write/query throughput, p50/p95/max query latency,
database size and SQLite integrity status. Compare results on the actual storage device, Python
version, embedding adapter and expected concurrency profile before setting capacity targets.

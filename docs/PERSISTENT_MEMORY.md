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

ULTK does not automatically ingest every LLM turn, infer consent, summarize history, or start a
background consolidation process. The host agent decides what context to append and what durable
facts to remember.

## Limits and boundaries

Default capacity is 100,000 memories per namespace. Context is bounded to 200 entries and 40,000
characters; memory content is limited to 20,000 characters. Recall scans at most the newest 5,000
visible records and returns at most 50. Large corpora should use a dedicated indexed vector store.

Consolidation merges exact normalized-text duplicates; it is not an LLM summarizer or ontology
resolver. No automatic deletion/decay is performed; confidence and recency affect ranking.
This subsystem is not a secret manager, secure enclave, backup service, identity provider or
distributed consistency protocol.

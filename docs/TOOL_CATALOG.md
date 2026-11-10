# Tool Catalog

This is a planned taxonomy, not an implementation inventory. Each tool must be implemented, tested, documented, and explicitly enabled before use.

| Domain | Planned tools |
|---|---|
| Core | provider/model discovery, registry, schemas, dispatch, retries, telemetry |
| Computer/OS | filesystem, process management, terminal, clipboard, persistent desktop sessions, multi-monitor/window/virtual desktop control, keyboard and accessibility automation, OCR text recognition and targeting, multi-scale image-template recognition, icon/control matching, unique-match clicking, scrolling, dragging, bounded visual GUI workflows, natural-language AI visual grounding, candidate-box inspection and unique-candidate clicking, native macOS/Linux accessibility actions, Sway Wayland window/workspace control, allowlisted Windows safe USB ejection |
| Web | search, URL fetch, headless browser sessions, accessible DOM inspection and interaction, persistent Chromium profiles, tabs/popups/iframes, cookie management, structured scraping, authenticated downloads, bounded network/WebSocket inspection, CAPTCHA detection and human auth handoff, preview-fingerprinted approval-gated form submission, browser test assertions, persistent website monitoring |
| Development | editor, isolated code runner, compiler, debugger, tests, Git status/log/diff, rebase/cherry-pick/revert, stash, linked worktrees, allowlisted submodules, conflict inspection/resolution, host-adapted pull-request review and merge |
| Data | CSV/JSON/XML/XLSX table I/O, schema validation, filtering, selection, rename, sort, deduplication, joins, grouping/aggregation, safe derived columns and file-to-file ETL; MySQL/PostgreSQL/SQLite, MongoDB and Redis integrations |
| Documents | TXT/Markdown/PDF/DOCX/PPTX/XLSX/XLS/ODT/ODS discovery, metadata and text extraction; PDF merge and page extraction |
| Communication | email, calendar, contacts, notifications, SMS, messaging |
| Media | image, audio, speech, video, subtitles, media conversion |
| AI/ML | embeddings, RAG, inference, datasets, evaluation, training, GPU inspection |
| Cloud/infra | Docker, Kubernetes, SSH, storage, compute, deployment, DNS, diagnostics |
| Integrations | REST, GraphQL, WebSocket, OAuth, webhooks, MCP, SDK connectors |
| Productivity/business | tasks, projects, notes, reminders, knowledge bases, commerce, analytics |
| Security | credential references, authentication, authorization, sandbox, audit, redaction |
| Agent systems | dependency-aware workflow DAGs, parallel steps, persistent checkpoints, retries/recovery, cooperative cancellation, execution traces, replay from saved definitions, delegation, scheduling and resumable jobs |

## Selection rules

- Prefer narrow, purpose-built tools over broad unrestricted tools.
- Separate read-only and mutating operations.
- Declare credentials as secure references; request them only when a tool is enabled.
- Require approval for destructive, externally visible, financial, or account-changing actions by default.
- Define execution, resource, concurrency, retry, and output limits.


## Advanced Git operations

Implemented as an optional pack via ToolEngine.install_advanced_git_tools. See
[Advanced Git Operations](ADVANCED_GIT_OPERATIONS.md) for tool names, capability requirements,
host adapter contract and safety boundaries. Tests are authored but validation is deferred.


## Documents and structured-data packs

Implemented as optional packs through `ToolEngine.install_document_tools(...)` and
`ToolEngine.install_structured_data_tools(...)`. See
[Documents and Structured Data](DOCUMENTS_AND_STRUCTURED_DATA.md). OCR, scanned-PDF recognition,
layout-faithful conversion, document editing, database engines, streaming/distributed ETL and
vector search remain separate capabilities.


## Database integrations

Implemented as an optional pack through \`ToolEngine.install_database_tools(profiles=...)\`.
See [Database Integrations](DATABASE_INTEGRATIONS.md) for profile configuration, tool
names, optional drivers, capabilities and security boundaries.

## Persistent memory

Implemented as an optional pack through `ToolEngine.install_memory_tools(...)`. Provides bounded
session context, episodic/semantic/procedural memory, namespace isolation, hybrid vector/lexical
recall, updates, deletion and duplicate consolidation. See [Persistent Memory](PERSISTENT_MEMORY.md).


The memory pack additionally exposes `memory.extract_context`,
`memory.summarize_context`, `memory.consolidate_related` and `memory.diagnostics` when
installed through `ToolEngine.install_memory_tools(...)`. Extraction and summarization require
trusted host adapters; outputs are bounded, validated and provenance-tagged. See
[Persistent Memory](PERSISTENT_MEMORY.md).

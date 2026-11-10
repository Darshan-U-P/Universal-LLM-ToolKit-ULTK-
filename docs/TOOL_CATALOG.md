# Tool Catalog

This is a planned taxonomy, not an implementation inventory. Each tool must be implemented, tested, documented, and explicitly enabled before use.

| Domain | Planned tools |
|---|---|
| Core | provider/model discovery, registry, schemas, dispatch, retries, telemetry |
| Computer/OS | filesystem, process management, terminal, clipboard, persistent desktop sessions, multi-monitor/window/virtual desktop control, keyboard and accessibility automation, OCR text recognition and targeting, scrolling, dragging, bounded visual GUI workflows |
| Web | search, URL fetch, headless browser sessions, accessible DOM inspection and interaction, bounded browser workflows, scraper, downloads, monitoring |
| Development | editor, isolated code runner, compiler, debugger, tests, Git, API testing |
| Data | SQL/NoSQL, CSV/XLSX, JSON/XML, ETL, vector DB, visualization |
| Documents | PDF, DOCX, PPTX, XLSX, OCR, conversion, document search |
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

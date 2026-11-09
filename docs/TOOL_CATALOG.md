# Tool Catalog

This is a planned taxonomy, not an implementation inventory. Each tool must be implemented, tested, documented, and explicitly enabled before use.

| Domain | Planned tools |
|---|---|
| Core | provider/model discovery, registry, schemas, dispatch, retries, telemetry |
| Computer/OS | filesystem and permissions/ACLs, process management, generic terminal, desktop sessions, multi-monitor/window/virtual-desktop management, keyboard automation, accessibility/UI Automation, cross-platform services, hardware/USB inventory and safe eject, network interface inspection, OS event monitoring |
| PowerShell/Windows administration | restricted persistent PowerShell runspaces and state, multi-step workflows, authorized persistent/one-shot WinRM remoting, registry writes, Defender Firewall rules, local users/groups, Windows Update, disks/partitions/volumes, certificate stores, pinned package/module installation, Active Directory, Group Policy, separately permissioned scheduled-task create/update/delete, audit/Defender hardening and SHA-256-pinned local security policy templates |
| Web | search, URL fetch, browser, scraper, downloads, monitoring |
| Development | editor, isolated code runner, compiler, debugger, tests, Git repository inspection, branch/index/commit/diff/merge/conflict/history/remote workflows, API testing |
| Data | SQL/NoSQL, CSV/XLSX, JSON/XML, ETL, vector DB, visualization |
| Documents | PDF, DOCX, PPTX, XLSX, OCR, conversion, document search |
| Communication | email, calendar, contacts, notifications, SMS, messaging |
| Media | image, audio, speech, video, subtitles, media conversion |
| AI/ML | embeddings, RAG, inference, datasets, evaluation, training, GPU inspection |
| Cloud/infra | Docker, Kubernetes, SSH, storage, compute, deployment, DNS, diagnostics |
| Integrations | REST, GraphQL, WebSocket, OAuth, webhooks, MCP, SDK connectors |
| Productivity/business | tasks, projects, notes, reminders, knowledge bases, commerce, analytics |
| Security | credential references, authentication, authorization, sandbox, audit, redaction |
| Agent systems | delegation, multi-agent communication, reflection, scheduling, resumable jobs |

## Selection rules

- Prefer narrow, purpose-built tools over broad unrestricted tools.
- Separate read-only and mutating operations.
- Declare credentials as secure references; request them only when a tool is enabled.
- Require approval for destructive, externally visible, financial, or account-changing actions by default.
- Define execution, resource, concurrency, retry, and output limits.

# Universal LLM ToolKit (ULTK)

A provider-independent, extensible tool execution framework for compatible large language models.

**Status:** Pre-alpha, partial implementation. Core runtime contracts and several built-in tool packs are present on sequential feature branches, but these branches are not yet integrated, comprehensively tested, or production-ready. See [the verification ledger](docs/VERIFICATION_LEDGER.md) for known failures and deferred checks.

## Vision

Connect an LLM to a governed, discoverable ecosystem of tools through one consistent runtime. ULTK should handle provider adaptation, tool registration and discovery, schema translation, policy checks, execution, result normalization, and bounded agent loops.

## Principles

- Provider-independent adapters for hosted and local models.
- Stable, versioned tool contracts using JSON-Schema-compatible input definitions.
- Explicit authorization and human approval; model output never directly executes arbitrary actions.
- Least privilege, bounded execution, cancellation, and resource limits.
- Lazy tool discovery/loading rather than sending every tool schema on every request.
- Extensible third-party plugins without modifying the orchestration core.
- Local and remote execution modes with distinct security boundaries.
- Structured telemetry with secret redaction.
- Honest provider capability negotiation; not all models support native tool calling.

## Implemented foundations (not yet fully validated)

Feature branches currently contain:
- Core provider-neutral tool contracts, registry, JSON Schema validation, capability policies, bounded dispatcher and mock provider.
- Filesystem, system inspection, terminal/process, computer/GUI, browser and development tool packs.
- Persistent approval requests, exact-argument one-time approval, SQLite audit hash chain and dependency-aware workflow DAG execution.
- Bounded CSV/JSON and SQLite database tools.
- Read-only text extraction for TXT/Markdown, PDF, DOCX, PPTX and XLSX.
- Host-configured HTTPS REST endpoints with host-held credentials and opt-in mutation methods.
- A non-streaming OpenAI-compatible provider adapter for hosted and loopback-local chat-completions servers.
- An explicitly trusted Python entry-point plugin SDK/manager with metadata-only discovery and enable/disable lifecycle.
- Bounded Pillow image operations and host-configured FFmpeg/ffprobe media processing.
- A host-configured TLS SMTP email sender with recipient allowlists and plain-text messages.

This list is an implementation snapshot, not a claim that the features have passed final integration tests. See [docs/VERIFICATION_LEDGER.md](docs/VERIFICATION_LEDGER.md).

## Architecture

```text
Application / SDK / REST API
          |
      Toolkit Facade
          |
     Provider Adapter
          |
    Agent Orchestrator
   /      |       \
Planner Context Workflow State
   \      |       /
     Tool Selection
          |
      Tool Registry
          |
   Schema & Policy Gate
          |
 Permission / Approval
          |
    Execution Runtime
    /      |       \
  Local  Remote  Sandboxed
  Tools  Tools   Executors
          |
  Normalized Tool Results
          |
     Provider Adapter
          |
      Final Response
```

Cross-cutting services: configuration and secret references, session state, optional memory, telemetry, caching, rate limits, cancellation, and audit records.

## Planned tool domains

The taxonomy below remains a roadmap; a domain may have only partial initial support.

| Domain | Planned capabilities |
|---|---|
| Core | provider/model discovery, tool registry, schema validation, dispatch, retries, telemetry |
| Computer/OS | filesystem, process management, terminal, clipboard, desktop automation |
| Web | search, URL fetch, browser automation, scraping, downloads, page monitoring |
| Development | code editing, isolated execution, compilers, debugging, tests, Git, API testing |
| Data | SQL/NoSQL, CSV/Excel, JSON/XML, ETL, vector databases, visualization |
| Documents | PDF, DOCX, PPTX, XLSX, OCR, conversion, document search |
| Communication | email, calendar, contacts, notifications, SMS and messaging integrations |
| Media | image, audio, speech, video, subtitles, media conversion |
| AI/ML | embeddings, RAG, inference, datasets, evaluation, training, GPU inspection |
| Cloud/infra | Docker, Kubernetes, SSH, storage, compute, deployment, DNS, diagnostics |
| Integrations | REST, GraphQL, WebSocket, OAuth, webhooks, MCP, third-party SDKs |
| Productivity/business | tasks, projects, notes, reminders, knowledge bases, commerce, analytics |
| Security | credential references, authentication, authorization, sandboxing, audit, redaction |
| Advanced agents | delegation, multi-agent coordination, reflection, resumable jobs |

## Proposed layout

```text
src/ultk/
  core/            # configuration, shared types, errors
  providers/       # provider adapter contracts and implementations
  agents/          # agent sessions and task lifecycle
  orchestration/   # planning, selection, workflows, control loop
  registry/        # tool registration, metadata, discovery
  schemas/         # schema translation and validation
  execution/       # dispatch, limits, retries, result envelopes
  permissions/     # authorization and human approval
  sandbox/         # isolated execution interfaces
  memory/          # optional session/task memory
  telemetry/       # traces, events and metrics
  plugins/         # plugin loading and compatibility
  api/             # optional HTTP API
plugins/            # independently packaged integrations
docs/
tests/
examples/
```

## Tool lifecycle

1. Application configures provider, model, secret references, enabled tools, and policy.
2. Adapter reports model/provider capabilities.
3. Registry discovers enabled tools and their schemas, capability declarations, and requirements.
4. Orchestrator selects a bounded subset and exposes provider-compatible definitions.
5. Model proposes a tool call.
6. Runtime validates identity and arguments, evaluates authorization, and requests approval when required.
7. Executor runs within configured deadlines, concurrency, resource, and output limits.
8. Normalized success/error results are returned to the model as untrusted tool data.
9. The loop continues within step/budget limits or exits for a final response, cancellation, or human input.

## Security baseline

- Treat model-generated calls, plugin metadata, fetched documents, and tool outputs as untrusted.
- Never evaluate model text as code or shell commands by default.
- No unrestricted filesystem, shell, network, or browser access by default.
- Require explicit capability grants and narrow resource scopes.
- Store credentials in a secret manager or inject them through environment-backed references; never commit or prompt-inject secrets.
- Gate destructive, externally visible, financial, account-changing, and other high-impact actions behind human approval.
- Isolate untrusted code; constrain network, filesystem, CPU, memory, execution time, output size, retries, and concurrency.
- Redact sensitive values from telemetry and maintain auditable decisions.
- Approval binds to exact action and arguments; changed arguments require re-approval.

## Roadmap

### Phase 0 — Architecture and repository
- [x] Project vision, architecture, security, tool catalog, roadmap
- [ ] Confirm initial public contracts and package metadata

### Phase 1 — Core contracts
- [ ] Shared types, configuration, errors, normalized result envelopes
- [ ] Provider adapter protocol and mock provider
- [ ] Tool protocol, metadata, JSON Schema validation and registry
- [ ] Authorization and approval interfaces
- [ ] Dispatcher with deadlines, cancellation and output limits
- [ ] Tests and CI

### Phase 2 — Minimal end-to-end runtime
- [ ] First hosted-provider adapter and second adapter
- [ ] Bounded tool-calling loop and schema translation
- [ ] Read-only web fetch and filesystem tools
- [ ] Isolated code execution prototype
- [ ] Structured tracing and usage events

### Phase 3 — Integrations
- [ ] Browser automation, documents, structured data and database adapters
- [ ] Git/development integrations
- [ ] Plugin packaging, discovery and compatibility validation

### Phase 4 — Advanced orchestration
- [ ] Parallel and dependency-aware execution
- [ ] Persistent checkpoints and resumable jobs
- [ ] Human approval workflows, delegation and scheduled tasks
- [ ] Replayable traces and budgets

### Phase 5 — Ecosystem
- [ ] TypeScript SDK and REST API
- [ ] Plugin documentation/catalog
- [ ] Distributed workers and additional integrations

Milestones are directional. An item is not complete until implementation, tests, and documentation are merged.

## Target API concept

```python
from ultk import ToolKit

toolkit = ToolKit(
    provider="provider_name",
    api_key_env="LLM_API_KEY",
    model="model_name",
    tools=["web.fetch", "documents.pdf"],
    policy="interactive",
)

result = await toolkit.run("Find the release notes and summarize them.")
print(result.text)
```

This is an illustrative target API, not an implemented interface in this architecture-only milestone. An LLM API key configures the model connection; third-party services may require separate credentials and permissions.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md), [Architecture](docs/ARCHITECTURE.md), [Security](docs/SECURITY.md), and the [verification ledger](docs/VERIFICATION_LEDGER.md).

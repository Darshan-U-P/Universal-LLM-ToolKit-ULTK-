# Universal LLM ToolKit (ULTK)

A provider-independent, extensible tool execution framework for compatible large language models.

**Status:** Active implementation. The repository contains the provider-independent runtime and incrementally delivered, capability-gated tool packs; the full target catalog and production deployment hardening are still in progress.

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

## Computer automation implementation

The advanced desktop branch adds a dedicated cross-platform computer/OS pack for persistent logical desktop contexts, monitor discovery, window placement and snapping, virtual desktops where supported, keyboard shortcuts/sequences, accessibility inspection, and bounded desktop workflows combining pointer, keyboard, window and screenshot actions.

Platform support is backend-dependent. Windows UI Automation and safe device ejection use native APIs; macOS accessibility uses the Accessibility API through PyObjC; Linux Wayland window/workspace operations have a Sway IPC backend, while Linux AT-SPI supports inspection and action invocation. Global Wayland input and native macOS Spaces management remain compositor/OS-specific limitations. See [Computer/OS Tool Pack](docs/COMPUTER_OS_TOOL_PACK.md).

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

This taxonomy is a roadmap, not an implementation inventory.

| Domain | Planned capabilities |
|---|---|
| Core | provider/model discovery, tool registry, schema validation, dispatch, retries, telemetry |
| Computer/OS | filesystem, process management, terminal, clipboard, persistent desktop contexts, multi-monitor/window/virtual desktop control, keyboard automation, accessibility and bounded GUI workflows |
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
| Advanced agents | delegation, multi-agent coordination, reflection, scheduling, resumable jobs |

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

See [CONTRIBUTING.md](CONTRIBUTING.md), [Architecture](docs/ARCHITECTURE.md), [Roadmap](docs/ROADMAP.md), [Tool Catalog](docs/TOOL_CATALOG.md), [Security](docs/SECURITY.md), and [Plugin Development](docs/PLUGIN_DEVELOPMENT.md).

## License

A license will be selected and added before the first implementation release.


## Workflow orchestration implementation

The LLM-independent workflow engine executes bounded DAGs through the same policy-gated dispatcher
as direct tool calls. It supports dependency-aware parallel steps, explicit JSON output references,
persistent SQLite checkpoints and event history, bounded retries with backoff, cooperative
cancellation, recovery after interruption, and re-execution from a saved definition. Recovery is
at-least-once: an interrupted external side effect may be repeated, so mutating tools should be
idempotent. Distributed worker coordination and exactly-once side effects are not provided.

See [Workflow Orchestration](docs/WORKFLOW_ORCHESTRATION.md) for the API, semantics, security
boundaries, and validation status.


## Visual computer automation

The computer tool packs now include an optional OCR-backed visual interaction layer. It can inspect visible text and bounding boxes, find exact text lines, click only unique matches, wait for text, scroll, drag, and execute bounded prevalidated visual workflows. Install it with `ToolEngine.install_computer_visual_tools()`; the host must separately install the Tesseract binary and required language data. See [Visual Computer Automation](docs/COMPUTER_VISUAL_AUTOMATION.md).


## Semantic browser automation

The optional semantic browser pack builds on the persistent Playwright browser sessions. It can inspect
visible page text and interactive controls, then target controls by accessible role/name, label,
visible text, placeholder, alt text or test ID. Actions require exactly one matching element and
are bounded to a fixed action/key allowlist. It also supports bounded waits for semantic targets.

Install Playwright with `pip install -e '.[browser]'` and run `playwright install chromium`.
Enable it with `ToolEngine.install_semantic_browser_tools()`. The existing
`install_advanced_browser_tools()` remains available for selector-based interactions and bounded
browser workflows. See [Semantic Browser Automation](docs/SEMANTIC_BROWSER_AUTOMATION.md).


## Comprehensive browser automation

The comprehensive Playwright pack adds persistent Chromium profiles, tabs and popup capture, iframe
interaction, cookie metadata/clearing, structured scraping, browser-triggered downloads, bounded
network inspection, a one-message WebSocket probe, browser test assertions, CAPTCHA-aware detection,
visible human login/MFA handoff, form preview with fingerprint-checked submission, and persistent
website change monitors. Form submission uses the separately gated
`browser:submit:consequential` capability; the host policy must enforce explicit human approval.

Install with `pip install -e '.[browser]'` and `playwright install chromium`. Enable with
`ToolEngine.install_comprehensive_browser_tools(profile_root=..., download_root=...)`. Protect
persistent profile directories as credential stores. Downloads are confined to a host-configured
directory and checked against a post-download byte limit. CAPTCHA is detected, never solved or
bypassed. Website monitors are host-polled, not background daemons. See
[Comprehensive Browser Automation](docs/COMPREHENSIVE_BROWSER_AUTOMATION.md).



## Image-template computer vision

The computer automation packs also include an optional OpenCV-backed image-template layer. Supply
trusted reference images in a host-configured template directory to detect known icons and controls
at multiple scales, inspect candidate coordinates and click only a unique non-overlapping match.
This complements OCR and semantic browser locators; it is template matching, not general semantic
object detection. Install with `pip install -e '.[computer-vision]'` and enable through
`ToolEngine.install_computer_vision_tools(template_root=...)`. See
[Image-Template Computer Vision](docs/COMPUTER_VISION_AUTOMATION.md).


## AI visual grounding

The desktop automation packs can also use an injected vision-model adapter to locate controls from
natural-language descriptions, without a saved template image. The host adapter receives bounded
PNG screenshot bytes and a target description, then returns candidate bounding boxes and
backend-reported confidence values. ULTK validates the candidates and clicks only when exactly one
candidate exceeds the configured threshold. No model provider or model weights are bundled.
Install desktop dependencies with `pip install -e '.[computer]'`, provide a trusted
`grounder` callable, and enable it through
`ToolEngine.install_computer_grounding_tools(grounder=...)`. See
[AI Visual Grounding](docs/AI_VISUAL_GROUNDING.md) for the adapter contract, privacy boundary and
safety limits.

## Advanced Git operations

The optional advanced Git pack adds bounded rebase, cherry-pick and revert workflows; stash
management; confined linked worktrees; allowlisted submodule operations; conflict inspection and
explicit stage selection; and host-adapted pull-request operations. Install it with
ToolEngine.install_advanced_git_tools(project_root=..., worktree_root=...).

GitHub/GitLab PR access is provided through an optional host-injected adapter; ULTK does not bundle
provider credentials or a network client. Destructive actions and PR merges have separate
capabilities. Interactive rebase todo editing, force push and automatic semantic conflict
resolution are intentionally not exposed. Git hooks and external helpers execute with host-user
privileges, so this is not an OS sandbox. See
[Advanced Git Operations](docs/ADVANCED_GIT_OPERATIONS.md).


## Documents and structured data

The optional document pack provides bounded discovery, metadata, text extraction for PDF and common Office/OpenDocument formats, and guarded PDF merge/page extraction. The structured-data pack reads and writes CSV, JSON, XML and XLSX and provides declarative, bounded ETL operations without evaluating model-supplied code.

Install with `pip install -e ".[documents,structured-data]"`. Legacy XLS and OpenDocument parsers have separate optional extras. See [Documents and Structured Data](docs/DOCUMENTS_AND_STRUCTURED_DATA.md) for capabilities, installation and security boundaries.


## Database integrations

The optional database pack connects to host-configured **SQLite, MySQL, PostgreSQL,
MongoDB and Redis** profiles. Install the needed driver extras (or all drivers with
`pip install -e ".[databases]"`) and call
`ToolEngine.install_database_tools(profiles=...)`.

SQL tools provide table/column discovery, bounded SELECT, parameterized INSERT/UPDATE/DELETE,
and atomic mutation transactions. MongoDB tools provide collection discovery, bounded filtered
find, insert, update and delete. Redis tools provide prefixed key get/set/delete, bounded SCAN,
TTL support and atomic transactions.

Connection settings and credentials are supplied only by the host application. Model calls can
select configured profile names but cannot supply DSNs, credentials or arbitrary SQL. SQL
identifiers are validated, values are parameterized, unfiltered UPDATE/DELETE is refused,
MongoDB executable operators are rejected, and Redis keys are confined to a host-configured
prefix. Mutating capabilities remain separate from reads. These controls are not a network or
database sandbox: configure least-privilege database users, TLS, firewall rules, and human
approval for sensitive writes. See [Database Integrations](docs/DATABASE_INTEGRATIONS.md).



## Persistent memory

ULTK now includes an optional SQLite-backed memory pack with session-scoped working context,
long-term episodic/semantic/procedural records, namespace isolation, hybrid vector/lexical recall,
update/forget operations and duplicate consolidation. The host binds a memory namespace to the
authenticated user and can inject trusted embedding, extraction and summarization callables. See
[Persistent Memory](docs/PERSISTENT_MEMORY.md) for installation, capabilities and privacy boundaries.


### Automatic and intelligent memory

`ToolEngine.install_memory_tools(...)` also accepts trusted host `extractor` and
`summarizer` callables. These enable context-to-memory extraction, conversation summaries,
fact/decision capture, conservative high-similarity consolidation and SQLite integrity
diagnostics. The host controls consent, model selection and scheduling; ULTK validates outputs
and records provenance. See [Persistent Memory](docs/PERSISTENT_MEMORY.md) for adapter
contracts and production-validation requirements.

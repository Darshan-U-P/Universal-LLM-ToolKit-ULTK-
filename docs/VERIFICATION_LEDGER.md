# Verification and Failure Ledger

This ledger separates implementation status from verification status. The project owner has deferred the consolidated test campaign until implementation is complete. Do not mark an item verified merely because code or a test file exists.

## Historical CI evidence

| Increment | Last known result | Notes |
|---|---|---|
| PR #2 — core runtime | Passed | Earlier CI passed after timeout/type/lint fixes. |
| PR #3 — filesystem | Passed | Earlier CI passed after filesystem tests and lint fixes. |
| PR #5 — system inspection | Passed | Run 42665510547 passed. |
| PR #6 — terminal/process management | Passed | Run 42666469124; 24 tests and Ruff passed. |
| PR #7 — initial computer/web/development | Passed | Run 42672846897 passed after import/lint fixes. |
| PR #8 — advanced computer/browser/development | Passed | Latest known run 42673036987 (run #168) completed successfully on head 0a48c0e2c986c4d69ccf07dc2e52d5059820c0ef. Earlier run 42672519333 had 16 Ruff findings; fixes were committed before the successful run. |
| PR #9+ feature branches | Not run / deferred | New security, data, document and REST integration code is committed to sequential feature branches; no CI or test suite has been run on these increments by design. Pull requests have not yet been opened. |

Historical CI does not establish Windows GUI behavior, browser integration, production security or end-to-end provider compatibility. PRs remain unmerged unless explicitly merged by the project owner.

## Current implementation branch chain

The new increments are deliberately sequential and remain unmerged:

| Increment | Branch | Current scope |
|---|---|---|
| Security/orchestration | `feat/security-approval-audit-orchestration` | Persistent exact-argument approvals, SQLite audit hash chain, bounded parallel calls, workflow DAG execution, verification ledger |
| Data/database | `feat/data-database-tool-pack` | Root-confined CSV/JSON operations, read-only SQLite query/schema, opt-in DML |
| Documents | `feat/document-extraction-tool-pack` | Bounded TXT/Markdown/PDF/DOCX/PPTX/XLSX extraction and metadata |
| REST integrations | `feat/allowlisted-rest-integrations` | Host-configured HTTPS endpoints, host-held credentials, read tools and opt-in mutation tools |\n| Provider adapter | `feat/openai-compatible-provider` | Non-streaming OpenAI-compatible chat-completions adapter for hosted HTTPS and loopback HTTP endpoints |\n| Plugin SDK/manager | `feat/plugin-sdk-and-manager` | Metadata-only entry-point discovery, host trust allowlist, API compatibility checks, enable/disable lifecycle |\n| Media processing | `feat/media-processing-tool-pack` | Bounded Pillow image tools and host-configured FFmpeg/ffprobe operations |

Latest feature branch in the current chain: `feat/plugin-sdk-and-manager` (plugin SDK and manager). The provider and plugin branches extend the REST integration branch; the media branch extends the plugin branch. The feature branches are not pull requests yet; final integration and validation will happen after implementation work is complete.

## Known failures and fixes to retain

- PR #2: asyncio timeout exception compatibility, collection typing imports, broad-exception lint annotation and output truncation newline were corrected; later CI passed.
- PR #5: process-list test was changed not to assume the test-runner PID appears in the sampled process list; later CI passed.
- PR #7: Ruff import ordering and subprocess capture style were corrected; later CI passed.
- PR #8: initial CI had pytest pass but Ruff fail (16 findings: import sorting, subprocess capture, ClassVar annotations, unused noqa/import). Fixes were committed to PR #7/PR #8 branches; latest PR #8 CI subsequently passed.
- New branches: no test/lint failures have been observed because testing is intentionally deferred. Treat all new code as unverified, not as passing.
- PR #4 was closed as superseded; do not revive it. PR #8 is based on PR #7, which is based on earlier sequential feature branches. Reconcile/retarget bases deliberately during final integration.

## Deferred verification checklist

### Core runtime and permissions
- [ ] Run full pytest and Ruff on the final integrated branch.
- [ ] Verify malformed schemas/arguments, duplicate tool IDs, timeout and cancellation behavior.
- [ ] Verify no tool runs when policy or capability authorization fails.
- [ ] Verify provider adapters and tool-call message formatting against actual providers.

### Filesystem, terminal and process controls
- [ ] Windows 11 path traversal, symlink/junction and atomic-write behavior.
- [ ] Symlink/TOCTOU race resistance; current root confinement is not an OS sandbox.
- [ ] Terminal executable alias, argument, environment, timeout, cancellation and child-tree termination on Windows and Linux.
- [ ] Verify allowlisted interpreters are not exposed to untrusted model arguments without OS isolation.
- [ ] Process PID/creation-time reuse checks and protected-process behavior.

### Computer and GUI
- [ ] Windows 11 integration tests for PyWinCtl/PyAutoGUI, title ambiguity, DPI scaling, multi-monitor coordinates and screenshots.
- [ ] Linux X11/Wayland and macOS backend support; Wayland restrictions documented.
- [ ] Desktop workflow action bounds, focus changes and accidental destructive clicks.
- [ ] Clipboard access and sensitive application interactions.

### Browser and web
- [ ] Playwright install/browser lifecycle, persistent storage permissions and session deletion.
- [ ] SSRF tests for DNS rebinding, IPv4/IPv6 private/link-local/metadata ranges, redirects and browser subresources.
- [ ] Cookie/session isolation, download path races, content-size limits and checksum mismatch behavior.
- [ ] Browser workflows across redirects, popups, tabs, frames, downloads, forms and authentication.
- [ ] Monitor scheduling, notifier failure/retry, content changes and database concurrency.
- [ ] Human approval for consequential external form submissions.

### Development tools and scheduler
- [ ] Confirm model-controlled command strings cannot bypass configured executable/argv templates.
- [ ] Test package install scripts, Git hooks/remotes, build/deploy targets and IDE launch under isolated OS accounts/containers.
- [ ] Verify API-test redirects, DNS changes, response-size limits and allowed-host policy.
- [ ] Scheduler concurrent workers, crash between claim and handler, missed intervals, idempotency and host polling.
- [ ] Cross-platform compiler/package-manager command templates.

### Approval, audit and orchestration
- [ ] Approval exact-argument binding, one-time consumption, expiry, denial, replay and concurrent retries.
- [ ] Authenticate approval actor at host UI/API; the library trusts the actor label supplied by host.
- [ ] Audit hash-chain verification, concurrent writes, tamper detection, tail-truncation detection through external checkpoints, and disk-full behavior.
- [ ] Verify audit events for success, denial, timeout, cancellation, unknown-tool paths and approved execution.
- [ ] Verify audit backend failure blocks execution before side effects; reconcile cases where final audit persistence fails after a tool has already run.
- [ ] Workflow DAG cycle detection, malformed/unknown references, concurrency, dependent-step skip, fail-fast and cancellation.
- [ ] Verify workflow results preserve approval metadata and block use of truncated output.
- [ ] Multi-process/distributed execution and durable workflow checkpoints remain unimplemented.

### Data and database
- [ ] CSV/JSON path traversal, symlink/junction races, atomic replacement and size/row caps on Windows and Linux.
- [ ] SQLite read-only authorizer denies DML, DDL, ATTACH/DETACH, PRAGMA and extension loading.
- [ ] SQLite write mode is unavailable unless host opts in; DML only, rollback on failure, parameter binding and transaction behavior.
- [ ] SQLite URI handling on Windows, concurrent writers, VM-step interruption, large fields/results and malformed SQL.
- [ ] Validate behavior against real application schemas and large databases; only SQLite is implemented in this increment.

### Documents
- [ ] Install and validate optional pypdf/python-docx/python-pptx/openpyxl dependencies.
- [ ] Malformed/encrypted PDFs, scanned PDF limitations, DOCX tables, PPTX shapes, XLSX formulas/cell types and large files.
- [ ] Parser execution in restricted worker for hostile documents; current extraction is not sandboxed.
- [ ] Confirm extraction limits, truncation metadata, worksheet/slide/page counts and Windows paths.
- [ ] OCR, layout reconstruction and document editing/conversion remain unimplemented.

### REST integrations
- [ ] Validate URL construction, encoded traversal, base path restrictions, redirects, port handling and allowed methods.
- [ ] Verify no model-controlled auth headers or credentials; missing host environment credentials fail closed.
- [ ] Test request/response size limits, timeout behavior, HTTP errors and response redaction.
- [ ] DNS rebinding/pinning and network egress enforcement; current host checks do not pin DNS.
- [ ] Verify API-specific pagination, rate limits, webhook signatures, idempotency and retry policies; not implemented.

## Current limitations / not yet implemented

- No OS/container sandbox, credential vault, authenticated approval UI/API, distributed worker, durable workflow checkpoint/replay, global rate limiter or resource quota manager.
- Scheduler supports interval jobs only and relies on host polling; no cron/one-shot daemon.
- Browser tabs/popups/frames/CAPTCHA and robust monitor retry/backoff are incomplete.
- No full Python execution environment; the restricted interpreter is intentionally not a REPL.
- Data pack currently supports CSV/JSON and SQLite only; PostgreSQL, MySQL, NoSQL, vector databases, ETL and visualization are outstanding.
- Document pack is read-only text extraction; OCR, editing, signing, redaction and conversion are outstanding.
- REST transport is not a complete OAuth implementation or vendor-specific connector.\n- Media tools currently cover image operations and FFmpeg transcodes/probing only; speech and generative media are not implemented.\n- Provider support currently covers non-streaming OpenAI-compatible chat completions only.\n- Plugin manager supports explicitly trusted Python entry points in-process; it is not a plugin sandbox or marketplace.
- Communications, media, AI/ML, cloud/infra, marketplace, TypeScript SDK and REST API server remain roadmap work.

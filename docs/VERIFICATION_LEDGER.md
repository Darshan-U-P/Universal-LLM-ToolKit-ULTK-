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

Historical CI does not establish Windows GUI behavior, browser integration, production security or end-to-end provider compatibility. PRs remain unmerged unless explicitly merged by the project owner.

## Known failures and fixes to retain

- PR #2: asyncio timeout exception compatibility, collection typing imports, broad-exception lint annotation and output truncation newline were corrected; later CI passed.
- PR #5: process-list test was changed not to assume the test-runner PID appears in the sampled process list; later CI passed.
- PR #7: Ruff import ordering and subprocess capture style were corrected; later CI passed.
- PR #8: initial CI had pytest pass but Ruff fail (16 findings: import sorting, subprocess capture, ClassVar annotations, unused noqa/import). Fixes were committed to PR #7/PR #8 branches; latest PR #8 CI subsequently passed.
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

### New approval, audit and orchestration layer
- [ ] Approval exact-argument binding, one-time consumption, expiry, denial, replay and concurrent retries.
- [ ] Authenticate approval actor at host UI/API; current library trusts the actor label supplied by host.
- [ ] Audit hash-chain verification, concurrent writes, tamper detection and disk-full behavior.
- [ ] Verify audit events for every success, denial, timeout, cancellation and unknown-tool path.
- [ ] Workflow DAG cycle detection, reference resolution, concurrency, dependent-step skip, fail-fast and cancellation.
- [ ] Verify workflow results preserve approval metadata and do not leak secrets.
- [ ] Multi-process/distributed execution and durable workflow checkpoints remain unimplemented.

## Current limitations / not yet implemented

- No OS/container sandbox, credential vault, authenticated approval UI/API, distributed worker, durable workflow checkpoint/replay, global rate limiter or resource quota manager.
- Scheduler supports interval jobs only and relies on host polling; no cron/one-shot daemon.
- Browser tabs/popups/frames/CAPTCHA and robust monitor retry/backoff are incomplete.
- No full Python execution environment; the restricted interpreter is intentionally not a REPL.
- Database, documents, communications, media, cloud/infra, AI/ML, OAuth/MCP and marketplace remain roadmap work.

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
| New feature branches after PR #8 | Not run / deferred | Security, data, documents, REST, provider, plugin, media, email, Git, PowerShell and comprehensive computer/OS additions have not had tests or CI run by design. |

Historical CI does not establish Windows GUI behavior, browser integration, production security or end-to-end provider compatibility. PRs remain unmerged unless explicitly merged by the project owner.

## Current implementation branch chain

The new increments are deliberately sequential and remain unmerged:

| Increment | Branch | Current scope |
|---|---|---|
| Security/orchestration | `feat/security-approval-audit-orchestration` | Persistent exact-argument approvals, SQLite audit hash chain, bounded parallel calls, workflow DAG execution |
| Data/database | `feat/data-database-tool-pack` | Root-confined CSV/JSON operations, read-only SQLite query/schema, opt-in DML |
| Documents | `feat/document-extraction-tool-pack` | Bounded TXT/Markdown/PDF/DOCX/PPTX/XLSX extraction and metadata |
| REST integrations | `feat/allowlisted-rest-integrations` | Host-configured HTTPS endpoints, host-held credentials, read tools and opt-in mutation tools |
| Provider adapter | `feat/openai-compatible-provider` | Non-streaming OpenAI-compatible chat-completions adapter for hosted HTTPS and loopback HTTP endpoints |
| Plugin SDK/manager | `feat/plugin-sdk-and-manager` | Metadata-only entry-point discovery, host trust allowlist, API compatibility checks, enable/disable lifecycle |
| Media processing | `feat/media-processing-tool-pack` | Bounded Pillow image tools and host-configured FFmpeg/ffprobe operations |
| Email | `feat/secure-email-tool-pack` | Host-configured TLS SMTP sender, exact/domain recipient allowlists, plain-text only |
| Git Tool Pack | `feat/git-toolkit-comprehensive` | Repository inspection, branch/index/commit/diff/merge/conflict/history and HTTPS allowlisted remote operations |
| Dedicated PowerShell | `feat/dedicated-powershell-tool-pack` | PowerShell-native system, process, service, network, registry, event, task, module and approved-script operations |
| Comprehensive computer/OS | `feat/comprehensive-computer-os-tool-pack` | Persistent logical desktop contexts, monitor/window/virtual desktop control, keyboard, accessibility, cross-platform services, filesystem permissions, Windows ACL, hardware, USB, network and event-log tools |

The provider and plugin branches extend the REST integration branch; media extends the plugin branch; email extends media; Git extends email; PowerShell extends Git; comprehensive computer/OS extends PowerShell. These are feature branches, not pull requests. Final integration and validation will happen after implementation work is complete.

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

### Provider adapters
- [ ] Validate hosted provider authentication, local Ollama-compatible endpoints, endpoint path construction, same-origin redirects and response parsing.
- [ ] Test tool-call parsing against real OpenAI-compatible providers and confirm schema compatibility across vendors.
- [ ] Add streaming, usage accounting, rate-limit/backoff and provider capability negotiation; these are not implemented.

### Plugin SDK and manager
- [ ] Validate metadata-only discovery, explicit trust gating, API compatibility, atomic registration, disable behavior and duplicate entry points.
- [ ] Verify untrusted plugin modules are never imported before explicit enablement.
- [ ] Package and install a real third-party test plugin from a wheel.
- [ ] Add signed manifests, dependency resolution, isolated plugin workers and hot-reload; these are not implemented.

### Media processing
- [ ] Validate Pillow optional dependency, image metadata, alpha flattening, resize, conversion, decompression-bomb limits and output atomicity.
- [ ] Validate FFmpeg/ffprobe executable configuration, codec availability, output detection, partial-output cleanup, timeouts and process cancellation.
- [ ] Test large media files, corrupted inputs, path traversal and Windows/Linux path behavior.
- [ ] Speech-to-text, diarization, TTS, subtitle generation and AI media generation remain unimplemented.

### Email and communications
- [ ] Validate SMTP-over-TLS and STARTTLS, credential loading/rotation, recipient allowlists, partial refusal and timeout behavior.
- [ ] Require exact-argument human approval for externally visible email sends.
- [ ] Test SMTP provider compatibility and message encoding.
- [ ] Inbox reading, attachments, OAuth mail APIs, calendar, contacts, SMS and messaging APIs remain unimplemented.

## Current limitations / not yet implemented

- No OS/container sandbox, credential vault, authenticated approval UI/API, distributed worker, durable workflow checkpoint/replay, global rate limiter or resource quota manager.
- Scheduler supports interval jobs only and relies on host polling; no cron/one-shot daemon.
- Browser tabs/popups/frames/CAPTCHA and robust monitor retry/backoff are incomplete.
- No full Python execution environment; the restricted interpreter is intentionally not a REPL.
- Data pack currently supports CSV/JSON and SQLite only; PostgreSQL, MySQL, NoSQL, vector databases, ETL and visualization are outstanding.
- Document pack is read-only text extraction; OCR, editing, signing, redaction and conversion are outstanding.
- REST transport is not a complete OAuth implementation or vendor-specific connector.
- Provider support currently covers non-streaming OpenAI-compatible chat completions only.
- Plugin manager supports explicitly trusted Python entry points in-process; it is not a plugin sandbox or marketplace.
- Media tools cover image operations and FFmpeg transcodes/probing only; speech and generative media are not implemented.
- Communications currently includes plain-text SMTP sending only.
- Cloud/infra, AI/ML, marketplace, TypeScript SDK and REST API server remain roadmap work.


### Git Tool Pack — branch feat/git-toolkit-comprehensive
- [ ] Implementation added as src/ultk/builtins/git.py; tests authored in tests/test_git_tools.py; tests and CI deliberately not run.
- [ ] Scope: repository inspection, branch lifecycle, staging/unstaging/commits, working/staged/commit diffs, merge start/abort/complete, conflict listing/resolution, history/show/blame/tags, and HTTPS-allowlisted remote management/fetch/pull/push.
- [ ] Verify subprocess timeout/cancellation: synchronous subprocess work runs in a worker thread; cancellation may not terminate the Git child process immediately.
- [ ] Verify Git config threat model, hooks disabled, external diff/textconv disabled, pager disabled, system config disabled, protocol allowlist and credential helper behavior across supported platforms.
- [ ] Verify remote URL validation including malformed ports, IPv6, encoded userinfo, redirects, URL rewrites, credential helpers, DNS rebinding and HTTP redirect behavior.
- [ ] Verify push URL separately from fetch URL; verify local remote.pushurl cannot bypass the host allowlist.
- [ ] Verify pathspec literal behavior for Unicode, newline, colon, leading dash, Windows separators, symlinks/junctions, case-insensitive filesystems and deleted paths.
- [ ] Verify conflict parsing for paths containing tabs/newlines/non-UTF-8 bytes; current output decoding is UTF-8 replacement and NUL-delimited path parsing needs byte-level validation.
- [ ] Verify merge lifecycle for fast-forward, already-up-to-date, conflicts, unrelated histories, merge hooks disabled and abort after partially resolved files.
- [ ] Verify branch/revision validation against Git's full refname rules; current conservative validators may reject valid refs.
- [ ] Verify remote pull/push semantics and credentials on real GitHub/GitLab test repositories; push is an externally visible mutation and must require host approval.
- [ ] Review whether repository-local config can execute filters or credential helpers; untrusted repositories require OS sandboxing.
- [ ] Confirm capability policies can separately gate each mutating operation.


### Dedicated PowerShell Tool Pack — branch feat/dedicated-powershell-tool-pack
- [ ] Implementation added in src/ultk/builtins/powershell.py; tests authored in tests/test_powershell_tools.py; tests and CI deliberately not run.
- [ ] Dedicated fixed-cmdlet operations: location/environment, OS/computer/hotfix, process/service, IP/TCP/DNS/firewall, registry read, event logs, scheduled tasks, module discovery, WS-Man reachability, PowerShell script parsing.
- [ ] Optional script execution requires host-pinned script IDs and SHA-256 hashes; verify race resistance between hash check and execution, symlink/junction behavior, and script-root permissions.
- [ ] Verify PowerShell 7 and Windows PowerShell 5.1 behavior, encoded command parsing, UTF-8 output, JSON serialization of CIM objects, arrays/null/singletons and error stream handling.
- [ ] Verify Windows-only cmdlets and optional NetTCPIP/NetSecurity/ScheduledTasks modules across Windows 10/11 and Server SKUs; confirm missing cmdlets fail cleanly.
- [ ] Verify environment filtering; environment values are now returned only for host-allowlisted names (empty by default); verify this remains fail-closed and add secret-pattern redaction before production.
- [ ] Verify service and scheduled-task mutations with least-privilege identities, approval gates, UAC boundaries and protected/system services.
- [ ] Verify registry path validation, provider-path injection resistance and 32/64-bit registry view behavior.
- [ ] Verify event-log query performance, Security log access-denied handling and message/output caps.
- [ ] Verify timeout and child-process cleanup; subprocess.run timeout kills the PowerShell process but may leave child processes spawned by approved scripts.
- [ ] Verify module discovery does not trigger unsafe module auto-loading; host-allowlisted modules must be treated as trusted executable code.
- [ ] Verify WS-Man test behavior, host allowlisting, authentication configuration and network egress controls. General-purpose remote command execution is not implemented.
- [ ] Confirm script execution capability powershell:script:execute and all service/task mutation capabilities are approval-gated by production host policy.
- [ ] Validate on the user's Windows 11 environment; no Windows integration tests or CI have been run for this increment.


### Comprehensive Computer and Operating-System Pack — branch feat/comprehensive-computer-os-tool-pack
- [ ] Implementation added in src/ultk/builtins/computer_os.py; 30 FunctionTool operations are registered by ToolEngine.install_computer_os_tools; tests authored in tests/test_computer_os_tools.py; no tests, Ruff, mypy, packaging checks or CI have been run.
- [ ] Persistent desktop sessions are logical SQLite-backed ULTK context records, not actual Windows logon sessions or isolated desktop processes. Verify session ownership/authentication at the host layer, concurrent updates, SQLite locking, state limits and lifecycle semantics.
- [ ] Validate PyWinCtl window discovery/action behavior on Windows 11, Linux X11, Wayland and macOS; verify title uniqueness, hidden/minimized windows, DPI scaling, multi-monitor negative coordinates, stale windows, close behavior and race conditions.
- [ ] Validate screeninfo monitor enumeration and primary-display fallback on all supported display servers; verify monitor rotation, scaling, hotplug and virtual display geometry.
- [ ] Validate Windows pyvda API/version compatibility and desktop numbering; current Windows enumeration is only a current-desktop view. Linux virtual desktop support requires wmctrl/X11; Wayland and macOS switching are not implemented.
- [ ] Validate keyboard mapping for Windows/Linux/macOS, shortcut ordering, dead keys, Unicode typing, secure-attention sequence blocking, partial workflow failures and foreground-window focus. Keyboard actions can cause irreversible changes in active applications.
- [ ] Validate Windows UI Automation with pywinauto on real applications; test duplicate automation IDs, stale controls, modal dialogs, UAC secure desktop, elevated applications and invoke-vs-click semantics.
- [ ] Validate Linux AT-SPI installation and traversal on GNOME/KDE; check inaccessible applications, recursion bounds, stale accessibility nodes and desktop service availability. AT-SPI element invocation is not implemented.
- [ ] Validate service inventory and mutation command semantics on Windows SCM and Linux systemd; exact host allowlist is required. Check permission errors, dependencies, service name casing and start/stop/restart result codes. macOS launchd is list-only.
- [ ] Validate POSIX chmod/chown semantics, uid/gid behavior, sticky/setuid/setgid bit restrictions, symlink/junction races, hard links and filesystem TOCTOU. chown is disabled by default.
- [ ] Validate Windows icacls parsing and ACL grant semantics on NTFS/ReFS, SID allowlisting, inherited ACE behavior, object/container ACL behavior and error reporting. ACL changes are disabled by default; R/RX/M only.
- [ ] Validate hardware inspection across Windows/Linux/macOS, missing sensor APIs, permission errors, removable/network filesystems, disk enumeration and potentially sensitive network/device metadata.
- [ ] Validate USB enumeration on Linux pyudev, Windows pnputil and macOS system_profiler; output parsing, locale differences, device count limits, serial privacy and driver/device permissions.
- [ ] Validate Linux/macOS safe eject with exact device allowlists, busy mount handling, multi-partition devices and data-loss prevention. Windows safe eject is not implemented.
- [ ] Validate Windows wevtutil XPath query and XML namespace parsing, Linux journalctl since/channel behavior, macOS log show output format, privilege restrictions, truncation and secret-sensitive event data.
- [ ] Event watches are persisted definitions only; host scheduler polling is required. Background daemon, incremental cursor/checkpoint, deduplication and notification delivery are not implemented.
- [ ] Validate subprocess output draining/capping, timeout kill behavior, child-process cleanup, command availability, restricted OS/display environment and Windows process handle behavior.
- [ ] Verify secure attention sequence Ctrl+Alt+Delete is rejected by both standalone shortcut and sequence validation.
- [ ] Verify Windows ACL grant uses only numeric host-allowlisted SIDs and R/RX/M rights, with no recursive or Full Control grants.
- [ ] Verify device eject requires exact host-allowlisted identifiers and is rejected on Windows; test busy-device and in-flight I/O handling on Linux/macOS.
- [ ] pyproject.toml had a malformed literal escaped newline between optional dependency declarations in the parent branch; this branch rewrites it as valid separate TOML entries and adds the computer-os extra. Verify TOML parsing, wheel build and installation of platform markers.
- [ ] Validate optional dependency installation and imports: PyWinCtl, PyAutoGUI, screeninfo, pywinauto, pyvda, pyudev and system-level AT-SPI bindings.
- [ ] No Windows 11, Linux X11/Wayland or macOS end-to-end integration tests have been run for this increment.


## Multi-monitor cross-platform desktop automation increment

- Branch: feat/multi-monitor-cross-platform-desktop-automation
- Base: feat/advanced-computer-browser-development (PR #8 head)
- Added computer_os pack integration through ToolEngine.install_computer_os_tools.
- Added monitor enumeration, monitor-relative window snapping/arrangement, desktop sessions,
  virtual desktop controls where supported, accessibility inspection, and bounded desktop
  workflows combining pointer, keyboard, window and screenshot actions.
- Added authored unit tests for workflow prevalidation, pointer/keyboard dispatch, negative
  monitor origins and tool registration.
- Tests and CI intentionally not executed; final validation remains deferred by project policy.
- Platform checks still required: Windows 10/11, macOS supported releases, Linux X11, and
  documented Linux Wayland limitations. Validate optional native dependencies and GUI sessions.
- Known limitations: macOS accessibility element invocation and virtual-desktop control are
  not implemented; Linux Wayland global input/window control depends on compositor support;
  Windows safe USB eject and some OS-administration operations remain outside this increment.


## Durable workflow orchestration increment

- Branch: feat/durable-workflow-orchestration
- Base: feat/multi-monitor-cross-platform-desktop-automation (PR #9 head).
- Added a persistent SQLite workflow DAG engine in src/ultk/orchestration.py.
- Supports explicit dependency edges, ancestor-only JSON Pointer output references, bounded parallel
  execution, bounded exponential retries, dependency-failure skips, fail-fast, cooperative
  cancellation, step/run checkpoints, event history, recovery of orphaned in-flight steps, and
  re-execution from a saved definition.
- Integrated through ToolEngine.create_workflow_engine and public WorkflowStep/WorkflowEngine exports.
- Added tests/test_orchestration.py and docs/WORKFLOW_ORCHESTRATION.md.
- GitHub Actions run #505 completed successfully against the synchronized workflow and desktop
  code: pytest passed (69 tests) and Ruff passed. The earlier workflow-module and inherited desktop
  lint findings have been corrected. The verification commit after this run changes only this
  ledger entry; no runtime code changed after the successful run.
- Mypy, Windows/macOS/Linux desktop integration, SQLite crash/disk-full, multi-process execution,
  and external-side-effect idempotency checks remain pending.
- Recovery is at-least-once. A crash after an external side effect but before checkpoint persistence
  can cause a repeated tool call. Exactly-once side effects and distributed worker leasing are not
  implemented. Recovery must only be run after the prior worker is stopped.
- Cancellation is cooperative between workflow scheduling batches; in-flight tools finish under
  their own dispatcher timeout. Replay creates a fresh run and re-executes tools; it is not
  deterministic playback or rollback.
- Verify DAG cycle and unknown-reference validation, JSON Pointer escaping/indexes, step and
  concurrency bounds, dependency skip/fail-fast semantics, retry persistence/backoff, concurrent
  cancellation, crash recovery, replay definition fidelity, SQLite locking/corruption/disk-full,
  secret-bearing argument/output storage, and multiple simultaneous workflow runners.


## Visual computer automation increment

- Branch: feat/visual-computer-automation
- Base: feat/durable-workflow-orchestration (PR #10 head).
- Added src/ultk/builtins/computer_visual.py with OCR-backed screen text extraction, exact line
  matching, unique-match text clicking, bounded wait-for-text polling, scroll, drag, and a
  prevalidated visual desktop workflow.
- Added ToolEngine.install_computer_visual_tools and the public built-in factory export.
- Added the optional computer-visual dependency group; Tesseract executable and language data are
  host-installed system dependencies, not installed by pip.
- Added tests/test_computer_visual_tools.py and docs/COMPUTER_VISUAL_AUTOMATION.md; README and tool
  catalog updated.
- Tests and Ruff must be confirmed by GitHub Actions after the PR is opened. No platform integration
  test has yet been run.
- Validate OCR language allowlists, Tesseract version/language availability, OCR confidence and
  coordinate accuracy, false/duplicate matches, monitor coordinate transforms, screen scaling,
  screenshot backend differences, OCR timeout/cancellation, and sensitive visible text handling.
- Visual workflow prevalidation checks all step schemas and bounds before actions begin, but runtime
  OCR and OS failures can occur after earlier steps have executed. No rollback/transaction is claimed.
- This increment does not add image-template matching, semantic object recognition, screenshot
  streaming, or unattended background desktop sessions.
- GitHub Actions run #527 completed successfully on commit 36e204d: pytest passed (84 tests) and
  Ruff passed. The only failures in earlier runs were corrected: the configured OCR line cap now
  supplies the default, the aggregate-wait test exceeds the limit it asserts, and two unused-code
  lint findings were removed. Platform-specific GUI/Tesseract integration tests remain pending.


## Semantic browser automation increment

- Branch: feat/semantic-browser-automation
- Base: feat/visual-computer-automation (PR #11 head).
- Added src/ultk/builtins/browser_semantic.py with bounded interactive-control inspection,
  accessible-role/label/text/placeholder/alt/test-id targeting, unique-match interaction, and
  bounded semantic target waits.
- Added ToolEngine.install_semantic_browser_tools, the public factory export, focused unit tests,
  and docs/SEMANTIC_BROWSER_AUTOMATION.md. Reuses the existing Playwright session and network guard.
- Authored tests cover registration, engine integration, exact semantic locators, ambiguity/missing
  target fail-closed behavior, action/key validation and wait bounds. CI must be run after PR creation.
- The inspection name is a DOM-derived approximation rather than a complete browser accessibility
  tree. Platform/browser behavior and live-site workflows still require integration testing.
- Browser session calls reopen Chromium per invocation and restore storage plus the last URL; live
  browser-process state and multiple tabs are not persisted.
- This increment does not add CAPTCHA solving, anti-bot evasion, frame targeting, upload/download
  flows, browser extensions or network egress isolation. URL validation is not a complete SSRF
  boundary; enforce host/network-level egress controls.


## Image-template computer vision increment

- Branch: feat/image-template-computer-vision
- Base: feat/semantic-browser-automation (PR #12 head).
- Added src/ultk/builtins/computer_vision.py with multi-scale grayscale OpenCV template matching,
  non-maximum overlap suppression, bounded candidate inspection, unique-match clicking and
  bounded wait-for-template polling.
- Templates are host-supplied image files confined to a configured directory; extension, file
  size, image pixel count, capture area, threshold, candidate count and wait bounds are restricted.
- Added ToolEngine.install_computer_vision_tools, public factory export, optional
  computer-vision dependency extra, focused unit tests and dedicated documentation.
- This is deterministic image-template matching for known reference images, not general semantic
  object detection or a learned visual grounding model. Appearance changes, animation, DPI scaling,
  theme changes and anti-aliasing can reduce match scores.
- Unit tests cover registration, engine integration, path confinement, image extension/size limits,
  match bounds, overlap calculations, unique-match click safety, and wait bounds. CI result pending.
- Validate OpenCV behavior and false-positive rates against real screenshots on Windows, macOS and
  Linux; test high-DPI/multi-monitor scaling, theme/zoom changes, animated controls, image formats,
  template quality, CPU/memory load and capture backend behavior.
- Desktop clicks remain externally visible host actions. Grant computer:screen:read and
  computer:screen:control separately, and require human approval for high-impact actions.
- PR #12 semantic browser automation CI run #535 completed successfully after its import-order fix.

- GitHub Actions run #540 on commit 263a40b completed successfully: 107 tests passed and Ruff passed.
  The preceding run #537 passed all tests but exposed two Ruff sorting findings in built-in exports;
  the export order was corrected in commit 263a40b. A further test now exercises the matching
  pipeline with stubbed OpenCV/PyAutoGUI boundaries; real OpenCV and live-desktop integration
  remain separate validation requirements.


## AI visual grounding increment

- Branch: feat/ai-visual-grounding
- Base: feat/image-template-computer-vision (PR #13 head).
- Added src/ultk/builtins/computer_grounding.py with a host-injected VisualGrounder adapter
  contract, bounded screenshot capture, natural-language target descriptions, candidate-box
  validation, confidence filtering, and unique-candidate-only clicking.
- Added ToolEngine.install_computer_grounding_tools and the public built-in factory export.
- Added tests/test_computer_grounding_tools.py and docs/AI_VISUAL_GROUNDING.md.
- The pack is provider/model independent: it does not bundle model weights, provider SDKs,
  network clients, or credentials. The host adapter is trusted in-process application code.
- Unit tests cover registration, engine installation, screenshot/target handoff, region coordinate
  offsets, confidence filtering, malformed/out-of-bounds candidate rejection, missing/failing
  backends, ambiguity rejection, unique-match click coordinates and candidate bounds.
- GitHub Actions run #562 on commit 59173c1 completed successfully: 124 tests passed and Ruff passed.
  Earlier CI findings were corrected: a test assertion-message regex, unused import and redundant casts,
  a loop-variable closure binding, and the public __all__ ordering.
- Live model quality, latency, privacy/data-transfer, real screenshot capture and cross-platform
  coordinate integration remain unverified.
- Backend-reported confidence is not assumed to be calibrated. A unique candidate may still be
  incorrect; high-impact actions require host approval bound to the exact arguments and fresh
  screenshot context. Screenshots may contain sensitive content, and hosted adapters may transmit
  it externally.


### Platform-specific desktop automation completion — branch feat/platform-desktop-automation-completion

- Base: PR #14 visual-grounding head (commit 7add4ed8b92a6656449357db1a43abbc40ba6640).
- Added macOS Accessibility API inspection and exact identifier/title AXPress invocation using PyObjC. The host process must be granted macOS Accessibility permission; calls fail closed when AX trust is not granted.
- Added Linux AT-SPI exact accessible-name action invocation; ambiguous element names fail closed.
- Added a Sway IPC backend for Linux Wayland window enumeration, unique-title activate/close/move/resize/fullscreen/restore actions, and workspace list/current/create/switch. Sway IPC socket and swaymsg must be available. This does not claim generic support for all Wayland compositors or global pointer/keyboard input.
- Added Windows safe USB device ejection through Configuration Manager CM_Locate_DevNodeW and CM_Request_Device_EjectW, gated by exact host-configured device instance ID allowlist. Busy-device vetoes are returned; force removal is not attempted.
- Added focused backend tests in tests/test_computer_os_platform_backends.py; tests and CI remain deferred under the current implementation-phase validation policy.
- Added macOS PyObjC framework dependencies to the computer-os extra and updated the platform coverage documentation.
- Still outside this desktop-automation increment: native macOS Spaces management (private APIs intentionally avoided), non-Sway Wayland compositor adapters and global Wayland input, recursive/inherited Windows ACL and owner changes, USB driver installation/configuration, isolated OS desktop sessions, and background event-monitor daemons. These require separate OS-specific design/privilege boundaries and are not represented as implemented.
- Cross-platform native integration is not verified merely by unit tests. Validate on Windows 10/11, macOS with Accessibility permission, Linux X11, and Sway/Wayland before production use.

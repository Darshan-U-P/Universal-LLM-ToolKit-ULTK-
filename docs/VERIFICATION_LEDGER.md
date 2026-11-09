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
| New feature branches after PR #8 | Not run / deferred | Security, data, documents, REST, provider, plugin, media, email, Git, PowerShell, comprehensive computer/OS and advanced PowerShell administration additions have not had tests or CI run by design. |

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
| Advanced PowerShell administration | `feat/advanced-powershell-administration` | 70 tools: restricted persistent runspaces, persistent WinRM PSSessions, registry/firewall/identity/update/storage/certificate/package/AD/GPO/task/security policy and SHA-256-pinned security templates |

The provider and plugin branches extend the REST integration branch; media extends the plugin branch; email extends media; Git extends email; PowerShell extends Git; comprehensive computer/OS extends PowerShell; advanced PowerShell administration extends comprehensive computer/OS. These are feature branches, not pull requests. Final integration and validation will happen after implementation work is complete.

## Known failures and fixes to retain

- PR #2: asyncio timeout exception compatibility, collection typing imports, broad-exception lint annotation and output truncation newline were corrected; later CI passed.
- PR #5: process-list test was changed not to assume the test-runner PID appears in the sampled process list; later CI passed.
- PR #7: Ruff import ordering and subprocess capture style were corrected; later CI passed.
- PR #8: initial CI had pytest pass but Ruff fail (16 findings: import sorting, subprocess capture, ClassVar annotations, unused noqa/import). Fixes were committed to PR #7/PR #8 branches; latest PR #8 CI subsequently passed.
- New branches: no test/lint failures have been observed because testing is intentionally deferred. During the advanced PowerShell implementation, an automated edit temporarily displaced a scheduled-task path validation line; it was corrected before the final branch head. Treat all new code as unverified, not as passing.
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


### Advanced PowerShell Administration — branch feat/advanced-powershell-administration
- [ ] Added src/ultk/builtins/powershell_advanced.py, ToolEngine.install_advanced_powershell_tools, exports, docs/POWERSHELL_ADVANCED_TOOL_PACK.md and tests/test_powershell_advanced.py. The advanced factory currently declares 71 distinct FunctionTool operations, including separately permissioned scheduled-task create/update/delete; tests, Ruff, mypy, packaging checks and CI have not been run.
- [ ] Persistent local sessions use one long-lived PowerShell process per ULTK session, capped at 16 sessions per manager. Verify session startup protocol, UTF-8 input/output, one-element and array JSON handling, concurrent calls, dead-process cleanup, timeout behavior, memory growth and session close.
- [ ] Verify session variable persistence and isolation across two sessions; variable inspection excludes internal protocol variables. Host must bind session IDs to authenticated principals, authorize every request against ownership, enforce idle expiration and close sessions on logout. Session processes are in-memory only and do not survive application restart.
- [ ] The persistent-session AST gate permits only host-allowlisted cmdlets plus a restricted syntax subset; aliases, dynamic command names, member/method access, type expressions, subexpressions, scriptblocks, redirection, functions/classes, loops and control flow are rejected. Validate AST bypasses, unusual AST nodes, variable scope, automatic variables, command parameter edge cases and PowerShell 5.1/7 parser differences.
- [ ] AST validation is not an OS sandbox. Host-allowlisted cmdlets are trusted code and can still read data or cause side effects through their own parameters. Review every host session command allowlist; keep file writes, process termination, service changes and administrative mutations in their dedicated tools.
- [ ] Multi-step session workflows validate all steps before execution and run sequentially. A runtime failure can occur after earlier steps have changed state; no rollback/transaction exists. Verify partial results, output caps, cancellation and timeout handling.
- [ ] Persistent WinRM sessions create a PSSession in the local long-lived process; remote calls invoke only host-allowlisted cmdlets with data-only arguments. Verify New-PSSession/Invoke-Command/Remove-PSSession semantics, UseSSL, Windows integrated authentication, certificate validation, host identity, WinRM listener/firewall configuration, remote session persistence, idle timeout and cleanup after process crash.
- [ ] Persistent WinRM is currently Windows-host-only. Remote PSSessions may remain on the remote endpoint until WinRM idle timeout if the local process is forcibly terminated. No SSH remoting transport or model-supplied credentials are implemented.
- [ ] Verify one-shot and persistent remote invocation parameter serialization, arrays, empty parameter dictionaries, cmdlet resolution on remote hosts, module auto-loading, output serialization, timeout and remote process/resource cleanup. Remote allowlisted modules/cmdlets are trusted code.
- [ ] Registry write operations are constrained to host-configured registry subtrees and concrete provider paths; validate prefix-boundary bypasses, provider path normalization, 32/64-bit views, value types, binary/multi-string serialization, default values, empty-key deletion and registry ACL failures.
- [ ] Firewall create/enable/disable/remove operations require exact host-allowlisted rule names. Validate rule-name collisions, port/protocol combinations, profile behavior, Windows Firewall policy precedence and rollback after partial failures.
- [ ] Local user/group operations require exact account/group allowlists. Verify password environment secret handling, password policy, secret non-disclosure, privileged group membership, local account module availability, UAC and partial account mutation failures.
- [ ] Windows Update listing/history/install requires host-trusted PSWindowsUpdate; install is disabled by default and limited to allowlisted KB IDs with automatic reboot suppressed. Verify module versions/repositories, KB matching, download/install semantics, reboot suppression, update failure states and maintenance-window approval.
- [ ] Disk/partition/volume operations require allowlisted disk numbers and allow_storage_mutations opt-in. Drive-letter and volume-label operations require allowlisted letters. Boot/system disks cannot be taken offline and boot/system partitions cannot be resized. Verify RAW-only initialization, partition free-space bounds, shrink/grow semantics, protected partitions, online/offline behavior, drive-letter collisions, volume labels and data-loss protections. Formatting, deletion and disk cleaning are intentionally not implemented.
- [ ] Certificate store operations require exact store allowlists; import is limited to public CER/CRT/DER files under working_root; removal requires exact pinned thumbprints. Verify certificate path races, store ACLs, thumbprint normalization, private-key behavior, LocalMachine trust-anchor impact and certificate provider semantics.
- [ ] Module/package installation requires exact module/package versions and repository/source allowlists. Verify package provider behavior, repository trust, signature/hash validation, installation scripts, version pinning, uninstall semantics and supply-chain risks.
- [ ] Active Directory and Group Policy operations require ActiveDirectory/GroupPolicy in the base trusted-module allowlist plus exact domain, group/member DN, separately scoped AD provisioning OU, GPO target OU, GPO and policy-key allowlists. Verify RSAT module compatibility, DN parsing/escaping, search-base domain containment, AD user creation/password secret handling, identity collisions, group membership changes, GPO link/unlink/delete semantics, policy value types and domain permissions.
- [ ] Scheduled task create/update/delete now have distinct tool names and capabilities. Create refuses an existing task; update refuses a missing task; both use host-fixed executable/argument/working-directory templates, exact task names/paths and Limited current-user principals. Verify task path handling, Once/Daily/Weekly trigger behavior, time-zone/time semantics, task replacement, template executable identity, task permissions and delete behavior.
- [ ] Security policy inspection now exports local secedit policy, account policy, audit policy, Defender preferences/status and firewall profiles. Verify export permissions, localization, output sensitivity and parser/output limits.
- [ ] Security policy changes require allow_security_policy_changes; disabling audit outcomes additionally requires allow_audit_disable. Defender operations only enable selected hardening features. Verify auditpol localization, subcategory allowlists, Defender Tamper Protection, GPO precedence, cmdlet parameter compatibility and least-privilege failures.
- [ ] Local secedit template application requires a host-approved relative INF path, SHA-256 pin, private staging copy and an explicit list of secedit areas. Verify source/staging TOCTOU resistance, hash mismatch handling, allowed area semantics, database lifecycle, secedit exit codes, partial-application recovery and rollback procedures.
- [ ] AD user creation uses a host-injected password environment secret and exact expected user DN/OU allowlists. Verify sAMAccountName constraints, password complexity, secret redaction and AD module failure behavior.
- [ ] PowerShellToolPack._run was changed from subprocess.run capture to threaded bounded pipe draining, including host-injected ULTK_ secret environment values. Verify output caps under sustained stdout/stderr, pipe deadlocks, timeout/child-process cleanup, UTF-8, Windows handle behavior and secret non-disclosure.
- [ ] Verify the advanced factory tool count (currently 71 unique tool names) and schemas, duplicate tool registration behavior, ToolEngine installer options (including explicit allow_insecure_remoting), FunctionTool timeout interactions, capability declarations and human-approval policy for every state-changing capability.
- [ ] Verify host policy validation for command allowlists, remote hostname/FQDN/IPv4 allowlists (single host only), non-SSL WinRM opt-in, separate AD provisioning OU versus GPO link-target allowlists, package/module versions, drive letters, task paths and security-template hashes.
- [ ] Verify PowerShell common-parameter alias blocking (OutVariable, ErrorVariable, PipelineVariable and related aliases) prevents persistent-session scripts from overwriting runspace protocol/authorization state. Verify Write-Host, transcript, debugging and module-loading cmdlets remain blocked in restricted sessions.
- [ ] Verify all new behavior on Windows 11 with PowerShell 7 and Windows PowerShell 5.1 where supported; test RSAT, WinRM, PSWindowsUpdate, NetSecurity, Storage, LocalAccounts, PKI and ScheduledTasks modules. No Windows integration tests or CI have been run for this increment.


#### Advanced PowerShell review fixes — not yet verified
- [ ] The advanced module contained a truncated security_inspect Python string and an appended duplicate factory/class tail that made the module structurally invalid. The method was reconstructed from the intended secedit/audit/Defender inspection workflow and the duplicate tail removed. Verify import/AST parsing and security inspection output on Windows.
- [ ] ToolEngine now exposes allow_insecure_remoting as a top-level host configuration parameter and prevents overriding it through advanced_policy; verify installer forwarding and that SSL remains default/mandatory unless explicitly opted out.
- [ ] Added powershell.update_scheduled_task with powershell:tasks:update; create now refuses overwrite and update requires an existing task. Verify PowerShell if/else result assignment, Register-ScheduledTask behavior, schedules, and distinct capabilities.
- [ ] partition_create now checks any requested drive letter against the host allowlist; partition resizing rejects boot/system partitions. Verify on test disks and ensure no destructive operations occur on protected disks.
- [ ] Registry key deletion now refuses to delete the configured allowlist root itself; verify non-recursive deletion behavior for keys containing subkeys and values.
- [ ] Certificate import rejects symlink components in addition to absolute/parent-traversal paths. Verify Windows junction/reparse-point races and file replacement between validation and import.
- [ ] AD user/group search bases now require the domain DN itself or a comma-delimited DN suffix, avoiding loose string-suffix matching. Verify escaped RDNs, nested OUs, alternate distinguished-name representations and domain normalization.
- [ ] One-shot and persistent remoting parameter objects distinguish omitted None from other falsey invalid values and reject non-finite JSON numbers. Verify scalar/list serialization, empty object behavior and malformed payload rejection.
- [ ] Host boolean policy flags are type-checked, and allow_audit_disable=True requires allow_security_policy_changes=True. Verify every factory and ToolEngine configuration path.
- [ ] Local user descriptions now accept an omitted/empty description without passing an empty string through the non-empty text validator. Verify local account provisioning and secret redaction.
- [ ] Boot/system disk offline protection was added in the final review; verify it on Windows Storage cmdlets and confirm the returned state matches actual disk state.
- [ ] No tests or CI have been run for these review fixes by design.


### Comprehensive Web and Browser Control — branch feat/comprehensive-web-browser-control
- [ ] Added src/ultk/builtins/browser_comprehensive.py, ToolEngine.install_comprehensive_browser_tools, factory export, docs/COMPREHENSIVE_BROWSER_TOOL_PACK.md and tests/test_browser_comprehensive.py. Tests, Ruff, mypy, packaging checks and CI are deliberately deferred.
- [ ] Tool families: named browser profiles with persisted Playwright storage state; tab list/create/select/close; popup capture; iframe read/click/fill; cookie metadata/clear; host-trusted extension loading; selector-based structured scraping; request/response/failure/WebSocket metadata; one-shot text WebSocket probe; CAPTCHA/anti-bot detection; login-selector authentication heuristic; form preview and approval-gated form submission; bounded application smoke tests; persistent website change monitors with optional host notifier.
- [ ] Browser profile storage contains cookies/local storage and may contain bearer credentials. Validate restrictive directory permissions, encryption-at-rest integration, profile ownership/isolation, clone semantics, deletion and backup/restore. The implementation does not encrypt profile state itself.
- [ ] Browser tabs are restored by saved URL and profile storage state; exact live tabs, JavaScript heaps, in-flight requests, browser process and WebSocket sessions are not persistent. Confirm product documentation and API semantics do not imply otherwise.
- [ ] Browser contexts launch per tool call. Validate Playwright sync API threading, startup/shutdown cost, Chromium version, Windows/macOS/Linux support, concurrent calls on one profile, SQLite manifest races and profile-state file races.
- [ ] Popup capture: verify popup/new-page timing, blocked popups, same-page target=_blank behavior, redirects, opener relationships and active-tab persistence. Test multiple popup pages and close events.
- [ ] Iframe interaction: test same-origin/cross-origin frames, nested frames, detached frames, shadow DOM boundaries, dynamic selectors, frame navigation and cross-origin restrictions.
- [ ] Extension integration loads only host-configured directories and requires headed Chromium. Validate Chromium launch args, Manifest V2/V3 support, background service workers, extension permissions, path symlinks, untrusted extension code and extension isolation. Extension install/update/signature lifecycle is not implemented.
- [ ] Cookie listing intentionally omits values; clearing supports all cookies or one named cookie. Validate cookie domain scoping, SameSite/partitioned cookies, expiry, storage-state persistence, localStorage exposure and per-profile access controls. Cookie import/export and secret-manager integration are not implemented.
- [ ] Network inspection captures bounded metadata only during the current navigation/action; it does not collect full HAR payloads, response bodies, TLS details, request replay or arbitrary CDP events. Validate event registration order, cap/truncation reporting, large pages and WebSocket event coverage.
- [ ] WebSocket probe validates a public HTTP(S)-mapped host before opening ws/wss, sends one text message and captures one reply. Validate ws/wss URL parsing, redirects, TLS, handshake auth, timeout cleanup, binary frames, large frames and DNS rebinding. Persistent duplex sockets and binary interaction are not implemented.
- [ ] URL checks rely on DNS resolution and Playwright routing; DNS rebinding, proxy behavior, browser DNS/network differences, IPv4/IPv6 edge cases, redirects, WebSocket routes and browser exploits remain SSRF risks. Production deployments need OS/container egress controls and network policy.
- [ ] CAPTCHA/anti-bot detection is heuristic and may have false positives/negatives. No CAPTCHA solving, bypass, challenge outsourcing, human-in-the-loop live browser handoff or MFA automation is implemented. Validate Cloudflare, reCAPTCHA, hCaptcha and generic challenge pages without attempting circumvention.
- [ ] Authentication status uses host-supplied selectors and is only a heuristic. Validate login page selectors, redirects, MFA, SSO, session expiry, CSRF, identity confirmation and account switching. No generic credential submission/login wizard is provided.
- [ ] Form preview redacts password fields only; other personal, financial, hidden and CSRF fields may be returned. Validate redaction policies for token/secret fields, sensitive query strings, destination normalization and form action/method mutation between preview and submit.
- [ ] Form submission is a separate capability browser:submit:consequential and must be included in ToolEngine.require_approval approval_capabilities. Verify exact-argument approval, host actor authentication, notice presentation, replay protection, session ownership, double-submit prevention and that all externally consequential actions are classified and gated. Payment/financial/legal/irreversible actions need additional host-side risk classification and approval UX.
- [ ] Browser test runner supports bounded navigation, click, fill, expect_text, expect_visible and expect_url actions; it stops at first failed step. Validate test argument shape, timeouts, assertion semantics, cleanup, screenshots/traces, flakiness and test isolation. This is not a full test runner/CI integration.
- [ ] Site change monitors persist URL/selector/hash and notify only when monitor_check is invoked. Validate dynamic pages, normalization, false positives, monitor deletion/disable APIs, callback failures, retries, deduplication and scheduling. No autonomous polling daemon is included.
- [ ] Verify public tool names, schemas, capabilities and installer registration. Ensure no duplicate registrations when old and comprehensive browser packs are installed together; names currently use distinct identifiers except intentionally shared web.monitor namespaces are not reused.
- [ ] Verify Python 3.12 import and TOML/package extras; Playwright/Chromium installation and operation on Windows 11. No tests, Ruff, mypy, wheel build, integration tests or CI have been run for this branch by design.
- [ ] Potential code review targets before verification: profile cloning inserts the target row before validating the source state file; tab restore failures and partial context cleanup; active-tab index when blank tabs are excluded from persisted URLs; synchronous notifier exception behavior; WebSocket evaluation browser-origin restrictions; and exception detail leakage in browser test result messages.

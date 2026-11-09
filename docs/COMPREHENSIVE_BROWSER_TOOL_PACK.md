# Comprehensive Web and Browser Tool Pack

Install with the optional browser dependency:

    pip install -e ".[browser]"
    playwright install chromium

Register the pack:

    engine.install_comprehensive_browser_tools(
        profile_root="./browser_profiles",
        headless=True,
        extension_dirs=(),  # host-trusted extension directories only
    )

## Capabilities

| Area | Tools / behavior |
|---|---|
| Profiles | Create, list, clone saved browser state, delete profiles |
| Tabs and popups | List/create/select/close tabs; capture popup/new-tab events |
| Frames | Read/click/fill elements inside selected iframes |
| Authentication state | Persist cookies and local storage; inspect cookie metadata; clear cookies; use host-supplied login selectors as an authentication heuristic |
| Extensions | Load only host-configured extension directories; headed Chromium required |
| Scraping | Bounded CSS-selector extraction of text and selected attributes |
| Network | Capture request/response/failure metadata and WebSocket endpoints during navigation |
| WebSockets | Send one bounded text frame and capture one bounded reply |
| Change detection | Persist URL/selector monitors and invoke an optional host notifier when content changes |
| Application testing | Bounded navigation, click, fill, text, visibility and URL assertions |
| Human handoff | Detect likely CAPTCHA/anti-bot challenges and report that a human is required |
| Consequential forms | Preview destination/method/fields, then submit using a separately gated capability |

## Approval configuration

Consequential form submission is exposed only as browser.form_submit with capability
browser:submit:consequential. Configure the core approval layer to require a one-time,
exact-argument approval for this capability:

    engine.require_approval(
        "./approvals.sqlite3",
        approval_capabilities={"browser:submit:consequential"},
        on_request=host_approval_notification,
    )

The caller must first use browser.form_preview and pass its form_sha256 fingerprint to
browser.form_submit. Submission is refused if the form's action, method, field names, types,
required flags, values, checked states or selected values changed after preview. Password,
hidden and file values are redacted from preview output but are included in the fingerprint.
The host must authenticate the person deciding the approval and display the destination,
method, selected form and relevant consequence summary. The approval system binds to the
exact tool arguments, but does not itself establish the user's identity. Do not grant this
capability by default. Use a separate approval policy for payment, account deletion, legal
acceptance, purchases, publishing and other high-impact website actions.

## Security boundaries and known limitations

- CAPTCHA is detected, not solved, outsourced or bypassed. Authentication uses saved browser storage and heuristic selectors. In headed mode, a human
  handoff can keep a visible browser open while a host-supplied login indicator is awaited;
  it does not automate credentials or prove account identity.
- Browser profiles use Chromium persistent user-data directories on disk. Cookie values and local
  storage may contain bearer credentials. Protect the profile directory with OS ACLs,
  encryption at rest and per-user ownership; do not place it in a shared repository.
- Tabs are restored by URL plus saved cookies/storage, not by restoring the exact live
  JavaScript heap, open network sockets, in-flight requests or complete browser process.
- Chromium contexts are created per tool call, but the profile's persistent user-data directory
  retains cookies and local storage. Live tabs, JavaScript heaps, open sockets and browser
  process state are not preserved. This is not a full Chrome DevTools Protocol replacement.
- Extensions must be supplied by the host as trusted directories with a manifest. They
  run with browser privileges; extension signing, marketplace discovery, update policy
  and permission review are outside this pack.
- Network capture records metadata, not full HAR bodies, TLS secrets, response payloads,
  request replay or arbitrary DevTools protocol commands. WebSocket probe sends a single
  text message; it does not provide a persistent bidirectional socket session or binary
  frame support.
- WebSocket and browser URL checks reject non-public destinations, but DNS rebinding,
  browser networking behavior, redirects, proxy configuration and browser-engine bugs
  still require defense-in-depth network egress controls. Do not treat URL validation as
  an SSRF-proof network sandbox.
- Structured scraping is selector-driven and bounded; it is not a general-purpose
  crawler, search indexer, robots-policy engine or anti-bot evasion mechanism.
- Site monitors run only when web.change_monitor_check is invoked or a host scheduler
  invokes it. The optional notifier is a synchronous host callback; delivery retries,
  deduplication, daemon scheduling and notification-channel integration are host work.
- Browser test steps are bounded smoke/functional checks, not a replacement for a full
  Playwright test runner, test fixtures, trace viewer or CI browser matrix.
- Form preview redacts password, hidden and file values, hashes all field values for change
detection, and shows only a bounded excerpt of other field values. Other personal or financial
field values may still be visible. Tool output is untrusted; the host UI should redact sensitive fields before
  showing approval notices. The form submit operation should always be approval-gated.
- Playwright operations run with the host user's privileges. This pack does not provide
  OS-level process/container isolation or protection against malicious browser content.

## Verification status

Tests are authored in tests/test_browser_comprehensive.py but deliberately not run
under the current implementation instruction. See docs/VERIFICATION_LEDGER.md for
deferred checks, platform coverage and known failure modes.

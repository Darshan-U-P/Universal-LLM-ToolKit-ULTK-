# Comprehensive Browser Automation

ULTK's comprehensive browser pack builds on the basic browser and semantic-browser tools with persistent Chromium profiles, multi-tab workflows, popup and iframe handling, cookies, structured scraping, browser-triggered downloads, bounded network inspection, human authentication handoff, CAPTCHA-aware detection, form preview/submission, and persistent website change monitors.

## Installation

Install the browser extra and Chromium:

```bash
pip install -e '.[browser]'
python -m playwright install chromium
```

## Install the pack

```python
from ultk import ToolEngine

engine = ToolEngine(policy=your_permission_policy)
engine.install_comprehensive_browser_tools(
    profile_root="./browser_profiles",
    headless=True,
    download_root="./browser_downloads",
    max_download_bytes=25_000_000,
    extension_dirs=(),  # host-trusted unpacked Chromium extension directories
    notifier=my_host_notification_callback,
)
```

Extension directories and download paths are host configuration. Model input cannot add an extension, change the profile root, or choose an arbitrary filesystem destination.

## Tool surface

| Tool | Function |
|---|---|
| `browser.profile_create` | Create a named persistent Chromium profile; optional cloning copies browser state |
| `browser.profile_list` | List profile names and last-used timestamps |
| `browser.profile_delete` | Delete a profile and its saved authentication state |
| `browser.extensions_list` | List host-configured extension directories |
| `browser.control_navigate` / `browser.control_snapshot` | Navigate and inspect the active tab |
| `browser.tabs` | List, create, select and close tabs |
| `browser.popup_capture` | Click a selector and capture the resulting popup/new tab |
| `browser.frame_interact` | Read, click or fill inside a selected iframe |
| `browser.cookies` | List cookie metadata (never values) or clear cookies |
| `browser.scrape_structured` | Extract bounded text and selected attributes from matching elements |
| `browser.download` | Capture a browser-triggered download and save it in the configured directory |
| `browser.network_inspect` | Capture bounded request/response/failure/WebSocket metadata during a navigation window |
| `browser.websocket_probe` | Send one bounded text message to a public WebSocket and capture one reply |
| `browser.profile_workflow` | Run a fully prevalidated bounded multi-tab workflow with navigation, interaction, waits and assertions |
| `browser.test_run` | Run a bounded sequence of navigation, interaction and assertions |
| `browser.challenge_detect` | Detect CAPTCHA/anti-bot indicators without attempting to solve them |
| `browser.auth_handoff` | Open a visible browser for a human to complete login/MFA |
| `browser.auth_status` | Evaluate host-supplied login selectors as a heuristic |
| `browser.form_preview` | Preview form destination, method and redacted field metadata |
| `browser.form_submit` | Submit only if the form fingerprint matches a prior preview |
| `web.change_monitor_add/check/list/delete` | Manage and poll persistent website content monitors |

The read and mutating tools use separate capabilities. In particular, `browser.form_submit` requires the host policy to enforce a human approval step for `browser:submit:consequential`; a capability grant by itself is not a user confirmation.

## Profiles, sessions and tabs

Profiles use persistent Chromium user-data directories. Cookies, local storage and other browser state remain on disk between tool calls. Profile names are restricted to safe ASCII identifiers and hashed before they become directory names. A per-profile in-process lock serializes concurrent calls made through one ULTK process. This is not a cross-process browser lock or an OS sandbox.

Cloning a profile copies its saved browser state, including authentication material. Deleting a profile removes its saved browser directory. Protect `profile_root` with OS filesystem permissions and treat it as a credential store.

The active tab index and bounded HTTP(S) tab URLs are persisted in SQLite. A later operation recreates tabs at their last saved URLs; it does not restore the exact JavaScript heap, in-memory application state, open dialogs, or unsaved form state.

## Browser interaction and downloads

Selectors are bounded strings passed to Playwright locators. The pack does not accept model-supplied JavaScript. Popup and iframe operations are explicit and bounded. The structured scraper caps returned elements and per-element text/attribute lengths. Profile workflows prevalidate every step before dispatching the first browser action; they are bounded but not transactional if the browser or website fails mid-run.

Downloads are initiated by clicking a selected page element. Suggested filenames are sanitized, destination paths are confined to the host-configured download directory, existing files are not overwritten, and a SHA-256 digest is returned. The configured byte limit is checked after Playwright completes the download and saves its temporary file; it is not a pre-transfer network quota. Production hosts should additionally enforce response-size and disk quotas at the network/proxy or OS layer.

No browser file-upload tool is included in this increment.

## Network and security boundary

The browser context routes HTTP(S) requests through ULTK's public-URL validation, and service workers are blocked. This is defense in depth, not a complete SSRF boundary: DNS rebinding, resolution-to-connection races, browser/network-stack behavior and environment-specific proxying require network-level egress restrictions. Enforce public destination ranges at the host firewall or controlled proxy, including IPv4 and IPv6, link-local and cloud metadata addresses.

The Playwright request route does not provide a complete WebSocket egress policy. The WebSocket probe validates the requested public host before connecting, but host network egress controls are still required. The network inspector captures bounded metadata only; it is not a full HAR, packet capture or DevTools protocol recorder. WebSocket frame payloads are not captured by the inspector. The probe sends one text message and captures at most one reply.

## Authentication and anti-bot handling

- CAPTCHA and anti-bot detection is heuristic. ULTK does not solve, bypass, outsource or evade challenges.
- Human authentication handoff requires `headless=False` and a visible browser. The tool waits for a host-supplied login indicator to disappear. That is a workflow signal, not proof of identity, MFA success or account authorization.
- `browser.auth_status` uses host-supplied selectors. A missing login indicator is not authoritative proof that the user is authenticated.
- Authentication state persists in the profile directory. Restrict access and retention.

## Form submission and approval

The form preview returns the destination, method and bounded field metadata. Password, hidden and file values are redacted; value hashes are included so changes can be detected without returning raw values. Submission recomputes the fingerprint, rejects changes, validates the destination as public HTTP(S), permits only GET/POST and uses the browser's standards-based `requestSubmit` path.

The form hash is a change detector, not an approval token. The host application must require explicit human approval for the exact `browser.form_submit` arguments, ideally showing the destination, method, field summary and expected fingerprint before authorization. Do not automatically approve a form merely because its preview matches.

## Website monitoring

Monitor definitions and last-seen hashes are stored in SQLite. Checks are explicitly invoked by the host; this pack does not start a daemon or schedule recurring jobs. The host scheduler should apply retry/backoff and idempotent notifier handling. If the notifier fails, the monitor checkpoint is not advanced so the change can be retried. A notifier may still be called more than once if the external notification succeeds but the subsequent database write fails.

## Operational limitations

- Browser sessions are headless by default; visible human login requires a headed installation and desktop session.
- Playwright/Chromium and the configured extension binaries are host-installed.
- Persistent browser profiles contain sensitive state and are not encrypted by this pack.
- Same-profile calls are serialized only inside one process; multi-process locking is not implemented.
- No CAPTCHA solving, anti-bot evasion, arbitrary JavaScript, extension installation from model input, file upload, full HAR capture, WebSocket frame capture, distributed browser workers or unattended daemon is included.
- Website monitors rely on host polling. Scheduling, retries and notification delivery are host responsibilities.
- Browser interaction is not a sandbox. Browser processes run with the host user's privileges; use OS/container isolation and network egress restrictions for untrusted pages.

## Related browser packs

- `install_advanced_browser_tools`: earlier named-session navigation, interaction, snapshots, workflows and website monitor definitions.
- `install_semantic_browser_tools`: DOM-derived semantic target inspection and exact-unique element actions.
- `install_comprehensive_browser_tools`: persistent profiles and the expanded browser control plane documented here.

These packs have separate session/profile stores. Hosts should choose one session model per workflow or explicitly manage the distinction.

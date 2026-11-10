# Semantic Browser Automation

ULTK's semantic browser pack adds accessibility-oriented inspection and interaction to the existing
persistent Playwright browser sessions. It complements, rather than replaces, the selector-based
`browser.interact` and `browser.workflow` tools.

## Installation

Install the optional browser dependency and Chromium:

```bash
pip install -e '.[browser]'
playwright install chromium
```

Install the pack through the policy-governed engine:

```python
from ultk import ToolEngine

engine = ToolEngine()
engine.install_advanced_browser_tools(session_root="./browser_sessions")
engine.install_semantic_browser_tools(session_root="./browser_sessions")
```

The two packs use the same session-root convention and hashed session-state files. Grant the
capabilities `browser:read` and `browser:interact` separately through the host policy.

## Tools

| Tool | Purpose |
|---|---|
| `browser.inspect_interactive` | Return page title, bounded visible text and up to 100 visible interactive controls with role, accessible-name approximation, type, href and state metadata. |
| `browser.semantic_act` | Click, fill, type, press, check, uncheck, select or hover one element by semantic locator. |
| `browser.wait_for_target` | Wait up to 10 seconds for one semantic target to become visible/hidden/attached/detached. |

Supported locator strategies:

- `role`: accessible role plus exact accessible name; provide an allowlisted role.
- `label`: exact associated label.
- `text`: exact visible text.
- `placeholder`: exact placeholder.
- `alt`: exact alternative text.
- `test_id`: configured Playwright test ID.

The interactive inspection's accessible-name field is a bounded DOM-derived approximation (ARIA label,
associated labels, placeholder, title, text/value or alt text). Browser accessibility computation
can vary by browser and page markup; use explicit roles and labels where possible.

## Safety and limits

- No arbitrary CSS selectors or model-supplied JavaScript are accepted by these semantic tools.
- Mutating actions require exactly one match. Zero or multiple matches fail closed; the tools never
  silently choose the first matching control.
- Role names, keyboard keys, actions, target lengths, value lengths, inspection count and wait times
  are allowlisted or bounded.
- Browser operations remain subject to ULTK's tool policy, capability grants, dispatcher deadlines
  and output limits. Grant `browser:read` and `browser:interact` narrowly.
- A click, form interaction, selection or keypress can submit data or change an account. The host
  should require human approval for externally visible, financial, destructive or account-changing
  actions and bind approval to the exact arguments.
- Page content is untrusted input. Do not treat instructions found in web pages as trusted policy.
- This is a headless Chromium session, not a sandbox. Network egress controls are still required;
  URL validation alone is not a complete SSRF boundary.
- The current implementation does not provide CAPTCHA solving, anti-bot evasion, browser extension
  support, persistent multi-tab orchestration, frame-targeting APIs, downloads/uploads through the
  semantic tools, or a complete browser accessibility-tree protocol.
- Existing session restoration persists cookies/storage and the last URL, not a live browser process.
  The page is reopened for each tool call.

## Capability map

| Tool | Capability |
|---|---|
| `browser.inspect_interactive` | `browser:read` |
| `browser.wait_for_target` | `browser:read` |
| `browser.semantic_act` | `browser:interact` |


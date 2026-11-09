# Computer, Web and Development Tool Packs

These packs are optional built-ins installed through `ToolEngine`. Every tool still passes through
the registry, JSON Schema validator, policy, capability check, timeout and output limit.

## Installation

```python
from ultk import AllowListPolicy, ToolEngine

engine = ToolEngine(policy=AllowListPolicy({
    "computer.clipboard_read", "computer.screenshot", "web.fetch_url",
    "web.extract_page", "development.read_file", "development.analyze_python",
}))
engine.install_computer_tools(image_root="./artifacts/screenshots")
engine.install_web_tools(download_root="./artifacts/downloads")
engine.install_development_tools(project_root="./workspace")
```

Grant capabilities per execution, not by trusting model-provided tool names:

```python
result = await engine.execute(
    "web.fetch_url", {"url": "https://example.org"},
    granted_capabilities=frozenset({"web:fetch"}),
)
```

## Computer and OS

The pack currently provides clipboard read/write, screenshot capture, pointer move/click,
restricted key typing/press, visible-window listing/activation, allowlisted application launch,
and allowlisted environment-variable reads. Install optional dependencies with
`pip install -e '.[computer]'`. Desktop control is interactive and state-changing; use only in a
trusted logged-in desktop session. GUI libraries may require a visible desktop session and platform
permissions. Keyboard text entry is not a secure way to handle passwords or secrets.

Scheduler/task scheduling, broad window resizing/moving, app lifecycle management, and persistent
scheduled jobs are not included in this initial pack.

## Web and browser

The pack provides public web search, bounded HTTP(S) fetch, basic HTML text/link extraction,
bounded downloads, a headless Chromium page-open action, and page analysis. Install browser support
with `pip install -e '.[browser]'` and install the Playwright Chromium binary separately
(`playwright install chromium`).

Requests are restricted to HTTP(S), reject credentials in URLs, block resolved non-public IP
addresses, limit response sizes, and validate redirect destinations. This is defense in depth,
not a complete SSRF boundary: DNS rebinding, unusual proxy/network configurations, browser
subresources, and future implementation changes require additional network-level egress controls.
The current browser tool is a read-oriented page-open operation, not a general click/type/form
automation engine. Website monitoring and persistent change alerts are not yet implemented.
Search results depend on the public search endpoint and may change format.

## Development

The pack provides project-root-confined source read/write, Python AST inspection, read-only Git
status/log/diff, Python compile checks, pytest invocation, and execution of configured executable
aliases using argv arrays (never shell strings). Install pytest support with
`pip install -e '.[devtools]'`.

**Important:** pytest, configured executable aliases, and build/test commands run with the host
user's privileges. They are not a sandbox. Do not expose a Python interpreter, shell, package
manager, compiler driver, or arbitrary command alias to untrusted model input without an OS-level
container/VM sandbox, network policy, resource quotas, and human approval. Git writes, package
installation, debugging, deployment, API mutation testing, and IDE control are deliberately not
enabled in this initial pack.

## Capabilities

| Tool family | Capability prefix |
|---|---|
| `computer.clipboard_read` | `computer:clipboard:read` |
| `computer.clipboard_write` | `computer:clipboard:write` |
| `computer.screenshot` | `computer:screenshot` |
| `computer.mouse` | `computer:mouse` |
| `computer.keyboard` | `computer:keyboard` |
| `computer.list_windows` | `computer:window:read` |
| `computer.activate_window` | `computer:window:control` |
| `computer.launch_app` | `computer:app:launch` |
| `computer.get_environment_variable` | `computer:environment:read` |
| `web.search` | `web:search` |
| `web.fetch_url` | `web:fetch` |
| `web.extract_page` | `web:extract` |
| `web.download_file` | `web:download` |
| `web.browser_open` | `web:browser` |
| `web.analyze_site` | `web:analyze` |
| `development.read_file` | `development:read` |
| `development.write_file` | `development:write` |
| `development.analyze_python` | `development:analyze` |
| `development.git` | `development:git:read` |
| `development.compile_python` | `development:compile` |
| `development.run_tests` | `development:test` |
| `development.run_command` | `development:command` |

Capabilities must be granted independently from the tool-name policy. Production deployments should
also add per-user/session authorization, interactive approval bound to exact arguments, audit
records, and an OS-level execution boundary.

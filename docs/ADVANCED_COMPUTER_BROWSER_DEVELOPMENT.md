# Advanced Computer, Browser and Development Tools

This increment extends the initial tool packs. All operations still pass through ULTK's registry,
JSON Schema validation, tool-name policy, capability authorization, timeout and output-size limits.

## Installation

```python
from ultk import ToolEngine, AllowListPolicy

engine = ToolEngine(policy=AllowListPolicy({
    "computer.window_action", "computer.desktop_workflow",
    "scheduler.add_job", "scheduler.run_due",
    "browser.navigate", "browser.interact", "browser.workflow",
    "web.monitor_add", "web.monitor_check",
    "development.interpreter", "development.git_write",
}))
engine.install_advanced_computer_tools()
engine.install_scheduler_tools(
    "./state/scheduler.sqlite3",
    {"refresh_cache": lambda payload: print("refresh", payload)},
)
engine.install_advanced_browser_tools(
    session_root="./state/browser-sessions",
    monitor_database="./state/site-monitors.sqlite3",
)
engine.install_advanced_development_tools(
    project_root="./workspace",
    compilers={"gcc": {"path": "/usr/bin/gcc", "args": ["{source}", "-o", "{output}"]}},
    package_managers={"pip": {"path": "/path/to/pip", "ecosystem": "pip"}},
    build_targets={"release": ["/usr/bin/make", "release"]},
    deployment_targets={"staging": ["/opt/deploy-staging"]},
    api_hosts=("api.example.com",),
    ides={"vscode": "/usr/bin/code"},
    analyzers={"ruff": {"path": "/path/to/ruff", "args": ["check"]}},
    allowed_git_remotes=("origin",),
)
```

Only configure executable paths, compiler templates, package managers, build/deployment targets,
IDE binaries, analyzers, API hosts, Git remotes and scheduler handlers from trusted host settings.
Do not let a model edit these host-side allowlists.

## Computer and OS

Added:
- Window move/resize/maximize/minimize/restore by unique title match.
- Running application/process listing with PID and creation time.
- Process termination/kill after identity verification.
- Bounded desktop action sequences: move, click, type, restricted key press, wait and screenshot.

The GUI backend uses optional PyWinCtl/PyAutoGUI and inherits their platform/session limitations.
This is not a universal accessibility API; validate the backend on each target OS/window manager.
Desktop automation can click destructive controls or type into sensitive applications. Keep its
capabilities disabled by default and require an application-level approval layer for production.

## Scheduler and persistent jobs

The SQLite scheduler stores recurring interval jobs and survives restarts. It intentionally does
not spawn a daemon. The host application must call `scheduler.run_due` periodically (e.g. from
its own service loop). Job handlers are Python callables configured by the host; model-supplied
payloads are JSON data only. Jobs are advanced before invocation to reduce duplicate execution
after a crash; this is at-most-once leaning behavior, not a transactional exactly-once guarantee.
Use idempotent handlers. A production service should add leases, retry/backoff, dead-letter state,
misfire policies, time zones, one-shot/cron schedules, and durable execution records.

## Browser automation and monitoring

Added:
- Named browser sessions with persisted Playwright storage state (cookies/local storage).
- Navigate, click, fill, type, press, form submission and page snapshots.
- Bounded multi-page workflows.
- SQLite website monitor definitions and content-hash change detection.
- Optional host-provided notifier callback invoked when monitored content changes.

Browser session state contains authentication cookies and must be protected as a credential store.
Do not expose session directories to untrusted users. Browser automation is capable of submitting
forms and changing external accounts; use exact-argument human approval for consequential actions.
Network URL checks are defense in depth; enforce network-level egress controls as well. Monitoring
runs when the host invokes `web.monitor_check` or schedules a trusted monitor-check handler; no
background polling service is started automatically.

## Development

Added:
- A restricted Python expression/assignment interpreter with in-memory sessions. It is not a full
  Python REPL and rejects imports, loops, attribute access and arbitrary function calls.
- pdb launch with a source-line breakpoint.
- Configured compiler aliases with fixed argument templates.
- Configured pip/npm package list/install/remove.
- Git branch create/switch, stage, commit and allowlisted remote push.
- Named build and deployment targets from trusted static argv configuration.
- HTTPS API tests limited to explicitly allowlisted hostnames.
- IDE open-at-line through configured IDE binaries.
- Configured static analyzer execution (e.g. Ruff, mypy, Bandit).

**Execution security:** pdb, compilers, package managers, Git hooks, build targets, deployment
targets, IDE binaries and static analyzers are external processes and execute with the ULTK host
user's privileges. They are not sandboxes. Use a disposable container/VM, filesystem/network
restrictions, resource limits and human approval before running untrusted project code. Package
installation can execute package build/install scripts. Deployment, Git push, package mutation,
browser form submission and desktop controls should each require narrowly scoped approval.

The restricted interpreter is intentionally limited to simple expressions and assignments. It
keeps state in process memory and loses it on restart. It does not execute general Python programs.

## Tool capabilities

| Family | Capability |
|---|---|
| Window and app control | `computer:window:control`, `computer:app:read`, `computer:app:control` |
| Desktop workflow | `computer:workflow` |
| Persistent scheduler | `scheduler:read`, `scheduler:write`, `scheduler:execute` |
| Browser navigation/read | `browser:navigate`, `browser:read` |
| Browser interaction/workflow | `browser:interact`, `browser:workflow` |
| Website monitoring | `web:monitor:read`, `web:monitor:write`, `web:monitor:check` |
| Restricted interpreter | `development:interpreter` |
| Debugging | `development:debug` |
| Git mutations | `development:git:write` |
| Compiler | `development:compile` |
| Package management | `development:package:mutate` |
| Build/deployment | `development:build`, `development:deploy` |
| API testing | `development:api:test` |
| IDE | `development:ide` |
| Static analysis | `development:analysis:advanced` |

Tool-name policy and capability grants are both required. Production use also needs per-user
authorization, argument-bound approvals, auditable decisions, secret redaction and OS-level
isolation.

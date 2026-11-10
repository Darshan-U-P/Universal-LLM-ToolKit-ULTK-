# Terminal and Process Management Tools

ULTK provides a restricted command runner and separately permissioned process controls.

## Terminal execution

Configure exact executable paths and a working-directory root. The tool accepts an executable
alias plus an argument array; it never invokes a shell and does not perform PATH-based executable
lookup.

```python
import sys
from ultk import AllowListPolicy, ToolEngine

engine = ToolEngine(policy=AllowListPolicy({"terminal.execute"}))
engine.install_terminal_tools(
    working_root="./workspace",
    allowed_executables={"python": sys.executable},
    timeout_seconds=15,
    max_output_bytes=64_000,
)
result = await engine.execute(
    "terminal.execute",
    {"executable": "python", "args": ["--version"]},
    granted_capabilities=frozenset({"terminal:execute"}),
)
```

Controls:
- Exact executable aliases map to resolved executable files at installation time.
- Arguments are passed as an array to `create_subprocess_exec`; shell parsing is disabled.
- The working directory must resolve inside the configured root.
- Per-call timeout cannot exceed the configured maximum (at most 120 seconds).
- stdin is closed; stdout and stderr are independently capped and decoded as UTF-8 with replacement.
- Only explicitly selected parent environment variables are inherited.
- Cancellation and timeout trigger best-effort termination of the launched process and its descendants.
- Requires the allowlisted tool ID and `terminal:execute` capability.

**Security boundary:** executable allowlisting and directory confinement reduce exposure but are not
an OS sandbox. An approved executable may itself access files, networks, or spawn other programs
according to the host user's OS permissions. Do not allowlist shells or interpreters for untrusted
model-generated scripts unless a real OS-level sandbox and approval policy are in place.

## Process management

The existing `system.*` tools provide read-only process discovery. The new controls are:

| Tool | Capability | Effect |
|---|---|---|
| `process.terminate` | `process:terminate` | Request termination; optional force-kill |
| `process.suspend` | `process:suspend` | Suspend a process |
| `process.resume` | `process:resume` | Resume a suspended process |

Every operation requires both PID and the process creation timestamp previously returned by
`system.get_process_info`. This guards against accidentally acting on a different process after
PID reuse. ULTK refuses to control its own host process. OS access controls still apply, and
operations can fail when the caller lacks permission.

```python
engine.install_system_tools()
engine.install_process_management_tools()

info = await engine.execute(
    "system.get_process_info",
    {"pid": 1234},
    granted_capabilities=frozenset({"system:read"}),
)
# Read the returned created_at value, then explicitly authorize a separate operation.
```

Termination, suspension, and resumption are state-changing operations. They should only be enabled
for trusted sessions and should be protected by a human-approval layer in production. ULTK's
current permission policy is an allowlist/capability gate, not an interactive approval workflow.

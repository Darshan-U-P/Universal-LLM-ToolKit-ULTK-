# System and Process Tools

ULTK's first system tool pack is cross-platform and read-only.

| Tool ID | Purpose | Capability |
|---|---|---|
| `system.get_platform_info` | OS, Python, CPU and memory metadata | `system:read` |
| `system.list_processes` | Bounded process listing with PID, name, status and RSS memory | `system:read` |
| `system.get_process_info` | Metadata for one PID | `system:read` |

## Installation

```python
from ultk import AllowListPolicy, ToolEngine

engine = ToolEngine(
    policy=AllowListPolicy({
        "system.get_platform_info",
        "system.list_processes",
        "system.get_process_info",
    })
)
engine.install_system_tools()
```

Each invocation must also receive the `system:read` capability.

## Data minimization and safety

- Process listing is capped at 100 entries per call (50 by default).
- Optional name filtering is case-insensitive.
- The tools intentionally do not expose command-line arguments, environment variables,
  process credentials, open files, or network connections.
- The pack does not start, stop, signal, suspend, or modify processes.
- Process metadata is inherently time-sensitive; a process may exit between enumeration
  and inspection. Such races are handled by skipping inaccessible entries or returning
  a safe structured error.
- These tools are inspection utilities, not a security boundary or process sandbox.

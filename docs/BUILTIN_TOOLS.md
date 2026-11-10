# Built-in Tools

## LLM-independent execution

The `ToolEngine` API registers and executes tools directly. It does not require a provider,
model, API key, or agent runtime.

```python
import asyncio

from ultk import AllowListPolicy, ToolEngine


async def main() -> None:
    engine = ToolEngine(
        policy=AllowListPolicy({
            "filesystem.read_file",
            "filesystem.write_file",
            "filesystem.list_directory",
            "filesystem.create_directory",
            "filesystem.stat",
        })
    )
    engine.install_filesystem_tools("./workspace")

    result = await engine.execute(
        "filesystem.write_file",
        {"path": "notes.txt", "content": "Created by ULTK"},
        granted_capabilities=frozenset({"filesystem:write"}),
    )
    if result.is_error:
        raise RuntimeError(result.content)


asyncio.run(main())
```

## Filesystem tool pack

The first built-in pack provides:

| Tool ID | Operation | Required capability |
|---|---|---|
| `filesystem.read_file` | Read UTF-8 text | `filesystem:read` |
| `filesystem.write_file` | Create or replace UTF-8 text | `filesystem:write` |
| `filesystem.list_directory` | List directory entries | `filesystem:read` |
| `filesystem.create_directory` | Create directories | `filesystem:write` |
| `filesystem.stat` | Read basic file metadata | `filesystem:read` |

All paths are relative to the configured root. Absolute paths and paths that resolve outside
the root are rejected. File reads and writes have a configurable byte limit (2 MB by default).
Writes use a temporary file and atomic replacement.

## Security and current limitations

- The default policy denies all tools. Configure an explicit allow-list.
- Grant only the capabilities needed for a particular invocation.
- The filesystem root is a boundary for normal path resolution, not a complete OS sandbox.
- This initial implementation does not yet defend against every filesystem time-of-check/time-of-use
  race involving a concurrently modified symlink.
- There is intentionally no delete tool in this first pack. Destructive operations will be added
  after the approval and audit subsystems are implemented.
- The tools operate on UTF-8 text; binary file handling belongs in a later file/media tool pack.

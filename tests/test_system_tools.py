import os

import psutil
import pytest

from ultk.builtins.system import create_system_tools
from ultk.engine import ToolEngine
from ultk.permissions import AllowListPolicy


@pytest.fixture
def engine() -> ToolEngine:
    names = {
        "system.get_platform_info",
        "system.list_processes",
        "system.get_process_info",
    }
    toolkit = ToolEngine(policy=AllowListPolicy(names))
    toolkit.register_tools(create_system_tools())
    return toolkit


@pytest.mark.asyncio
async def test_platform_info_returns_expected_fields(engine: ToolEngine) -> None:
    result = await engine.execute(
        "system.get_platform_info",
        {},
        granted_capabilities=frozenset({"system:read"}),
    )
    assert not result.is_error
    for field in ("system", "python_version", "logical_cpu_count", "memory_total_bytes"):
        assert f'"{field}"' in result.content


@pytest.mark.asyncio
async def test_process_listing_includes_current_process(engine: ToolEngine) -> None:
    result = await engine.execute(
        "system.list_processes",
        {"limit": 100},
        granted_capabilities=frozenset({"system:read"}),
    )
    assert not result.is_error
    assert str(os.getpid()) in result.content


@pytest.mark.asyncio
async def test_process_info_returns_current_process(engine: ToolEngine) -> None:
    result = await engine.execute(
        "system.get_process_info",
        {"pid": os.getpid()},
        granted_capabilities=frozenset({"system:read"}),
    )
    assert not result.is_error
    assert f'"pid": {os.getpid()}' in result.content


@pytest.mark.asyncio
async def test_missing_process_returns_safe_error(engine: ToolEngine) -> None:
    missing_pid = max(psutil.pids(), default=1) + 100_000
    result = await engine.execute(
        "system.get_process_info",
        {"pid": missing_pid},
        granted_capabilities=frozenset({"system:read"}),
    )
    assert result.is_error
    assert "No process exists" in result.content


@pytest.mark.asyncio
async def test_system_read_capability_is_required(engine: ToolEngine) -> None:
    result = await engine.execute("system.list_processes", {})
    assert result.is_error
    assert "denied" in result.content.lower()

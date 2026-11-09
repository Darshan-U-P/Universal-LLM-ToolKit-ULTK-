import asyncio
import json
import subprocess
import sys
import time

import psutil
import pytest

from ultk.engine import ToolEngine
from ultk.permissions import AllowListPolicy


@pytest.fixture
def terminal_engine(tmp_path) -> ToolEngine:
    engine = ToolEngine(policy=AllowListPolicy({"terminal.execute"}))
    engine.install_terminal_tools(
        tmp_path,
        {"python": sys.executable},
        timeout_seconds=3,
        max_output_bytes=128,
    )
    return engine


@pytest.mark.asyncio
async def test_terminal_executes_allowlisted_program_with_argv(terminal_engine: ToolEngine) -> None:
    result = await terminal_engine.execute(
        "terminal.execute",
        {"executable": "python", "args": ["-c", "print('hello')"]},
        granted_capabilities=frozenset({"terminal:execute"}),
    )
    assert not result.is_error
    payload = json.loads(result.content)
    assert payload["return_code"] == 0
    assert payload["stdout"].strip() == "hello"


@pytest.mark.asyncio
async def test_terminal_rejects_unapproved_executable(terminal_engine: ToolEngine) -> None:
    result = await terminal_engine.execute(
        "terminal.execute",
        {"executable": "not-configured", "args": []},
        granted_capabilities=frozenset({"terminal:execute"}),
    )
    assert result.is_error


@pytest.mark.asyncio
async def test_terminal_rejects_working_directory_escape(terminal_engine: ToolEngine) -> None:
    result = await terminal_engine.execute(
        "terminal.execute",
        {"executable": "python", "args": ["--version"], "cwd": ".."},
        granted_capabilities=frozenset({"terminal:execute"}),
    )
    assert result.is_error


@pytest.mark.asyncio
async def test_terminal_enforces_timeout(terminal_engine: ToolEngine) -> None:
    result = await terminal_engine.execute(
        "terminal.execute",
        {"executable": "python", "args": ["-c", "import time; time.sleep(10)"], "timeout_seconds": 0.2},
        granted_capabilities=frozenset({"terminal:execute"}),
    )
    assert not result.is_error
    assert json.loads(result.content)["timed_out"] is True


@pytest.mark.asyncio
async def test_terminal_requires_capability(terminal_engine: ToolEngine) -> None:
    result = await terminal_engine.execute(
        "terminal.execute", {"executable": "python", "args": ["--version"]}
    )
    assert result.is_error
    assert "denied" in result.content.lower()


@pytest.mark.asyncio
async def test_process_terminate_requires_identity_and_capability() -> None:
    engine = ToolEngine(policy=AllowListPolicy({"process.terminate"}))
    engine.install_process_management_tools()
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        created = psutil.Process(child.pid).create_time()
        denied = await engine.execute(
            "process.terminate",
            {"pid": child.pid, "expected_create_time": created},
        )
        assert denied.is_error
        allowed = await engine.execute(
            "process.terminate",
            {"pid": child.pid, "expected_create_time": created},
            granted_capabilities=frozenset({"process:terminate"}),
        )
        assert not allowed.is_error
        assert json.loads(allowed.content)["status"] == "exited"
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


@pytest.mark.asyncio
async def test_process_identity_mismatch_is_rejected() -> None:
    engine = ToolEngine(policy=AllowListPolicy({"process.terminate"}))
    engine.install_process_management_tools()
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        result = await engine.execute(
            "process.terminate",
            {"pid": child.pid, "expected_create_time": time.time() - 1000},
            granted_capabilities=frozenset({"process:terminate"}),
        )
        assert result.is_error
        assert "identity check failed" in result.content.lower()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()

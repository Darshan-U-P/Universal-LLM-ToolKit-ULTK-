"""PowerShell pack tests; authored but deliberately not executed during implementation."""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

import pytest

from ultk.builtins.powershell import PowerShellToolPack, create_powershell_tools
from ultk.exceptions import ToolExecutionError


@pytest.fixture
def pwsh() -> str:
    executable = shutil.which("pwsh")
    if not executable:
        pytest.skip("PowerShell 7 is required for these tests.")
    return executable


def test_tool_pack_registers_expected_native_operations(tmp_path: Path, pwsh: str) -> None:
    tools = create_powershell_tools(executable=pwsh, working_root=tmp_path)
    names = {tool.spec.name for tool in tools}
    assert {
        "powershell.get_os_info", "powershell.list_services",
        "powershell.get_registry_key", "powershell.inspect_script",
        "powershell.list_processes", "powershell.get_event_logs",
    } <= names


def test_script_execution_requires_host_hash_and_detects_changes(tmp_path: Path, pwsh: str) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = scripts / "safe.ps1"
    script.write_text('param([string]$Value) Write-Output $Value\n', encoding="utf-8")
    digest = hashlib.sha256(script.read_bytes()).hexdigest()
    pack = PowerShellToolPack(
        executable=pwsh, working_root=tmp_path, script_root=scripts,
        allowed_script_hashes={"safe": digest},
    )
    script.write_text('Write-Output "changed"\n', encoding="utf-8")
    with pytest.raises(ToolExecutionError):
        pack.execute_approved_script("safe", [])


def test_unapproved_script_is_rejected(tmp_path: Path, pwsh: str) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    pack = PowerShellToolPack(executable=pwsh, working_root=tmp_path, script_root=scripts)
    with pytest.raises(ToolExecutionError):
        pack.execute_approved_script("unknown", [])


def test_inspect_script_rejects_path_escape(tmp_path: Path, pwsh: str) -> None:
    pack = PowerShellToolPack(executable=pwsh, working_root=tmp_path)
    with pytest.raises(ToolExecutionError):
        pack.inspect_script("../outside.ps1")


def test_non_windows_admin_operations_fail_closed(tmp_path: Path, pwsh: str) -> None:
    if os.name == "nt":
        pytest.skip("Windows-only guard is not applicable.")
    pack = PowerShellToolPack(executable=pwsh, working_root=tmp_path)
    with pytest.raises(ToolExecutionError):
        pack._fixed("system.get_os")

"""Dedicated, policy-governed PowerShell tools.

Built-in operations are fixed cmdlet workflows. Optional script execution is restricted
to host-pinned scripts whose SHA-256 digests are configured by the host.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping

from ultk.builtins._common import FunctionTool, object_schema
from ultk.exceptions import ToolExecutionError

_FIXED_SCRIPTS: dict[str, str] = {
    "shell.get_location": "$ExecutionContext.SessionState.Path.CurrentLocation.Path",
    "shell.get_environment": "Get-ChildItem Env: | Sort-Object Name | Select-Object Name,Value",
    "system.get_os": "Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber,OSArchitecture,LastBootUpTime",
    "system.get_computer": "Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer,Model,TotalPhysicalMemory,NumberOfLogicalProcessors,Domain",
    "system.get_hotfixes": "Get-HotFix | Sort-Object InstalledOn -Descending | Select-Object -First 100 HotFixID,Description,InstalledBy,InstalledOn",
    "process.list": "Get-Process | Sort-Object ProcessName | Select-Object -First 500 Id,ProcessName,CPU,WorkingSet64,StartTime",
    "service.list": "Get-Service | Sort-Object Name | Select-Object Name,DisplayName,Status,StartType",
    "network.ip_config": "Get-NetIPConfiguration | Select-Object InterfaceAlias,InterfaceIndex,IPv4Address,IPv6Address,DNSServer",
    "network.connections": "Get-NetTCPConnection | Select-Object -First 500 LocalAddress,LocalPort,RemoteAddress,RemotePort,State,OwningProcess",
    "network.dns_cache": "Get-DnsClientCache | Select-Object -First 500 Entry,Name,Type,Data,Status,TimeToLive",
    "firewall.profiles": "Get-NetFirewallProfile | Select-Object Name,Enabled,DefaultInboundAction,DefaultOutboundAction,LogFileName",
    "registry.get": "Get-ItemProperty -LiteralPath $data.path | Select-Object *",
    "registry.list_subkeys": "Get-ChildItem -LiteralPath $data.path | Select-Object Name,PSChildName",
    "events.get": "Get-WinEvent -FilterHashtable @{LogName=$data.log_name; StartTime=(Get-Date).AddDays(-$data.days)} -MaxEvents $data.limit | Select-Object TimeCreated,Id,LevelDisplayName,ProviderName,Message",
    "tasks.list": "Get-ScheduledTask | Select-Object -First 500 TaskName,TaskPath,State,Author,Description",
    "modules.list": "Get-Module -ListAvailable | Sort-Object Name,Version -Unique | Select-Object Name,Version,Path",
    "modules.get_commands": "Get-Command -Module $data.module_name | Select-Object Name,CommandType,Source,Version",
}

_WINDOWS_ONLY = {
    "system.get_os", "system.get_computer", "system.get_hotfixes",
    "service.list", "service.start", "service.stop", "service.restart",
    "network.ip_config", "network.connections", "network.dns_cache",
    "firewall.profiles", "registry.get", "registry.list_subkeys",
    "events.get", "tasks.list", "tasks.get", "tasks.start", "tasks.stop",
}


class PowerShellToolPack:
    """Fixed-operation PowerShell runner with bounded output and host policy."""

    def __init__(
        self, *, executable: str | Path | None = None, working_root: str | Path = ".",
        timeout_seconds: int = 20, max_output_bytes: int = 200_000,
        allowed_script_hashes: Mapping[str, str] | None = None,
        script_root: str | Path | None = None,
        allowed_modules: frozenset[str] = frozenset(),
        allowed_computers: frozenset[str] = frozenset(),
    ) -> None:
        candidates = ("pwsh.exe", "powershell.exe") if os.name == "nt" else ("pwsh",)
        selected = str(executable) if executable else next(
            (shutil.which(name) for name in candidates if shutil.which(name)), None)
        if not selected:
            raise ToolExecutionError("PowerShell was not found; configure pwsh or powershell.exe explicitly.")
        resolved = Path(selected).expanduser().resolve(strict=True)
        if not resolved.is_file():
            raise ToolExecutionError("Configured PowerShell executable is not a file.")
        if not 1 <= timeout_seconds <= 120 or not 1024 <= max_output_bytes <= 2_000_000:
            raise ToolExecutionError("Invalid PowerShell execution limits.")
        self.executable = str(resolved)
        self.root = Path(working_root).expanduser().resolve()
        if not self.root.is_dir():
            raise ToolExecutionError("PowerShell working root must be an existing directory.")
        self.timeout = timeout_seconds
        self.max_output = max_output_bytes
        self.allowed_modules = frozenset(allowed_modules)
        self.allowed_computers = frozenset(host.casefold() for host in allowed_computers)
        self.script_root = Path(script_root).expanduser().resolve() if script_root else None
        self.script_hashes = dict(allowed_script_hashes or {})
        if self.script_hashes and (self.script_root is None or not self.script_root.is_dir()):
            raise ToolExecutionError("A valid script_root is required for approved script execution.")
        self.approved_scripts: dict[str, Path] = {}
        for script_id, expected_hash in self.script_hashes.items():
            if not script_id or len(script_id) > 80 or not isinstance(expected_hash, str) or len(expected_hash) != 64:
                raise ToolExecutionError("Approved scripts require a short ID and SHA-256 digest.")
            if any(ch not in "0123456789abcdefABCDEF" for ch in expected_hash):
                raise ToolExecutionError("Approved script digest must be hexadecimal SHA-256.")
            candidate = (self.script_root / f"{script_id}.ps1").resolve()
            if not candidate.is_relative_to(self.script_root) or not candidate.is_file():
                raise ToolExecutionError(f"Approved script file is missing or escapes script_root: {script_id}")
            if hashlib.sha256(candidate.read_bytes()).hexdigest().casefold() != expected_hash.casefold():
                raise ToolExecutionError(f"Approved script hash mismatch: {script_id}")
            self.approved_scripts[script_id] = candidate

    def _run(self, source: str, payload: dict[str, Any] | None = None,
             *, timeout: int | None = None) -> dict[str, Any]:
        payload_b64 = base64.b64encode(
            json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).decode("ascii")
        wrapper = (
            "$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue';"
            "$WarningPreference='SilentlyContinue';$InformationPreference='SilentlyContinue';"
            f"$data=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{payload_b64}')) | ConvertFrom-Json;"
            "try {$result = & { " + source + " };"
            "if ($null -eq $result) {$result=@()};"
            "[Console]::Out.WriteLine((ConvertTo-Json -InputObject @($result) -Depth 10 -Compress));"
            "} catch {$err=@{error=$_.Exception.Message;category=$_.CategoryInfo.Category.ToString()};"
            "[Console]::Error.WriteLine((ConvertTo-Json -InputObject $err -Compress));exit 1}"
        )
        command = [self.executable, "-NoLogo", "-NoProfile", "-NonInteractive",
                   "-EncodedCommand", base64.b64encode(wrapper.encode("utf-16le")).decode("ascii")]
        env = {key: value for key, value in os.environ.items()
               if key.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH", "PATHEXT", "PSMODULEPATH"}}
        env["POWERSHELL_TELEMETRY_OPTOUT"] = "1"
        try:
            result = subprocess.run(command, cwd=self.root, env=env, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    shell=False, timeout=timeout or self.timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ToolExecutionError("PowerShell operation timed out.") from exc
        except OSError as exc:
            raise ToolExecutionError(f"Unable to start PowerShell ({type(exc).__name__}).") from exc
        stdout = result.stdout[:self.max_output].decode("utf-8", errors="replace")
        stderr = result.stderr[:self.max_output].decode("utf-8", errors="replace")
        return {"return_code": result.returncode, "stdout": stdout, "stderr": stderr,
                "output_truncated": len(result.stdout) > self.max_output or len(result.stderr) > self.max_output}

    @staticmethod
    def _string(value: str, label: str, max_length: int = 2048) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > max_length or "\x00" in value:
            raise ToolExecutionError(f"Invalid {label}.")
        return value

    def _windows_required(self, tool_name: str) -> None:
        if os.name != "nt":
            raise ToolExecutionError(f"{tool_name} is available only on Windows.")

    def _fixed(self, name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if name in _WINDOWS_ONLY:
            self._windows_required(name)
        return self._run(_FIXED_SCRIPTS[name], payload)

    def execute_approved_script(self, script_id: str, arguments: list[str] | None = None) -> dict[str, Any]:
        script_id = self._string(script_id, "script ID", 80)
        path = self.approved_scripts.get(script_id)
        if path is None:
            raise ToolExecutionError("Script ID is not host-approved.")
        args = arguments or []
        if not isinstance(args, list) or len(args) > 64 or any(
            not isinstance(item, str) or len(item) > 2000 or "\x00" in item for item in args):
            raise ToolExecutionError("Script arguments are invalid.")
        if hashlib.sha256(path.read_bytes()).hexdigest().casefold() != self.script_hashes[script_id].casefold():
            raise ToolExecutionError("Approved script changed after configuration; refusing execution.")
        args_b64 = base64.b64encode(json.dumps(args, ensure_ascii=False).encode("utf-8")).decode("ascii")
        safe_path = str(path).replace("'", "''")
        source = (f"$scriptArgs=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{args_b64}')) | ConvertFrom-Json;"
                  f"$result = & '{safe_path}' @scriptArgs;$result")
        return self._run(source, timeout=self.timeout)

    def inspect_script(self, relative_path: str) -> dict[str, Any]:
        path_text = self._string(relative_path, "script path", 1000)
        candidate = Path(path_text)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ToolExecutionError("Script path must remain inside working_root.")
        path = (self.root / candidate).resolve()
        if not path.is_relative_to(self.root) or not path.is_file() or path.suffix.casefold() != ".ps1":
            raise ToolExecutionError("Expected a .ps1 file inside working_root.")
        if path.stat().st_size > 1_000_000:
            raise ToolExecutionError("PowerShell script exceeds 1 MB.")
        source = (
            "$tokens=$null;$parseErrors=$null;"
            "[System.Management.Automation.Language.Parser]::ParseFile($data.path,[ref]$tokens,[ref]$parseErrors) | Out-Null;"
            "@{valid=($parseErrors.Count -eq 0);"
            "errors=@($parseErrors | ForEach-Object {@{message=$_.Message;line=$_.Extent.StartLineNumber;column=$_.Extent.StartColumnNumber}});"
            "commands=@($tokens | Where-Object {$_.Kind -eq 'Generic'} | Select-Object -First 500 | ForEach-Object {$_.Text})}"
        )
        result = self._run(source, {"path": str(path)})
        result["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        result["path"] = path.relative_to(self.root).as_posix()
        return result

    def _service(self, name: str, action: str) -> dict[str, Any]:
        self._windows_required("service management")
        service = self._string(name, "service name", 256)
        if action not in {"Start-Service", "Stop-Service", "Restart-Service"}:
            raise ToolExecutionError("Unsupported service action.")
        return self._run(f"{action} -Name $data.name -ErrorAction Stop; Get-Service -Name $data.name | Select-Object Name,Status",
                         {"name": service})

    def _task(self, name: str, task_path: str, action: str) -> dict[str, Any]:
        self._windows_required("scheduled task management")
        task_name = self._string(name, "task name", 256)
        path = self._string(task_path, "task path", 512)
        if not path.startswith("\\") or ".." in path.split("\\"):
            raise ToolExecutionError("Scheduled task path must be an absolute Task Scheduler path.")
        scripts = {
            "get": "Get-ScheduledTask -TaskName $data.name -TaskPath $data.path | Select-Object TaskName,TaskPath,State,Author,Description",
            "start": "Start-ScheduledTask -TaskName $data.name -TaskPath $data.path; Get-ScheduledTask -TaskName $data.name -TaskPath $data.path | Select-Object TaskName,TaskPath,State",
            "stop": "Stop-ScheduledTask -TaskName $data.name -TaskPath $data.path; Get-ScheduledTask -TaskName $data.name -TaskPath $data.path | Select-Object TaskName,TaskPath,State",
        }
        if action not in scripts:
            raise ToolExecutionError("Unsupported scheduled task action.")
        return self._run(scripts[action], {"name": task_name, "path": path})

    def _module_commands(self, module_name: str) -> dict[str, Any]:
        name = self._string(module_name, "module name", 128)
        if name not in self.allowed_modules:
            raise ToolExecutionError("Module is not in the host-configured allowlist.")
        return self._fixed("modules.get_commands", {"module_name": name})

    def _remote_test(self, computer: str) -> dict[str, Any]:
        host = self._string(computer, "computer name", 255)
        if host.casefold() not in self.allowed_computers:
            raise ToolExecutionError("Computer is not in the host-configured remoting allowlist.")
        self._windows_required("PowerShell remoting")
        return self._run("Test-WSMan -ComputerName $data.computer | Select-Object ComputerName,ProductVendor,ProtocolVersion",
                         {"computer": host})


def create_powershell_tools(
    *, executable: str | Path | None = None, working_root: str | Path = ".",
    timeout_seconds: int = 20, max_output_bytes: int = 200_000,
    allowed_script_hashes: Mapping[str, str] | None = None, script_root: str | Path | None = None,
    allowed_modules: frozenset[str] = frozenset(),
    allowed_computers: frozenset[str] = frozenset(),
) -> tuple[FunctionTool, ...]:
    """Create PowerShell-native tools with host-defined script/module/remoting trust."""
    pack = PowerShellToolPack(
        executable=executable, working_root=working_root, timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes, allowed_script_hashes=allowed_script_hashes,
        script_root=script_root, allowed_modules=allowed_modules, allowed_computers=allowed_computers)
    tools: list[FunctionTool] = []

    def add(name: str, description: str, props: dict[str, Any], required: list[str],
            capability: str, fn: Any, timeout: int | None = None) -> None:
        tools.append(FunctionTool(name, description, object_schema(props, required),
                                  capability, fn, timeout=timeout or timeout_seconds + 5,
                                  output_limit=max_output_bytes))

    empty: dict[str, Any] = {}
    string = {"type": "string", "minLength": 1, "maxLength": 2048}
    task_path = {"type": "string", "minLength": 1, "maxLength": 512}
    add("powershell.get_location", "Get current PowerShell working location.", empty, [], "powershell:read", lambda: pack._fixed("shell.get_location"))
    add("powershell.get_environment", "List environment variables visible to the PowerShell process.", empty, [], "powershell:read:environment", lambda: pack._fixed("shell.get_environment"))
    add("powershell.get_os_info", "Read Windows operating-system information.", empty, [], "powershell:read:system", lambda: pack._fixed("system.get_os"))
    add("powershell.get_computer_info", "Read computer manufacturer, model, memory and processor information.", empty, [], "powershell:read:system", lambda: pack._fixed("system.get_computer"))
    add("powershell.list_hotfixes", "List recently installed Windows hotfixes.", empty, [], "powershell:read:system", lambda: pack._fixed("system.get_hotfixes"))
    add("powershell.list_processes", "List bounded process metadata.", empty, [], "powershell:read:process", lambda: pack._fixed("process.list"))
    add("powershell.list_services", "List Windows services and their states.", empty, [], "powershell:read:services", lambda: pack._fixed("service.list"))
    add("powershell.start_service", "Start a named Windows service; requires host authorization.", {"name": string}, ["name"], "powershell:service:write", lambda name: pack._service(name, "Start-Service"))
    add("powershell.stop_service", "Stop a named Windows service; requires host authorization.", {"name": string}, ["name"], "powershell:service:stop", lambda name: pack._service(name, "Stop-Service"))
    add("powershell.restart_service", "Restart a named Windows service; requires host authorization.", {"name": string}, ["name"], "powershell:service:write", lambda name: pack._service(name, "Restart-Service"))
    add("powershell.get_ip_configuration", "Read Windows network interface and DNS configuration.", empty, [], "powershell:read:network", lambda: pack._fixed("network.ip_config"))
    add("powershell.list_tcp_connections", "List bounded Windows TCP connection metadata.", empty, [], "powershell:read:network", lambda: pack._fixed("network.connections"))
    add("powershell.get_dns_cache", "Inspect the Windows DNS client cache.", empty, [], "powershell:read:network", lambda: pack._fixed("network.dns_cache"))
    add("powershell.get_firewall_profiles", "Inspect Windows Defender Firewall profile states and defaults.", empty, [], "powershell:read:firewall", lambda: pack._fixed("firewall.profiles"))
    add("powershell.get_registry_key", "Read registry values at a supplied registry provider path.", {"path": string}, ["path"], "powershell:read:registry", lambda path: pack._fixed("registry.get", {"path": path}))
    add("powershell.list_registry_subkeys", "List immediate registry subkeys without modifying them.", {"path": string}, ["path"], "powershell:read:registry", lambda path: pack._fixed("registry.list_subkeys", {"path": path}))
    add("powershell.get_event_logs", "Read bounded recent events from a named Windows event log.", {"log_name": {"type": "string", "enum": ["System", "Application", "Security", "Setup"]}, "days": {"type": "integer", "minimum": 1, "maximum": 30}, "limit": {"type": "integer", "minimum": 1, "maximum": 200}}, ["log_name"], "powershell:read:eventlogs", lambda log_name, days=1, limit=50: pack._fixed("events.get", {"log_name": log_name, "days": days, "limit": limit}))
    add("powershell.list_scheduled_tasks", "List scheduled tasks.", empty, [], "powershell:read:tasks", lambda: pack._fixed("tasks.list"))
    add("powershell.get_scheduled_task", "Inspect one scheduled task.", {"name": string, "task_path": task_path}, ["name", "task_path"], "powershell:read:tasks", lambda name, task_path: pack._task(name, task_path, "get"))
    add("powershell.start_scheduled_task", "Start one scheduled task; requires host authorization.", {"name": string, "task_path": task_path}, ["name", "task_path"], "powershell:tasks:write", lambda name, task_path: pack._task(name, task_path, "start"))
    add("powershell.stop_scheduled_task", "Stop one scheduled task; requires host authorization.", {"name": string, "task_path": task_path}, ["name", "task_path"], "powershell:tasks:stop", lambda name, task_path: pack._task(name, task_path, "stop"))
    add("powershell.list_modules", "List installed and discoverable PowerShell modules.", empty, [], "powershell:read:modules", lambda: pack._fixed("modules.list"))
    add("powershell.get_module_commands", "List commands exported by a host-allowlisted module.", {"module_name": string}, ["module_name"], "powershell:read:modules", pack._module_commands)
    add("powershell.test_remoting", "Test WS-Management connectivity to a host-allowlisted computer.", {"computer": string}, ["computer"], "powershell:remoting:read", pack._remote_test)
    add("powershell.inspect_script", "Parse a project-local .ps1 script without executing it.", {"path": {"type": "string", "minLength": 1, "maxLength": 1000}}, ["path"], "powershell:script:inspect", pack.inspect_script)
    if pack.approved_scripts:
        add("powershell.execute_approved_script", "Execute a host-pinned PowerShell script with an approved SHA-256 digest.", {"script_id": {"type": "string", "minLength": 1, "maxLength": 80}, "arguments": {"type": "array", "items": {"type": "string", "maxLength": 2000}, "maxItems": 64}}, ["script_id"], "powershell:script:execute", pack.execute_approved_script, timeout_seconds + 10)
    return tuple(tools)

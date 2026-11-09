"""Advanced, policy-separated PowerShell administration and persistent session tools.

Persistent sessions accept only host-allowlisted cmdlets and a deliberately restricted
PowerShell AST subset. Administrative operations use fixed command templates and
host-side resource allowlists. No generic model-supplied script runner is exposed here.
"""
from __future__ import annotations

import base64
import json
import os
import queue
import re
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any, Mapping

from ultk.builtins._common import FunctionTool, object_schema
from ultk.builtins.powershell import PowerShellToolPack
from ultk.exceptions import ToolExecutionError

_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_REGISTRY_PREFIXES = ("HKLM:\\", "HKCU:\\", "HKCR:\\", "HKU:\\", "HKCC:\\")


class PersistentPowerShellSessions:
    """One isolated long-lived pwsh process per ULTK session."""

    _FORBIDDEN_AST = [
        "MemberExpressionAst", "InvokeMemberExpressionAst", "TypeExpressionAst",
        "TypeConstraintAst", "UsingExpressionAst", "UsingStatementAst",
        "ScriptBlockExpressionAst", "SubExpressionAst", "ExpandableStringExpressionAst",
        "RedirectionAst", "FunctionDefinitionAst", "ClassDefinitionAst",
        "ConfigurationDefinitionAst", "DataStatementAst", "DynamicKeywordStatementAst",
        "TrapStatementAst", "ThrowStatementAst", "ReturnStatementAst", "ExitStatementAst",
        "BreakStatementAst", "ContinueStatementAst", "IfStatementAst", "ForEachStatementAst",
        "ForStatementAst", "WhileStatementAst", "DoWhileStatementAst", "SwitchStatementAst",
        "TryStatementAst", "PipelineChainAst",
    ]

    def __init__(
        self, executable: str, working_root: Path, allowed_commands: frozenset[str],
        timeout_seconds: int, max_output_bytes: int,
    ) -> None:
        self.executable = executable
        self.working_root = working_root
        self.allowed_commands = frozenset(allowed_commands)
        self.timeout = timeout_seconds
        self.max_output = max_output_bytes
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def _wrapper(self) -> str:
        commands = base64.b64encode(json.dumps(sorted(self.allowed_commands)).encode()).decode()
        forbidden = json.dumps(self._FORBIDDEN_AST)
        return (
            "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false);"
            "$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue';"
            "$WarningPreference='SilentlyContinue';$InformationPreference='SilentlyContinue';"
            f"$allowed=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{commands}'))|ConvertFrom-Json;"
            f"$forbidden={forbidden};$reserved=@('allowed','forbidden','maxOutput','request','line','ast','tokens','errors','bad','variables','assignments','calls','name','resolved','result','json','value','commandName','arguments','path','variable','assignment','call','node','vars','item','data','ErrorActionPreference','ProgressPreference','WarningPreference','InformationPreference','ExecutionContext','PSDefaultParameterValues');"
            f"$maxOutput={self.max_output};"
            "function Send-Response($value) {"
            "$json=ConvertTo-Json -InputObject $value -Depth 8 -Compress;"
            "if ([Text.Encoding]::UTF8.GetByteCount($json) -gt $maxOutput) "
            "{$json=ConvertTo-Json -InputObject @{ok=$false;error='Session output exceeds configured limit.'} -Compress};"
            "[Console]::Out.WriteLine($json);[Console]::Out.Flush()"
            "};"
            "function Test-SessionScript([string]$source) {"
            "$tokens=$null;$errors=$null;"
            "$ast=[System.Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$errors);"
            "if ($errors.Count -gt 0) { throw 'PowerShell syntax error.' };"
            "$bad=$ast.FindAll({param($node) $forbidden -contains $node.GetType().Name},$true);"
            "if ($bad.Count -gt 0) { throw ('Disallowed PowerShell syntax: '+$bad[0].GetType().Name) };"
            "$variables=$ast.FindAll({param($node) $node -is [System.Management.Automation.Language.VariableExpressionAst]},$true);"
            "foreach($variable in $variables) {"
            "$path=$variable.VariablePath;"
            "if ($path.IsDriveQualified -or $path.IsGlobal -or $path.IsScript -or $path.IsPrivate -or "
            "$path.UserPath -match ':' -or $reserved -contains $path.UserPath) { throw 'Scoped, drive-qualified or reserved variables are not allowed.' }"
            "};"
            "$assignments=$ast.FindAll({param($node) $node -is [System.Management.Automation.Language.AssignmentStatementAst]},$true);"
            "foreach($assignment in $assignments) {"
            "if ($assignment.Left -isnot [System.Management.Automation.Language.VariableExpressionAst]) "
            "{ throw 'Assignments may target session variables only.' }"
            "};"
            "$calls=$ast.FindAll({param($node) $node -is [System.Management.Automation.Language.CommandAst]},$true);"
            "foreach($call in $calls) {"
            "$name=$call.GetCommandName();"
            "if (-not $name -or $allowed -notcontains $name) { throw 'Command is not host-allowlisted.' };"
            "$resolved=Get-Command -Name $name -ErrorAction Stop;"
            "if ($resolved.CommandType -ne [System.Management.Automation.CommandTypes]::Cmdlet) "
            "{ throw 'Only directly installed cmdlets are allowed in persistent sessions.' }"
            "};"
            "return $true"
            "};"
            "[Console]::Out.WriteLine((ConvertTo-Json -InputObject @{ready=$true} -Compress));[Console]::Out.Flush();"
            "while($null -ne ($line=[Console]::In.ReadLine())) {"
            "try {"
            "$request=$line|ConvertFrom-Json;"
            "switch($request.action) {"
            "'validate' { Test-SessionScript ([string]$request.script)|Out-Null; Send-Response @{ok=$true;validated=$true} }"
            "'execute' {"
            "Test-SessionScript ([string]$request.script)|Out-Null;"
            "$result=@(); . ([scriptblock]::Create([string]$request.script)) | ForEach-Object {$result += ,$_};"
            "Send-Response @{ok=$true;result=$result}"
            "}"
            "'variables' {"
            "$vars=Get-Variable | Where-Object {$_.Name -notmatch '^(PS|_|args$|input$)'} | "
            "Select-Object -First 200 Name,Visibility,Options;"
            "Send-Response @{ok=$true;variables=@($vars)}"
            "}"
            "'get_variable' {"
            "$name=[string]$request.name;"
            "if ($name -notmatch '^[A-Za-z][A-Za-z0-9_]{0,63}$') {throw 'Invalid variable name.'};"
            "$variable=Get-Variable -Name $name -ErrorAction Stop;"
            "Send-Response @{ok=$true;name=$name;value=$variable.Value}"
            "}"
            "default {throw 'Unknown session action.'}"
            "}"
            "} catch { Send-Response @{ok=$false;error=$_.Exception.Message} }"
            "}"
        )

    def open(self, label: str) -> dict[str, Any]:
        if not self.allowed_commands:
            raise ToolExecutionError("Persistent sessions are disabled until the host configures allowed_session_commands.")
        if not isinstance(label, str) or not label.strip() or len(label) > 100:
            raise ToolExecutionError("Session label must be 1–100 characters.")
        encoded = base64.b64encode(self._wrapper().encode("utf-16le")).decode("ascii")
        env = {key: value for key, value in os.environ.items() if key.upper() in {
            "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH", "PATHEXT", "PSMODULEPATH",
            "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
        }}
        try:
            process = subprocess.Popen(
                [self.executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                cwd=self.working_root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                bufsize=1, shell=False, close_fds=True,
            )
        except OSError as exc:
            raise ToolExecutionError(f"Unable to start persistent PowerShell session ({type(exc).__name__}).") from exc
        responses: queue.Queue[str | None] = queue.Queue(maxsize=256)

        def read_output() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                try:
                    responses.put(line.rstrip("\r\n"), timeout=1)
                except queue.Full:
                    process.kill()
                    return
            try:
                responses.put(None, timeout=1)
            except queue.Full:
                pass

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        try:
            ready = responses.get(timeout=10)
            if ready is None or json.loads(ready).get("ready") is not True:
                raise ToolExecutionError("PowerShell session failed to initialize.")
        except (queue.Empty, json.JSONDecodeError, AttributeError) as exc:
            process.kill()
            raise ToolExecutionError("PowerShell session initialization timed out or returned invalid output.") from exc
        session_id = uuid.uuid4().hex
        record = {
            "session_id": session_id, "label": label.strip(), "process": process,
            "responses": responses, "reader": reader, "lock": threading.Lock(),
            "created_at": __import__("time").time(), "last_used_at": __import__("time").time(),
        }
        with self._lock:
            self._sessions[session_id] = record
        return {"session_id": session_id, "label": record["label"], "status": "open",
                "allowed_commands": sorted(self.allowed_commands)}

    def _request(self, session_id: str, action: str, **payload: Any) -> dict[str, Any]:
        with self._lock:
            record = self._sessions.get(session_id)
        if record is None:
            raise ToolExecutionError("PowerShell session does not exist or is closed.")
        process: subprocess.Popen[str] = record["process"]
        lock: threading.Lock = record["lock"]
        with lock:
            if process.poll() is not None or process.stdin is None:
                raise ToolExecutionError("PowerShell session process has exited.")
            request = json.dumps({"action": action, **payload}, ensure_ascii=False, separators=(",", ":"))
            if len(request.encode("utf-8")) > self.max_output:
                raise ToolExecutionError("PowerShell session request exceeds configured size limit.")
            try:
                process.stdin.write(request + "\n")
                process.stdin.flush()
                line = record["responses"].get(timeout=self.timeout)
            except (BrokenPipeError, OSError) as exc:
                raise ToolExecutionError("PowerShell session pipe failed.") from exc
            except queue.Empty as exc:
                process.kill()
                with self._lock:
                    self._sessions.pop(session_id, None)
                raise ToolExecutionError("Persistent PowerShell command timed out; session was terminated.") from exc
            if line is None:
                raise ToolExecutionError("PowerShell session terminated unexpectedly.")
            try:
                response = json.loads(line)
            except json.JSONDecodeError as exc:
                process.kill()
                raise ToolExecutionError("PowerShell session returned malformed protocol data.") from exc
            record["last_used_at"] = __import__("time").time()
            if not response.get("ok"):
                raise ToolExecutionError(str(response.get("error", "PowerShell session operation failed."))[:1000])
            return response

    def validate(self, session_id: str, script: str) -> dict[str, Any]:
        self._validate_script_text(script)
        return self._request(session_id, "validate", script=script)

    def execute(self, session_id: str, script: str) -> dict[str, Any]:
        self._validate_script_text(script)
        return self._request(session_id, "execute", script=script)

    @staticmethod
    def _validate_script_text(script: str) -> None:
        if not isinstance(script, str) or not script.strip() or len(script.encode("utf-8")) > 32_000:
            raise ToolExecutionError("Session script must be non-empty and at most 32 KB.")

    def workflow(self, session_id: str, steps: list[str]) -> dict[str, Any]:
        if not isinstance(steps, list) or not 1 <= len(steps) <= 20:
            raise ToolExecutionError("A PowerShell workflow must contain 1–20 steps.")
        for step in steps:
            self._validate_script_text(step)
        # Validate every step before executing any step, so a bad later step cannot partially run.
        for step in steps:
            self.validate(session_id, step)
        results = []
        for index, step in enumerate(steps):
            results.append({"step": index + 1, **self.execute(session_id, step)})
        return {"session_id": session_id, "steps_completed": len(results), "results": results}

    def variables(self, session_id: str) -> dict[str, Any]:
        return self._request(session_id, "variables")

    def get_variable(self, session_id: str, name: str) -> dict[str, Any]:
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name):
            raise ToolExecutionError("Invalid session variable name.")
        return self._request(session_id, "get_variable", name=name)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [{
                "session_id": item["session_id"], "label": item["label"],
                "created_at": item["created_at"], "last_used_at": item["last_used_at"],
                "running": item["process"].poll() is None,
            } for item in self._sessions.values()]

    def close(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._sessions.pop(session_id, None)
        if record is None:
            raise ToolExecutionError("PowerShell session does not exist or is already closed.")
        process: subprocess.Popen[str] = record["process"]
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if process.stdin:
            process.stdin.close()
        if process.stdout:
            process.stdout.close()
        return {"session_id": session_id, "status": "closed"}


class AdvancedPowerShellToolPack:
    def __init__(
        self, base: PowerShellToolPack, *,
        allowed_session_commands: frozenset[str] = frozenset(),
        allowed_computers: frozenset[str] = frozenset(),
        allowed_remote_commands: frozenset[str] = frozenset(),
        allowed_registry_roots: frozenset[str] = frozenset(),
        allowed_firewall_rule_names: frozenset[str] = frozenset(),
        allowed_local_users: frozenset[str] = frozenset(),
        allowed_local_groups: frozenset[str] = frozenset(),
        local_user_password_env: str | None = None,
        allowed_update_kbs: frozenset[str] = frozenset(),
        allow_windows_update_install: bool = False,
        allowed_disk_numbers: frozenset[int] = frozenset(),
        allow_storage_mutations: bool = False,
        allowed_certificate_stores: frozenset[str] = frozenset({"Cert:\\CurrentUser\\My"}),
        allowed_certificate_thumbprints: frozenset[str] = frozenset(),
        allowed_install_modules: Mapping[str, frozenset[str]] | None = None,
        allowed_package_names: frozenset[str] = frozenset(),
        allowed_package_versions: Mapping[str, frozenset[str]] | None = None,
        allowed_package_sources: frozenset[str] = frozenset(),
        allowed_ad_domains: frozenset[str] = frozenset(),
        allowed_ad_group_dns: frozenset[str] = frozenset(),
        allowed_ad_member_dns: frozenset[str] = frozenset(),
        allowed_gpo_names: frozenset[str] = frozenset(),
        allowed_gpo_targets: frozenset[str] = frozenset(),
        allowed_gpo_registry_keys: frozenset[str] = frozenset(),
        allowed_task_names: frozenset[str] = frozenset(),
        allowed_task_paths: frozenset[str] = frozenset({chr(92)}),
        approved_task_templates: Mapping[str, Mapping[str, str]] | None = None,
        allowed_audit_subcategories: frozenset[str] = frozenset(),
        allow_security_policy_changes: bool = False,
        timeout_seconds: int = 30,
    ) -> None:
        self.base = base
        forbidden_commands = {"Invoke-Expression", "Add-Type", "Start-Process", "Set-ExecutionPolicy", "Stop-Computer", "Restart-Computer", "Remove-Item", "Clear-Content", "Set-Content"}
        if any(command in forbidden_commands for command in allowed_session_commands):
            raise ToolExecutionError("Persistent session allowlist includes a blocked high-risk cmdlet.")
        self.timeout = timeout_seconds
        self.allowed_computers = frozenset(item.casefold() for item in allowed_computers)
        self.allowed_remote_commands = frozenset(allowed_remote_commands)
        self.allowed_registry_roots = frozenset(item.rstrip("\\").casefold() for item in allowed_registry_roots)
        self.allowed_firewall_names = frozenset(allowed_firewall_rule_names)
        self.allowed_users = frozenset(allowed_local_users)
        self.allowed_groups = frozenset(allowed_local_groups)
        self.password_env = local_user_password_env
        self.allowed_kbs = frozenset(item.upper() for item in allowed_update_kbs)
        self.allow_update_install = allow_windows_update_install
        self.allowed_disks = frozenset(allowed_disk_numbers)
        self.allow_storage = allow_storage_mutations
        self.allowed_cert_stores = frozenset(allowed_certificate_stores)
        self.allowed_cert_thumbprints = frozenset(item.replace(" ", "").upper() for item in allowed_certificate_thumbprints)
        self.allowed_modules = dict(allowed_install_modules or {})
        self.allowed_packages = frozenset(allowed_package_names)
        self.allowed_package_versions = dict(allowed_package_versions or {})
        self.allowed_sources = frozenset(allowed_package_sources)
        self.allowed_ad_domains = frozenset(item.casefold() for item in allowed_ad_domains)
        self.allowed_ad_groups = frozenset(allowed_ad_group_dns)
        self.allowed_ad_members = frozenset(allowed_ad_member_dns)
        self.allowed_gpos = frozenset(allowed_gpo_names)
        self.allowed_gpo_targets = frozenset(allowed_gpo_targets)
        self.allowed_gpo_registry_keys = frozenset(allowed_gpo_registry_keys)
        self.allowed_tasks = frozenset(allowed_task_names)
        self.allowed_task_paths = frozenset(allowed_task_paths)
        self.task_templates = {key: dict(value) for key, value in (approved_task_templates or {}).items()}
        self.allowed_audit = frozenset(allowed_audit_subcategories)
        self.allow_security = allow_security_policy_changes
        self.sessions = PersistentPowerShellSessions(
            base.executable, base.root, allowed_session_commands, min(base.timeout, timeout_seconds),
            base.max_output,
        )

    def _windows(self, name: str) -> None:
        self.base._windows_required(name)

    @staticmethod
    def _value(value: Any, label: str, limit: int = 2048) -> str:
        return PowerShellToolPack._string(value, label, limit)

    @staticmethod
    def _name(value: Any, label: str) -> str:
        text = PowerShellToolPack._string(value, label, 128)
        if not _NAME.fullmatch(text):
            raise ToolExecutionError(f"Invalid {label}.")
        return text

    def _registry_path(self, value: str) -> str:
        path = self._value(value, "registry path", 512).replace("/", "\\")
        if not path.upper().startswith(_REGISTRY_PREFIXES) or ".." in path.split("\\") or "*" in path or "?" in path:
            raise ToolExecutionError("Registry path must be a concrete Windows registry provider path.")
        normalized = path.rstrip("\\").casefold()
        if not any(normalized == root or normalized.startswith(root + "\\")
                   for root in self.allowed_registry_roots):
            raise ToolExecutionError("Registry path is outside host-configured writable registry roots.")
        return path

    def registry_set(self, path: str, name: str, value: Any, value_type: str) -> dict[str, Any]:
        self._windows("registry write")
        registry_path = self._registry_path(path)
        value_name = self._value(name, "registry value name", 256)
        if value_type not in {"String", "ExpandString", "MultiString", "DWord", "QWord", "Binary"}:
            raise ToolExecutionError("Unsupported registry value type.")
        if value_type in {"String", "ExpandString"} and not isinstance(value, str):
            raise ToolExecutionError("String registry values require text.")
        if value_type == "MultiString" and (not isinstance(value, list) or any(not isinstance(item, str) for item in value)):
            raise ToolExecutionError("MultiString registry values require a list of strings.")
        if value_type in {"DWord", "QWord"} and (type(value) is not int or not 0 <= value <= (2**32-1 if value_type == "DWord" else 2**64-1)):
            raise ToolExecutionError("DWord/QWord registry values require a non-negative in-range integer.")
        if value_type == "Binary" and (not isinstance(value, list) or any(type(item) is not int or not 0 <= item <= 255 for item in value)):
            raise ToolExecutionError("Binary registry values require a list of byte values.")
        if isinstance(value, (dict,)) or not isinstance(value, (str, int, float, bool, list)):
            raise ToolExecutionError("Registry value must be a scalar or array.")
        if len(json.dumps(value, ensure_ascii=False)) > 16_000:
            raise ToolExecutionError("Registry value exceeds 16 KB.")
        return self.base._run(
            "New-Item -Path $data.path -Force -ErrorAction Stop | Out-Null;"
            "New-ItemProperty -LiteralPath $data.path -Name $data.name -Value $data.value "
            "-PropertyType $data.type -Force -ErrorAction Stop | Select-Object PSPath,PSChildName",
            {"path": registry_path, "name": value_name, "value": value, "type": value_type},
            timeout=self.timeout,
        )

    def registry_remove_value(self, path: str, name: str) -> dict[str, Any]:
        self._windows("registry write")
        registry_path = self._registry_path(path)
        value_name = self._value(name, "registry value name", 256)
        return self.base._run(
            "Remove-ItemProperty -LiteralPath $data.path -Name $data.name -ErrorAction Stop;"
            "@{path=$data.path;name=$data.name;removed=$true}",
            {"path": registry_path, "name": value_name}, timeout=self.timeout)

    def registry_remove_key(self, path: str) -> dict[str, Any]:
        self._windows("registry write")
        registry_path = self._registry_path(path)
        return self.base._run(
            "Remove-Item -LiteralPath $data.path -ErrorAction Stop;"
            "@{path=$data.path;removed=$true}",
            {"path": registry_path}, timeout=self.timeout)

    def firewall_list(self) -> dict[str, Any]:
        self._windows("firewall management")
        return self.base._run(
            "Get-NetFirewallRule | Select-Object -First 500 Name,DisplayName,Enabled,Direction,Action,Profile",
            timeout=self.timeout)

    def _firewall_name(self, name: str) -> str:
        value = self._value(name, "firewall rule name", 256)
        if value not in self.allowed_firewall_names:
            raise ToolExecutionError("Firewall rule name is not host-allowlisted.")
        return value

    def firewall_create(self, name: str, display_name: str, direction: str, action: str,
                        protocol: str, local_port: int | None, remote_port: int | None,
                        profile: str, enabled: bool) -> dict[str, Any]:
        self._windows("firewall management")
        rule_name = self._firewall_name(name)
        title = self._value(display_name, "firewall display name", 256)
        if direction not in {"Inbound", "Outbound"} or action not in {"Allow", "Block"}:
            raise ToolExecutionError("Invalid firewall direction or action.")
        if protocol not in {"TCP", "UDP", "Any"} or profile not in {"Domain", "Private", "Public", "Any"}:
            raise ToolExecutionError("Invalid firewall protocol or profile.")
        for port in (local_port, remote_port):
            if port is not None and (type(port) is not int or not 1 <= port <= 65535):
                raise ToolExecutionError("Firewall ports must be integers from 1 to 65535.")
        payload = {"name": rule_name, "display": title, "direction": direction, "action": action,
                   "protocol": protocol, "local_port": local_port, "remote_port": remote_port,
                   "profile": profile, "enabled": bool(enabled)}
        return self.base._run(
            "$params=@{Name=$data.name;DisplayName=$data.display;Direction=$data.direction;"
            "Action=$data.action;Protocol=$data.protocol;Profile=$data.profile;Enabled=[bool]$data.enabled};"
            "if($null -ne $data.local_port){$params.LocalPort=[string]$data.local_port};"
            "if($null -ne $data.remote_port){$params.RemotePort=[string]$data.remote_port};"
            "New-NetFirewallRule @params -ErrorAction Stop | Select-Object Name,DisplayName,Enabled,Direction,Action,Profile",
            payload, timeout=self.timeout)

    def firewall_state(self, name: str, enabled: bool) -> dict[str, Any]:
        self._windows("firewall management")
        rule_name = self._firewall_name(name)
        command = "Enable-NetFirewallRule" if enabled else "Disable-NetFirewallRule"
        return self.base._run(
            f"{command} -Name $data.name -ErrorAction Stop | Select-Object Name,Enabled",
            {"name": rule_name}, timeout=self.timeout)

    def firewall_remove(self, name: str) -> dict[str, Any]:
        self._windows("firewall management")
        rule_name = self._firewall_name(name)
        return self.base._run(
            "Remove-NetFirewallRule -Name $data.name -ErrorAction Stop;@{name=$data.name;removed=$true}",
            {"name": rule_name}, timeout=self.timeout)

    def local_users(self) -> dict[str, Any]:
        self._windows("local account management")
        return self.base._run("Get-LocalUser | Select-Object Name,Enabled,Description,LastLogon,PasswordRequired",
                              timeout=self.timeout)

    def local_groups(self) -> dict[str, Any]:
        self._windows("local group management")
        return self.base._run("Get-LocalGroup | Select-Object Name,Description,SID",
                              timeout=self.timeout)

    def _user(self, name: str) -> str:
        value = self._name(name, "local user name")
        if value not in self.allowed_users:
            raise ToolExecutionError("Local user is not in the host-configured allowlist.")
        return value

    def _group(self, name: str) -> str:
        value = self._name(name, "local group name")
        if value not in self.allowed_groups:
            raise ToolExecutionError("Local group is not in the host-configured allowlist.")
        return value

    def local_user_create(self, name: str, description: str = "") -> dict[str, Any]:
        self._windows("local user management")
        user = self._user(name)
        if not self.password_env or not os.environ.get(self.password_env):
            raise ToolExecutionError("Host-configured local_user_password_env is missing or empty.")
        password = os.environ[self.password_env]
        if len(password) < 12 or "\x00" in password:
            raise ToolExecutionError("Host-provided local account password must be at least 12 characters.")
        display = self._value(description, "user description", 256)
        return self.base._run(
            "$secure=ConvertTo-SecureString $env:ULTK_LOCAL_USER_PASSWORD -AsPlainText -Force;"
            "New-LocalUser -Name $data.name -Password $secure -Description $data.description "
            "-ErrorAction Stop | Select-Object Name,Enabled,Description,SID",
            {"name": user, "description": display}, timeout=self.timeout,
            extra_environment={"ULTK_LOCAL_USER_PASSWORD": password})

    def local_user_enabled(self, name: str, enabled: bool) -> dict[str, Any]:
        self._windows("local user management")
        user = self._user(name)
        command = "Enable-LocalUser" if enabled else "Disable-LocalUser"
        return self.base._run(f"{command} -Name $data.name -ErrorAction Stop | Select-Object Name,Enabled",
                              {"name": user}, timeout=self.timeout)

    def local_user_remove(self, name: str) -> dict[str, Any]:
        self._windows("local user management")
        user = self._user(name)
        return self.base._run("Remove-LocalUser -Name $data.name -ErrorAction Stop;@{name=$data.name;removed=$true}",
                              {"name": user}, timeout=self.timeout)

    def local_group_member(self, user_name: str, group_name: str, add: bool) -> dict[str, Any]:
        self._windows("local group management")
        user, group = self._user(user_name), self._group(group_name)
        command = "Add-LocalGroupMember" if add else "Remove-LocalGroupMember"
        return self.base._run(
            f"{command} -Group $data.group -Member $data.user -ErrorAction Stop;"
            "@{user=$data.user;group=$data.group;added=$data.add}",
            {"user": user, "group": group, "add": bool(add)}, timeout=self.timeout)

    def windows_update_list(self) -> dict[str, Any]:
        self._windows("Windows Update")
        if "PSWindowsUpdate" not in self.base.allowed_modules:
            raise ToolExecutionError("PSWindowsUpdate must be installed and host-allowlisted in allowed_modules.")
        return self.base._run(
            "Import-Module PSWindowsUpdate -ErrorAction Stop;"
            "Get-WindowsUpdate -ErrorAction Stop | Select-Object -First 200 KB,Size,Title,IsDownloaded,IsInstalled",
            timeout=self.timeout)

    def windows_update_history(self) -> dict[str, Any]:
        self._windows("Windows Update")
        return self.base._run(
            "Get-HotFix | Sort-Object InstalledOn -Descending | Select-Object -First 200 HotFixID,Description,InstalledOn",
            timeout=self.timeout)

    def windows_update_install(self, kb_ids: list[str]) -> dict[str, Any]:
        self._windows("Windows Update")
        if not self.allow_update_install or "PSWindowsUpdate" not in self.base.allowed_modules:
            raise ToolExecutionError("Windows Update installation is disabled or PSWindowsUpdate is not host-allowlisted.")
        if not isinstance(kb_ids, list) or not 1 <= len(kb_ids) <= 20:
            raise ToolExecutionError("Provide 1–20 approved KB identifiers.")
        normalized = [self._value(item, "KB identifier", 16).upper() for item in kb_ids]
        if any(not re.fullmatch(r"KB[0-9]{5,10}", item) or item not in self.allowed_kbs for item in normalized):
            raise ToolExecutionError("Every KB identifier must be in the host-configured Windows Update allowlist.")
        return self.base._run(
            "Import-Module PSWindowsUpdate -ErrorAction Stop;"
            "Install-WindowsUpdate -KBArticleID $data.kbs -AcceptAll -IgnoreReboot -ErrorAction Stop",
            {"kbs": normalized}, timeout=120)

    def disks(self) -> dict[str, Any]:
        self._windows("disk management")
        return self.base._run("Get-Disk | Select-Object Number,FriendlyName,SerialNumber,BusType,PartitionStyle,OperationalStatus,IsOffline,IsReadOnly,Size",
                              timeout=self.timeout)

    def partitions(self, disk_number: int) -> dict[str, Any]:
        self._windows("partition management")
        disk = self._disk(disk_number)
        return self.base._run("Get-Partition -DiskNumber $data.disk | Select-Object DiskNumber,PartitionNumber,DriveLetter,Type,Size,IsBoot,IsSystem",
                              {"disk": disk}, timeout=self.timeout)

    def volumes(self) -> dict[str, Any]:
        self._windows("volume management")
        return self.base._run("Get-Volume | Select-Object DriveLetter,FileSystemLabel,FileSystem,DriveType,HealthStatus,OperationalStatus,Size,SizeRemaining",
                              timeout=self.timeout)

    def _disk(self, number: int) -> int:
        if type(number) is not int or number not in self.allowed_disks:
            raise ToolExecutionError("Disk number is not in the host-configured allowlist.")
        return number

    def disk_online(self, number: int, online: bool) -> dict[str, Any]:
        self._windows("disk state management")
        if not self.allow_storage:
            raise ToolExecutionError("Storage mutations are disabled by host policy.")
        disk = self._disk(number)
        return self.base._run("Set-Disk -Number $data.disk -IsOffline $data.offline -ErrorAction Stop | "
                              "Select-Object Number,IsOffline,IsReadOnly",
                              {"disk": disk, "offline": not bool(online)}, timeout=self.timeout)

    def disk_initialize(self, number: int, partition_style: str) -> dict[str, Any]:
        self._windows("disk initialization")
        if not self.allow_storage:
            raise ToolExecutionError("Storage mutations are disabled by host policy.")
        disk = self._disk(number)
        if partition_style not in {"GPT", "MBR"}:
            raise ToolExecutionError("Partition style must be GPT or MBR.")
        return self.base._run(
            "$target=Get-Disk -Number $data.disk -ErrorAction Stop;"
            "if($target.PartitionStyle -ne 'RAW'){throw 'Only RAW disks can be initialized.'};"
            "Initialize-Disk -Number $data.disk -PartitionStyle $data.style -ErrorAction Stop | "
            "Select-Object Number,PartitionStyle,OperationalStatus",
            {"disk": disk, "style": partition_style}, timeout=self.timeout)

    def partition_create(self, number: int, size_bytes: int, drive_letter: str | None) -> dict[str, Any]:
        self._windows("partition creation")
        if not self.allow_storage:
            raise ToolExecutionError("Storage mutations are disabled by host policy.")
        disk = self._disk(number)
        if type(size_bytes) is not int or not 1_048_576 <= size_bytes <= 2_000_000_000_000:
            raise ToolExecutionError("Partition size must be between 1 MiB and 2 TB.")
        if drive_letter is not None and (not isinstance(drive_letter, str) or not re.fullmatch(r"[D-Z]", drive_letter.upper())):
            raise ToolExecutionError("Drive letter must be D–Z or null.")
        return self.base._run(
            "$params=@{DiskNumber=$data.disk;Size=$data.size;ErrorAction='Stop'};"
            "if($data.letter){$params.DriveLetter=$data.letter[0]};"
            "New-Partition @params | Select-Object DiskNumber,PartitionNumber,DriveLetter,Size",
            {"disk": disk, "size": size_bytes, "letter": drive_letter.upper() if drive_letter else None},
            timeout=self.timeout)

    def certificate_list(self, store: str) -> dict[str, Any]:
        self._windows("certificate store")
        if store not in self.allowed_cert_stores:
            raise ToolExecutionError("Certificate store is not host-allowlisted.")
        if not store.startswith("Cert:\\"):
            raise ToolExecutionError("Certificate store must be a Cert: provider path.")
        return self.base._run(
            "Get-ChildItem -LiteralPath $data.store | Select-Object -First 300 Subject,Issuer,Thumbprint,NotBefore,NotAfter,HasPrivateKey",
            {"store": store}, timeout=self.timeout)

    def certificate_import(self, relative_path: str, store: str) -> dict[str, Any]:
        self._windows("certificate import")
        if store not in self.allowed_cert_stores or not store.startswith("Cert:\\"):
            raise ToolExecutionError("Certificate store is not host-allowlisted.")
        candidate = Path(self._value(relative_path, "certificate path", 1000))
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ToolExecutionError("Certificate path must be relative to working_root.")
        path = (self.base.root / candidate).resolve()
        if not path.is_relative_to(self.base.root) or not path.is_file() or path.suffix.casefold() not in {".cer", ".crt", ".der"}:
            raise ToolExecutionError("Only a project-local public .cer/.crt/.der certificate can be imported.")
        return self.base._run(
            "Import-Certificate -FilePath $data.path -CertStoreLocation $data.store -ErrorAction Stop | "
            "Select-Object Subject,Thumbprint,NotAfter",
            {"path": str(path), "store": store}, timeout=self.timeout)

    def certificate_remove(self, store: str, thumbprint: str) -> dict[str, Any]:
        self._windows("certificate removal")
        if store not in self.allowed_cert_stores:
            raise ToolExecutionError("Certificate store is not host-allowlisted.")
        thumb = re.sub(r"\\s+", "", self._value(thumbprint, "certificate thumbprint", 80)).upper()
        if not re.fullmatch(r"[A-F0-9]{40,64}", thumb) or thumb not in self.allowed_cert_thumbprints:
            raise ToolExecutionError("Certificate thumbprint must be explicitly host-allowlisted.")
        return self.base._run(
            "$item=Get-ChildItem -LiteralPath $data.store | Where-Object {$_.Thumbprint -eq $data.thumbprint};"
            "if(@($item).Count -ne 1){throw 'Certificate not found uniquely.'};"
            "Remove-Item -LiteralPath $item.PSPath -ErrorAction Stop;@{thumbprint=$data.thumbprint;removed=$true}",
            {"store": store, "thumbprint": thumb}, timeout=self.timeout)

    def module_install(self, name: str, version: str, repository: str) -> dict[str, Any]:
        self._windows("PowerShell module installation")
        allowed_versions = self.allowed_modules.get(name)
        if allowed_versions is None or version not in allowed_versions:
            raise ToolExecutionError("Module and version must be explicitly host-allowlisted.")
        if repository not in self.allowed_sources:
            raise ToolExecutionError("PowerShell repository is not host-allowlisted.")
        return self.base._run(
            "Install-Module -Name $data.name -RequiredVersion $data.version -Repository $data.repository "
            "-Scope CurrentUser -Force -ErrorAction Stop;"
            "Get-Module -ListAvailable -Name $data.name | Where-Object {$_.Version -eq [version]$data.version} | "
            "Select-Object Name,Version,Path",
            {"name": name, "version": version, "repository": repository}, timeout=120)

    def module_remove(self, name: str, version: str) -> dict[str, Any]:
        self._windows("PowerShell module removal")
        allowed_versions = self.allowed_modules.get(name)
        if allowed_versions is None or version not in allowed_versions:
            raise ToolExecutionError("Module and version must be explicitly host-allowlisted.")
        return self.base._run(
            "Uninstall-Module -Name $data.name -RequiredVersion $data.version -Force -ErrorAction Stop;"
            "@{name=$data.name;version=$data.version;removed=$true}",
            {"name": name, "version": version}, timeout=120)

    def package_install(self, name: str, source: str) -> dict[str, Any]:
        self._windows("package installation")
        if name not in self.allowed_packages or source not in self.allowed_sources:
            raise ToolExecutionError("Package name and source must be host-allowlisted.")
        return self.base._run(
            "Install-Package -Name $data.name -Source $data.source -Force -ErrorAction Stop | "
            "Select-Object Name,Version,ProviderName,Source",
            {"name": name, "source": source}, timeout=120)

    def ad_users(self, domain: str, search_base: str) -> dict[str, Any]:
        self._windows("Active Directory")
        self._ad_domain(domain)
        base = self._value(search_base, "AD search base", 512)
        domain_dn = ",".join(f"DC={part}" for part in domain.split("."))
        if not base.casefold().endswith(domain_dn.casefold()):
            raise ToolExecutionError("AD search base must be within the selected domain; verify the DN with your directory administrator.")
        return self.base._run(
            "Import-Module ActiveDirectory -ErrorAction Stop;"
            "Get-ADUser -Filter * -SearchBase $data.search_base -ResultSetSize 200 -Properties Enabled,Mail,Department | "
            "Select-Object SamAccountName,Name,Enabled,Mail,Department,DistinguishedName",
            {"search_base": base}, timeout=self.timeout)

    def ad_groups(self, domain: str, search_base: str) -> dict[str, Any]:
        self._windows("Active Directory")
        self._ad_domain(domain)
        base = self._value(search_base, "AD search base", 512)
        return self.base._run(
            "Import-Module ActiveDirectory -ErrorAction Stop;"
            "Get-ADGroup -Filter * -SearchBase $data.search_base -ResultSetSize 200 | "
            "Select-Object Name,GroupScope,GroupCategory,DistinguishedName",
            {"search_base": base}, timeout=self.timeout)

    def _ad_domain(self, domain: str) -> str:
        value = self._value(domain, "AD domain", 255).casefold()
        if value not in self.allowed_ad_domains:
            raise ToolExecutionError("AD domain is not host-allowlisted.")
        return value

    def ad_group_member(self, group_dn: str, member_dn: str, add: bool) -> dict[str, Any]:
        self._windows("Active Directory group membership")
        if group_dn not in self.allowed_ad_groups or member_dn not in self.allowed_ad_members:
            raise ToolExecutionError("AD group and member distinguished names must be host-allowlisted.")
        command = "Add-ADGroupMember" if add else "Remove-ADGroupMember"
        return self.base._run(
            f"Import-Module ActiveDirectory -ErrorAction Stop;{command} -Identity $data.group "
            "-Members $data.member -Confirm:$false -ErrorAction Stop;"
            "@{group=$data.group;member=$data.member;added=$data.add}",
            {"group": group_dn, "member": member_dn, "add": bool(add)}, timeout=self.timeout)

    def gpo_list(self, domain: str) -> dict[str, Any]:
        self._windows("Group Policy")
        self._ad_domain(domain)
        return self.base._run(
            "Import-Module GroupPolicy -ErrorAction Stop;Get-GPO -All -Domain $data.domain | "
            "Select-Object DisplayName,Id,Owner,GpoStatus,CreationTime,ModificationTime",
            {"domain": domain}, timeout=self.timeout)

    def gpo_create(self, name: str, domain: str) -> dict[str, Any]:
        self._windows("Group Policy")
        self._ad_domain(domain)
        if name not in self.allowed_gpos:
            raise ToolExecutionError("GPO name must be host-allowlisted.")
        return self.base._run(
            "Import-Module GroupPolicy -ErrorAction Stop;New-GPO -Name $data.name -Domain $data.domain -ErrorAction Stop | "
            "Select-Object DisplayName,Id,Owner",
            {"name": name, "domain": domain}, timeout=self.timeout)

    def gpo_link(self, name: str, target: str, domain: str, enabled: bool) -> dict[str, Any]:
        self._windows("Group Policy linking")
        self._ad_domain(domain)
        if name not in self.allowed_gpos or target not in self.allowed_gpo_targets:
            raise ToolExecutionError("GPO name and target OU must be host-allowlisted.")
        command = "New-GPLink" if enabled else "Remove-GPLink"
        return self.base._run(
            f"Import-Module GroupPolicy -ErrorAction Stop;{command} -Name $data.name -Target $data.target "
            "-Domain $data.domain -ErrorAction Stop | Select-Object DisplayName,Enabled,Target",
            {"name": name, "target": target, "domain": domain}, timeout=self.timeout)

    def tasks_create(self, name: str, template_id: str, schedule: str, at: str,
                     days: list[str] | None, task_path: str = "\\") -> dict[str, Any]:
        self._windows("scheduled task creation")
        if name not in self.allowed_tasks or template_id not in self.task_templates:
            raise ToolExecutionError("Task name and action template must be host-allowlisted.")
        if task_path not in self.allowed_task_paths:
            raise ToolExecutionError("Task path must be host-allowlisted.")
        if schedule not in {"Once", "Daily", "Weekly"}:
            raise ToolExecutionError("Schedule must be Once, Daily or Weekly.")
        if not isinstance(at, str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", at):
            raise ToolExecutionError("Task time must use 24-hour HH:MM format.")
        week_days = days or []
        if schedule == "Weekly" and (not 1 <= len(week_days) <= 7 or any(
            day not in {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}
            for day in week_days)):
            raise ToolExecutionError("Weekly tasks require valid day names.")
        if schedule != "Weekly" and week_days:
            raise ToolExecutionError("Days are only valid for weekly schedules.")
        template = self.task_templates[template_id]
        executable = template.get("executable", "")
        if not executable or not Path(executable).is_absolute():
            raise ToolExecutionError("Approved task template must specify an absolute executable path.")
        arguments = template.get("arguments", "")
        working = template.get("working_directory", str(self.base.root))
        payload = {"name": name, "path": task_path, "executable": executable, "arguments": arguments,
                   "working": working, "schedule": schedule, "at": at, "days": week_days}
        return self.base._run(
            "$action=New-ScheduledTaskAction -Execute $data.executable -Argument $data.arguments -WorkingDirectory $data.working;"
            "$clock=[datetime]::Today.Add([timespan]::Parse($data.at));"
            "if($data.schedule -eq 'Once'){$trigger=New-ScheduledTaskTrigger -Once -At $clock}"
            "elseif($data.schedule -eq 'Daily'){$trigger=New-ScheduledTaskTrigger -Daily -At $clock}"
            "else{$trigger=New-ScheduledTaskTrigger -Weekly -DaysOfWeek $data.days -At $clock};"
            "$principal=New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited;"
            "Register-ScheduledTask -TaskName $data.name -TaskPath $data.path -Action $action -Trigger $trigger -Principal $principal "
            "-Description 'ULTK approved task template' -Force -ErrorAction Stop | "
            "Select-Object TaskName,TaskPath,State",
            payload, timeout=self.timeout)

    def tasks_delete(self, name: str, task_path: str) -> dict[str, Any]:
        self._windows("scheduled task deletion")
        if name not in self.allowed_tasks:
            raise ToolExecutionError("Scheduled task name is not host-allowlisted.")
        path = self._value(task_path, "task path", 512)
    allowed_task_paths: frozenset[str] = frozenset({chr(92)}),
            raise ToolExecutionError("Task path must be an absolute Task Scheduler path.")
        return self.base._run(
            "Unregister-ScheduledTask -TaskName $data.name -TaskPath $data.path -Confirm:$false -ErrorAction Stop;"
            "@{name=$data.name;path=$data.path;deleted=$true}",
            {"name": name, "path": path}, timeout=self.timeout)


    def local_group_create(self, name: str, description: str = "") -> dict[str, Any]:
        self._windows("local group management")
        group = self._group(name)
        description = self._value(description, "group description", 256) if description else ""
        return self.base._run(
            "New-LocalGroup -Name $data.name -Description $data.description -ErrorAction Stop | "
            "Select-Object Name,Description,SID",
            {"name": group, "description": description}, timeout=self.timeout)

    def local_group_remove(self, name: str) -> dict[str, Any]:
        self._windows("local group management")
        group = self._group(name)
        return self.base._run(
            "Remove-LocalGroup -Name $data.name -ErrorAction Stop;@{name=$data.name;removed=$true}",
            {"name": group}, timeout=self.timeout)

    def ad_user_state(self, distinguished_name: str, enabled: bool) -> dict[str, Any]:
        self._windows("Active Directory user management")
        if distinguished_name not in self.allowed_ad_members:
            raise ToolExecutionError("AD user DN must be host-allowlisted.")
        command = "Enable-ADAccount" if enabled else "Disable-ADAccount"
        return self.base._run(
            f"Import-Module ActiveDirectory -ErrorAction Stop;{command} -Identity $data.dn -ErrorAction Stop;"
            "Get-ADUser -Identity $data.dn | Select-Object SamAccountName,Enabled,DistinguishedName",
            {"dn": distinguished_name}, timeout=self.timeout)

    def ad_user_remove(self, distinguished_name: str) -> dict[str, Any]:
        self._windows("Active Directory user deletion")
        if distinguished_name not in self.allowed_ad_members:
            raise ToolExecutionError("AD user DN must be host-allowlisted.")
        return self.base._run(
            "Import-Module ActiveDirectory -ErrorAction Stop;"
            "Remove-ADUser -Identity $data.dn -Confirm:$false -ErrorAction Stop;"
            "@{distinguished_name=$data.dn;removed=$true}",
            {"dn": distinguished_name}, timeout=self.timeout)

    def ad_group_create(self, name: str, path: str, scope: str, category: str) -> dict[str, Any]:
        self._windows("Active Directory group creation")
        if scope not in {"Global", "DomainLocal", "Universal"} or category not in {"Security", "Distribution"}:
            raise ToolExecutionError("Invalid AD group scope or category.")
        if path not in self.allowed_gpo_targets:
            raise ToolExecutionError("AD group creation path must be a host-allowlisted OU DN.")
        group_name = self._value(name, "AD group name", 128)
        return self.base._run(
            "Import-Module ActiveDirectory -ErrorAction Stop;"
            "New-ADGroup -Name $data.name -Path $data.path -GroupScope $data.scope "
            "-GroupCategory $data.category -ErrorAction Stop | "
            "Select-Object Name,GroupScope,GroupCategory,DistinguishedName",
            {"name": group_name, "path": path, "scope": scope, "category": category},
            timeout=self.timeout)

    def ad_group_remove(self, group_dn: str) -> dict[str, Any]:
        self._windows("Active Directory group deletion")
        if group_dn not in self.allowed_ad_groups:
            raise ToolExecutionError("AD group DN must be host-allowlisted.")
        return self.base._run(
            "Import-Module ActiveDirectory -ErrorAction Stop;"
            "Remove-ADGroup -Identity $data.dn -Confirm:$false -ErrorAction Stop;"
            "@{distinguished_name=$data.dn;removed=$true}",
            {"dn": group_dn}, timeout=self.timeout)

    def gpo_remove(self, name: str, domain: str) -> dict[str, Any]:
        self._windows("Group Policy deletion")
        self._ad_domain(domain)
        if name not in self.allowed_gpos:
            raise ToolExecutionError("GPO name must be host-allowlisted.")
        return self.base._run(
            "Import-Module GroupPolicy -ErrorAction Stop;"
            "Remove-GPO -Name $data.name -Domain $data.domain -Confirm:$false -ErrorAction Stop;"
            "@{name=$data.name;deleted=$true}",
            {"name": name, "domain": domain}, timeout=self.timeout)

    def gpo_registry_set(self, name: str, domain: str, key: str, value_name: str,
                         value: Any, value_type: str) -> dict[str, Any]:
        self._windows("Group Policy registry settings")
        self._ad_domain(domain)
        if name not in self.allowed_gpos or key not in self.allowed_gpo_registry_keys:
            raise ToolExecutionError("GPO name and registry policy key must be host-allowlisted.")
        if value_type not in {"String", "DWord", "QWord", "ExpandString", "MultiString"}:
            raise ToolExecutionError("Unsupported Group Policy registry value type.")
        if value_type in {"String", "ExpandString"} and not isinstance(value, str):
            raise ToolExecutionError("String policy values require text.")
        if value_type in {"DWord", "QWord"} and (type(value) is not int or value < 0):
            raise ToolExecutionError("Numeric policy values require a non-negative integer.")
        if value_type == "MultiString" and (not isinstance(value, list) or any(not isinstance(item, str) for item in value)):
            raise ToolExecutionError("MultiString policy values require a list of strings.")
        value_name = self._value(value_name, "policy value name", 256)
        return self.base._run(
            "Import-Module GroupPolicy -ErrorAction Stop;"
            "Set-GPRegistryValue -Name $data.name -Domain $data.domain -Key $data.key "
            "-ValueName $data.value_name -Type $data.type -Value $data.value -ErrorAction Stop | "
            "Select-Object DisplayName,Id",
            {"name": name, "domain": domain, "key": key, "value_name": value_name,
             "type": value_type, "value": value}, timeout=self.timeout)

    def package_install(self, name: str, version: str, source: str) -> dict[str, Any]:
        self._windows("package installation")
        versions = self.allowed_package_versions.get(name)
        if name not in self.allowed_packages or versions is None or version not in versions or source not in self.allowed_sources:
            raise ToolExecutionError("Package name, version and source must be explicitly host-allowlisted.")
        return self.base._run(
            "Install-Package -Name $data.name -RequiredVersion $data.version -Source $data.source "
            "-Force -ErrorAction Stop | Select-Object Name,Version,ProviderName,Source",
            {"name": name, "version": version, "source": source}, timeout=120)

    def package_remove(self, name: str, version: str) -> dict[str, Any]:
        self._windows("package removal")
        versions = self.allowed_package_versions.get(name)
        if name not in self.allowed_packages or versions is None or version not in versions:
            raise ToolExecutionError("Package name and version must be host-allowlisted.")
        return self.base._run(
            "Uninstall-Package -Name $data.name -RequiredVersion $data.version -Force -ErrorAction Stop;"
            "@{name=$data.name;version=$data.version;removed=$true}",
            {"name": name, "version": version}, timeout=120)

    def partition_resize(self, disk_number: int, partition_number: int, size_bytes: int) -> dict[str, Any]:
        self._windows("partition resize")
        if not self.allow_storage:
            raise ToolExecutionError("Storage mutations are disabled by host policy.")
        disk = self._disk(disk_number)
        if type(partition_number) is not int or partition_number < 1:
            raise ToolExecutionError("Partition number must be positive.")
        if type(size_bytes) is not int or not 1_048_576 <= size_bytes <= 2_000_000_000_000:
            raise ToolExecutionError("Partition size must be between 1 MiB and 2 TB.")
        return self.base._run(
            "$part=Get-Partition -DiskNumber $data.disk -PartitionNumber $data.partition -ErrorAction Stop;"
            "$supported=Get-PartitionSupportedSize -DiskNumber $data.disk -PartitionNumber $data.partition;"
            "if($data.size -lt $supported.SizeMin -or $data.size -gt $supported.SizeMax){throw 'Requested size is outside supported resize bounds.'};"
            "Resize-Partition -DiskNumber $data.disk -PartitionNumber $data.partition -Size $data.size -ErrorAction Stop | "
            "Select-Object DiskNumber,PartitionNumber,Size",
            {"disk": disk, "partition": partition_number, "size": size_bytes}, timeout=self.timeout)

    def security_inspect(self) -> dict[str, Any]:
        self._windows("security policy inspection")
        return self.base._run(
            "$audit=auditpol.exe /get /category:*;"
            "$defender=Get-MpComputerStatus -ErrorAction SilentlyContinue | "
            "Select-Object AntivirusEnabled,RealTimeProtectionEnabled,BehaviorMonitorEnabled,IoavProtectionEnabled,NISEnabled;"
            "@{audit_policy=$audit;defender=$defender}",
            timeout=self.timeout)

    def audit_policy_set(self, subcategory: str, success: bool, failure: bool) -> dict[str, Any]:
        self._windows("audit policy management")
        if not self.allow_security or subcategory not in self.allowed_audit:
            raise ToolExecutionError("Security policy changes are disabled or subcategory is not host-allowlisted.")
        success_arg = "enable" if success else "disable"
        failure_arg = "enable" if failure else "disable"
        return self.base._run(
            "auditpol.exe /set /subcategory:$data.subcategory /success:$data.success /failure:$data.failure;"
            "if($LASTEXITCODE -ne 0){throw 'auditpol failed'};"
            "auditpol.exe /get /subcategory:$data.subcategory",
            {"subcategory": subcategory, "success": success_arg, "failure": failure_arg},
            timeout=self.timeout)

    def defender_harden(self, setting: str) -> dict[str, Any]:
        self._windows("Defender policy management")
        if not self.allow_security or setting not in {
            "PUAProtection", "EnableControlledFolderAccess", "EnableNetworkProtection"
        }:
            raise ToolExecutionError("Defender hardening is disabled or setting is not in the safe allowlist.")
        return self.base._run(
            f"Set-MpPreference -{setting} Enabled -ErrorAction Stop;"
            f"Get-MpPreference | Select-Object {setting}",
            timeout=self.timeout)


def create_advanced_powershell_tools(
    *, base: PowerShellToolPack,
    allowed_session_commands: frozenset[str] = frozenset(),
    allowed_computers: frozenset[str] = frozenset(),
    allowed_remote_commands: frozenset[str] = frozenset(),
    allowed_registry_roots: frozenset[str] = frozenset(),
    allowed_firewall_rule_names: frozenset[str] = frozenset(),
    allowed_local_users: frozenset[str] = frozenset(),
    allowed_local_groups: frozenset[str] = frozenset(),
    local_user_password_env: str | None = None,
    allowed_update_kbs: frozenset[str] = frozenset(),
    allow_windows_update_install: bool = False,
    allowed_disk_numbers: frozenset[int] = frozenset(),
    allow_storage_mutations: bool = False,
    allowed_certificate_stores: frozenset[str] = frozenset({"Cert:\\CurrentUser\\My"}),
    allowed_certificate_thumbprints: frozenset[str] = frozenset(),
    allowed_install_modules: Mapping[str, frozenset[str]] | None = None,
    allowed_package_names: frozenset[str] = frozenset(),
    allowed_package_versions: Mapping[str, frozenset[str]] | None = None,
    allowed_package_sources: frozenset[str] = frozenset(),
    allowed_ad_domains: frozenset[str] = frozenset(),
    allowed_ad_group_dns: frozenset[str] = frozenset(),
    allowed_ad_member_dns: frozenset[str] = frozenset(),
    allowed_gpo_names: frozenset[str] = frozenset(),
    allowed_gpo_targets: frozenset[str] = frozenset(),
    allowed_gpo_registry_keys: frozenset[str] = frozenset(),
    allowed_task_names: frozenset[str] = frozenset(),
    allowed_task_paths: frozenset[str] = frozenset({chr(92)}),
    approved_task_templates: Mapping[str, Mapping[str, str]] | None = None,
    allowed_audit_subcategories: frozenset[str] = frozenset(),
    allow_security_policy_changes: bool = False,
) -> tuple[FunctionTool, ...]:
    """Build the advanced PowerShell tool families under explicit host configuration."""
    pack = AdvancedPowerShellToolPack(
        base, allowed_session_commands=allowed_session_commands,
        allowed_computers=allowed_computers, allowed_remote_commands=allowed_remote_commands,
        allowed_registry_roots=allowed_registry_roots,
        allowed_firewall_rule_names=allowed_firewall_rule_names,
        allowed_local_users=allowed_local_users, allowed_local_groups=allowed_local_groups,
        local_user_password_env=local_user_password_env, allowed_update_kbs=allowed_update_kbs,
        allow_windows_update_install=allow_windows_update_install,
        allowed_disk_numbers=allowed_disk_numbers, allow_storage_mutations=allow_storage_mutations,
        allowed_certificate_stores=allowed_certificate_stores,
        allowed_certificate_thumbprints=allowed_certificate_thumbprints,
        allowed_install_modules=allowed_install_modules, allowed_package_names=allowed_package_names,
        allowed_package_versions=allowed_package_versions,
        allowed_package_sources=allowed_package_sources, allowed_ad_domains=allowed_ad_domains,
        allowed_ad_group_dns=allowed_ad_group_dns, allowed_ad_member_dns=allowed_ad_member_dns,
        allowed_gpo_names=allowed_gpo_names, allowed_gpo_targets=allowed_gpo_targets,
        allowed_gpo_registry_keys=allowed_gpo_registry_keys,
        allowed_task_names=allowed_task_names, allowed_task_paths=allowed_task_paths,
        approved_task_templates=approved_task_templates,
        allowed_audit_subcategories=allowed_audit_subcategories,
        allow_security_policy_changes=allow_security_policy_changes,
    )
    tools: list[FunctionTool] = []

    def add(name: str, description: str, props: dict[str, Any], required: list[str],
            capability: str, fn: Any, timeout: int = 35) -> None:
        tools.append(FunctionTool(name, description, object_schema(props, required),
                                  capability, fn, timeout=timeout, output_limit=base.max_output))

    s = {"type": "string", "minLength": 1, "maxLength": 2048}
    name = {"type": "string", "minLength": 1, "maxLength": 128}
    session_id = {"type": "string", "minLength": 32, "maxLength": 32}
    empty: dict[str, Any] = {}

    # Persistent local PowerShell runspaces.
    add("powershell.session_open", "Open an isolated persistent PowerShell process with host-allowlisted cmdlets.", {"label": {"type": "string", "minLength": 1, "maxLength": 100}}, ["label"], "powershell:session:create", pack.sessions.open)
    add("powershell.session_list", "List persistent PowerShell sessions owned by this tool pack.", empty, [], "powershell:session:read", pack.sessions.list)
    add("powershell.session_execute", "Execute a bounded sequence of allowlisted cmdlets and session-variable assignments in an isolated persistent runspace.", {"session_id": session_id, "script": {"type": "string", "minLength": 1, "maxLength": 32000}}, ["session_id", "script"], "powershell:session:execute", pack.sessions.execute)
    add("powershell.session_workflow", "Prevalidate then execute up to 20 sequential PowerShell steps in one persistent session.", {"session_id": session_id, "steps": {"type": "array", "minItems": 1, "maxItems": 20, "items": {"type": "string", "minLength": 1, "maxLength": 32000}}}, ["session_id", "steps"], "powershell:workflow:execute", pack.sessions.workflow, 120)
    add("powershell.session_variables", "List variable names and metadata in one isolated PowerShell session.", {"session_id": session_id}, ["session_id"], "powershell:session:read", pack.sessions.variables)
    add("powershell.session_get_variable", "Read one explicitly named variable from an isolated PowerShell session.", {"session_id": session_id, "name": name}, ["session_id", "name"], "powershell:session:variables:read", pack.sessions.get_variable)
    add("powershell.session_close", "Terminate and remove one persistent PowerShell session.", {"session_id": session_id}, ["session_id"], "powershell:session:close", pack.sessions.close)

    # Authorized remoting; only host-allowlisted computers and cmdlets are callable.
    def remote(computer: str, command: str, parameters: dict[str, Any] | None = None,
               use_ssl: bool = True) -> dict[str, Any]:
        pack._windows("PowerShell remoting")
        host = pack._value(computer, "remote computer", 255)
        if host.casefold() not in pack.allowed_computers:
            raise ToolExecutionError("Remote computer is not host-allowlisted.")
        if command not in pack.allowed_remote_commands:
            raise ToolExecutionError("Remote cmdlet is not host-allowlisted.")
        values = parameters or {}
        if not isinstance(values, dict) or len(values) > 30:
            raise ToolExecutionError("Remote parameters must be an object with at most 30 entries.")
        if any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,63}", key) or
               isinstance(value, dict) or (isinstance(value, list) and (len(value) > 100 or any(not isinstance(item, (str, int, float, bool, type(None))) for item in value))) or
               not isinstance(value, (str, int, float, bool, type(None), list))
               for key, value in values.items()):
            raise ToolExecutionError("Remote parameter names or values are invalid.")
        if len(json.dumps(values, ensure_ascii=False)) > 16_000:
            raise ToolExecutionError("Remote parameter payload exceeds 16 KB.")
        return pack.base._run(
            "$parameters=@{};foreach($p in $data.parameters.PSObject.Properties){$parameters[$p.Name]=$p.Value};"
            "$script={param($commandName,$arguments);"
            "$cmd=Get-Command -Name $commandName -CommandType Cmdlet -ErrorAction Stop;"
            "& $cmd @arguments};"
            "Invoke-Command -ComputerName $data.computer -UseSSL:$data.use_ssl -ScriptBlock $script "
            "-ArgumentList $data.command,$parameters -ErrorAction Stop",
            {"computer": host, "command": command, "parameters": values, "use_ssl": bool(use_ssl)},
            timeout=120)
    add("powershell.remote_invoke", "Invoke one host-allowlisted cmdlet with bounded data arguments on an allowlisted remote computer using WS-Man; integrated authentication.", {"computer": s, "command": name, "parameters": {"type": "object"}, "use_ssl": {"type": "boolean"}}, ["computer", "command"], "powershell:remoting:execute", remote, 130)

    # Registry mutation.
    add("powershell.registry_set_value", "Create or set one registry value inside a host-allowlisted writable registry subtree.", {"path": s, "name": s, "value": {}, "value_type": {"type": "string", "enum": ["String", "ExpandString", "MultiString", "DWord", "QWord", "Binary"]}}, ["path", "name", "value", "value_type"], "powershell:registry:write", pack.registry_set)
    add("powershell.registry_remove_value", "Remove one named value inside a host-allowlisted registry subtree.", {"path": s, "name": s}, ["path", "name"], "powershell:registry:value:delete", pack.registry_remove_value)
    add("powershell.registry_remove_key", "Remove one empty registry key inside a host-allowlisted subtree; recursive deletion is not exposed.", {"path": s}, ["path"], "powershell:registry:key:delete", pack.registry_remove_key)

    # Firewall rules.
    add("powershell.firewall_list_rules", "List Windows Defender Firewall rules.", empty, [], "powershell:read:firewall", pack.firewall_list)
    add("powershell.firewall_create_rule", "Create a firewall rule whose internal name is host-allowlisted.", {"name": name, "display_name": s, "direction": {"type": "string", "enum": ["Inbound", "Outbound"]}, "action": {"type": "string", "enum": ["Allow", "Block"]}, "protocol": {"type": "string", "enum": ["TCP", "UDP", "Any"]}, "local_port": {"type": ["integer", "null"], "minimum": 1, "maximum": 65535}, "remote_port": {"type": ["integer", "null"], "minimum": 1, "maximum": 65535}, "profile": {"type": "string", "enum": ["Domain", "Private", "Public", "Any"]}, "enabled": {"type": "boolean"}}, ["name", "display_name", "direction", "action", "protocol", "profile", "enabled"], "powershell:firewall:create", pack.firewall_create)
    add("powershell.firewall_enable_rule", "Enable one host-allowlisted firewall rule.", {"name": name}, ["name"], "powershell:firewall:write", lambda name: pack.firewall_state(name, True))
    add("powershell.firewall_disable_rule", "Disable one host-allowlisted firewall rule.", {"name": name}, ["name"], "powershell:firewall:disable", lambda name: pack.firewall_state(name, False))
    add("powershell.firewall_remove_rule", "Remove one host-allowlisted firewall rule.", {"name": name}, ["name"], "powershell:firewall:delete", pack.firewall_remove)

    # Local Windows users/groups.
    add("powershell.list_local_users", "List local Windows user accounts.", empty, [], "powershell:read:identity", pack.local_users)
    add("powershell.list_local_groups", "List local Windows groups.", empty, [], "powershell:read:identity", pack.local_groups)
    add("powershell.create_local_user", "Create one host-allowlisted local user using a host-injected password environment secret.", {"name": name, "description": {"type": "string", "maxLength": 256}}, ["name"], "powershell:identity:user:create", pack.local_user_create)
    add("powershell.enable_local_user", "Enable one host-allowlisted local user.", {"name": name}, ["name"], "powershell:identity:user:write", lambda name: pack.local_user_enabled(name, True))
    add("powershell.disable_local_user", "Disable one host-allowlisted local user.", {"name": name}, ["name"], "powershell:identity:user:disable", lambda name: pack.local_user_enabled(name, False))
    add("powershell.remove_local_user", "Remove one host-allowlisted local user.", {"name": name}, ["name"], "powershell:identity:user:delete", pack.local_user_remove)
    add("powershell.create_local_group", "Create one host-allowlisted local group.", {"name": name, "description": {"type": "string", "maxLength": 256}}, ["name"], "powershell:identity:group:create", pack.local_group_create)
    add("powershell.remove_local_group", "Remove one host-allowlisted local group.", {"name": name}, ["name"], "powershell:identity:group:delete", pack.local_group_remove)
    add("powershell.add_local_group_member", "Add one host-allowlisted user to one host-allowlisted local group.", {"user_name": name, "group_name": name}, ["user_name", "group_name"], "powershell:identity:group:write", lambda user_name, group_name: pack.local_group_member(user_name, group_name, True))
    add("powershell.remove_local_group_member", "Remove one host-allowlisted user from one host-allowlisted local group.", {"user_name": name, "group_name": name}, ["user_name", "group_name"], "powershell:identity:group:remove_member", lambda user_name, group_name: pack.local_group_member(user_name, group_name, False))

    # Windows Update.
    add("powershell.windows_update_available", "List available Windows updates using host-installed PSWindowsUpdate.", empty, [], "powershell:read:updates", pack.windows_update_list, 90)
    add("powershell.windows_update_history", "Read installed Windows update history.", empty, [], "powershell:read:updates", pack.windows_update_history)
    add("powershell.windows_update_install", "Install only host-allowlisted KB updates; automatic reboot is suppressed.", {"kb_ids": {"type": "array", "minItems": 1, "maxItems": 20, "items": {"type": "string", "pattern": "^KB[0-9]{5,10}$"}}}, ["kb_ids"], "powershell:updates:install", pack.windows_update_install, 150)

    # Disks and volumes.
    add("powershell.list_disks", "List physical Windows disks.", empty, [], "powershell:read:storage", pack.disks)
    add("powershell.list_partitions", "List partitions on one host-allowlisted disk.", {"disk_number": {"type": "integer", "minimum": 0}}, ["disk_number"], "powershell:read:storage", pack.partitions)
    add("powershell.list_volumes", "List Windows volumes and free space.", empty, [], "powershell:read:storage", pack.volumes)
    add("powershell.set_disk_online", "Bring one host-allowlisted disk online or offline.", {"disk_number": {"type": "integer", "minimum": 0}, "online": {"type": "boolean"}}, ["disk_number", "online"], "powershell:storage:state", pack.disk_online)
    add("powershell.initialize_disk", "Initialize only a host-allowlisted RAW disk as GPT or MBR.", {"disk_number": {"type": "integer", "minimum": 0}, "partition_style": {"type": "string", "enum": ["GPT", "MBR"]}}, ["disk_number", "partition_style"], "powershell:storage:initialize", pack.disk_initialize)
    add("powershell.resize_partition", "Resize a partition only within the size bounds reported by Windows Storage cmdlets.", {"disk_number": {"type": "integer", "minimum": 0}, "partition_number": {"type": "integer", "minimum": 1}, "size_bytes": {"type": "integer", "minimum": 1048576, "maximum": 2000000000000}}, ["disk_number", "partition_number", "size_bytes"], "powershell:storage:partition:resize", pack.partition_resize)
    add("powershell.create_partition", "Create a bounded partition on one host-allowlisted disk; formatting is not exposed.", {"disk_number": {"type": "integer", "minimum": 0}, "size_bytes": {"type": "integer", "minimum": 1048576, "maximum": 2000000000000}, "drive_letter": {"type": ["string", "null"], "pattern": "^[D-Zd-z]$"}}, ["disk_number", "size_bytes"], "powershell:storage:partition:create", pack.partition_create)

    # Certificate stores.
    add("powershell.list_certificates", "List certificates in a host-allowlisted certificate store.", {"store": s}, ["store"], "powershell:read:certificates", pack.certificate_list)
    add("powershell.import_public_certificate", "Import a project-local public CER/CRT/DER certificate into a host-allowlisted store; PFX/private-key import is not exposed.", {"path": s, "store": s}, ["path", "store"], "powershell:certificates:import", pack.certificate_import)
    add("powershell.remove_certificate", "Remove a certificate only when its thumbprint is host-allowlisted.", {"store": s, "thumbprint": s}, ["store", "thumbprint"], "powershell:certificates:delete", pack.certificate_remove)

    # Package/module installation.
    add("powershell.install_module", "Install one host-allowlisted PowerShell module/version from a host-allowlisted repository.", {"name": name, "version": s, "repository": name}, ["name", "version", "repository"], "powershell:modules:install", pack.module_install, 150)
    add("powershell.remove_module", "Remove one host-allowlisted PowerShell module/version.", {"name": name, "version": s}, ["name", "version"], "powershell:modules:remove", pack.module_remove, 150)
    add("powershell.install_package", "Install one host-allowlisted package/version from a host-allowlisted package source.", {"name": name, "version": s, "source": name}, ["name", "version", "source"], "powershell:packages:install", pack.package_install, 150)
    add("powershell.remove_package", "Uninstall one host-allowlisted package/version.", {"name": name, "version": s}, ["name", "version"], "powershell:packages:remove", pack.package_remove, 150)

    # Active Directory and Group Policy.
    add("powershell.ad_list_users", "List bounded AD users within a host-allowlisted domain/search base.", {"domain": s, "search_base": s}, ["domain", "search_base"], "powershell:read:active_directory", pack.ad_users, 60)
    add("powershell.ad_list_groups", "List bounded AD groups within a host-allowlisted domain/search base.", {"domain": s, "search_base": s}, ["domain", "search_base"], "powershell:read:active_directory", pack.ad_groups, 60)
    add("powershell.ad_enable_user", "Enable one host-allowlisted Active Directory user DN.", {"distinguished_name": s}, ["distinguished_name"], "powershell:active_directory:user:write", lambda distinguished_name: pack.ad_user_state(distinguished_name, True), 60)
    add("powershell.ad_disable_user", "Disable one host-allowlisted Active Directory user DN.", {"distinguished_name": s}, ["distinguished_name"], "powershell:active_directory:user:disable", lambda distinguished_name: pack.ad_user_state(distinguished_name, False), 60)
    add("powershell.ad_remove_user", "Remove one host-allowlisted Active Directory user DN.", {"distinguished_name": s}, ["distinguished_name"], "powershell:active_directory:user:delete", pack.ad_user_remove, 60)
    add("powershell.ad_create_group", "Create an AD group under a host-allowlisted OU.", {"name": s, "path": s, "scope": {"type": "string", "enum": ["Global", "DomainLocal", "Universal"]}, "category": {"type": "string", "enum": ["Security", "Distribution"]}}, ["name", "path", "scope", "category"], "powershell:active_directory:group:create", pack.ad_group_create, 60)
    add("powershell.ad_remove_group", "Remove one host-allowlisted AD group DN.", {"group_dn": s}, ["group_dn"], "powershell:active_directory:group:delete", pack.ad_group_remove, 60)
    add("powershell.ad_add_group_member", "Add one host-allowlisted AD member DN to one host-allowlisted group DN.", {"group_dn": s, "member_dn": s}, ["group_dn", "member_dn"], "powershell:active_directory:group:write", lambda group_dn, member_dn: pack.ad_group_member(group_dn, member_dn, True))
    add("powershell.ad_remove_group_member", "Remove one host-allowlisted AD member DN from one host-allowlisted group DN.", {"group_dn": s, "member_dn": s}, ["group_dn", "member_dn"], "powershell:active_directory:group:remove_member", lambda group_dn, member_dn: pack.ad_group_member(group_dn, member_dn, False))
    add("powershell.gpo_list", "List Group Policy Objects in a host-allowlisted AD domain.", {"domain": s}, ["domain"], "powershell:read:gpo", pack.gpo_list, 60)
    add("powershell.gpo_create", "Create a host-allowlisted GPO in a host-allowlisted domain.", {"name": name, "domain": s}, ["name", "domain"], "powershell:gpo:create", pack.gpo_create, 60)
    add("powershell.gpo_delete", "Delete one host-allowlisted GPO in a host-allowlisted domain.", {"name": name, "domain": s}, ["name", "domain"], "powershell:gpo:delete", pack.gpo_remove, 60)
    add("powershell.gpo_set_registry_value", "Set one Group Policy registry setting only under a host-allowlisted GPO and registry key.", {"name": name, "domain": s, "key": s, "value_name": s, "value": {}, "value_type": {"type": "string", "enum": ["String", "DWord", "QWord", "ExpandString", "MultiString"]}}, ["name", "domain", "key", "value_name", "value", "value_type"], "powershell:gpo:settings:write", pack.gpo_registry_set, 60)
    add("powershell.gpo_link", "Link a host-allowlisted GPO to a host-allowlisted OU target.", {"name": name, "target": s, "domain": s}, ["name", "target", "domain"], "powershell:gpo:link", lambda name, target, domain: pack.gpo_link(name, target, domain, True), 60)
    add("powershell.gpo_unlink", "Remove a host-allowlisted GPO link from a host-allowlisted OU target.", {"name": name, "target": s, "domain": s}, ["name", "target", "domain"], "powershell:gpo:unlink", lambda name, target, domain: pack.gpo_link(name, target, domain, False), 60)

    # Scheduled task templates.
    add("powershell.create_scheduled_task", "Create/update a scheduled task from a host-approved executable template and bounded schedule.", {"name": name, "template_id": name, "schedule": {"type": "string", "enum": ["Once", "Daily", "Weekly"]}, "at": {"type": "string", "pattern": "^(?:[01][0-9]|2[0-3]):[0-5][0-9]$"}, "days": {"type": "array", "items": {"type": "string"}, "maxItems": 7}, "task_path": s}, ["name", "template_id", "schedule", "at"], "powershell:tasks:create", pack.tasks_create, 60)
    add("powershell.delete_scheduled_task", "Delete one host-allowlisted scheduled task.", {"name": name, "task_path": s}, ["name", "task_path"], "powershell:tasks:delete", pack.tasks_delete)

    # Security policy.
    add("powershell.inspect_security_policy", "Inspect Windows audit policy and Defender protection status.", empty, [], "powershell:read:security", pack.security_inspect)
    add("powershell.set_audit_policy", "Enable/disable success/failure auditing for a host-allowlisted audit subcategory.", {"subcategory": s, "success": {"type": "boolean"}, "failure": {"type": "boolean"}}, ["subcategory", "success", "failure"], "powershell:security:audit:write", pack.audit_policy_set)
    add("powershell.harden_defender_setting", "Enable one supported Defender hardening feature; weakening settings are not exposed.", {"setting": {"type": "string", "enum": ["PUAProtection", "EnableControlledFolderAccess", "EnableNetworkProtection"]}}, ["setting"], "powershell:security:defender:write", pack.defender_harden)
    return tuple(tools)

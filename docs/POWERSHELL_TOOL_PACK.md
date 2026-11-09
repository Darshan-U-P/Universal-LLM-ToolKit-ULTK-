# Dedicated PowerShell Tool Pack

ULTK provides a PowerShell-native tool pack separate from generic terminal execution. Built-in operations use fixed PowerShell cmdlet workflows; the model does not submit free-form PowerShell source for these operations.

## Installation

    from ultk import ToolEngine

    engine = ToolEngine(policy=your_permission_policy)
    engine.install_powershell_tools(
        working_root=r"C:\Projects",
        executable=r"C:\Program Files\PowerShell\7\pwsh.exe",
        allowed_modules=frozenset({"Microsoft.PowerShell.Management"}),
    )

If no executable is specified, the pack looks for PowerShell 7 (pwsh) first and Windows PowerShell (powershell.exe) second on Windows. On non-Windows systems it looks for pwsh; Windows administration tools fail closed there.

## Included tools

- Shell/environment: current location and process-visible environment variables.
- System: OS version, computer manufacturer/model/memory/CPU, installed hotfixes.
- Processes: bounded process listing.
- Services: list, start, stop, restart.
- Networking: IP configuration, TCP connections, DNS cache and firewall profile inspection.
- Registry: read a key's values and list immediate subkeys. No registry writes are exposed.
- Event logs: bounded recent event retrieval from System, Application, Security or Setup.
- Scheduled tasks: list, inspect, start and stop.
- Modules: list available modules and inspect commands from host-allowlisted modules.
- Remoting: test WS-Management connectivity to a host-allowlisted computer.
- Scripts: parse a project-local .ps1 without execution; optionally execute a host-pinned script.

## Approved script execution

Free-form model-generated PowerShell is deliberately not exposed. A host may configure allowed_script_hashes, keyed by script ID, and a script_root. Each script must be named <script_id>.ps1 and its SHA-256 digest must match at installation and immediately before execution. The model can select only an approved ID and pass bounded string arguments. Script files are trusted code and execute with the ULTK process's OS privileges; hash pinning provides integrity, not sandboxing.

## Security and permissions

- PowerShell runs with NoLogo, NoProfile and NonInteractive options and a host-authored encoded wrapper.
- Built-in operations use fixed cmdlet templates; tool arguments are passed as JSON data, not interpolated into command text.
- Process environment is reduced to basic OS/PowerShell variables; output and execution time are bounded.
- Each write-capable family has a distinct capability. Require human approval for service/task changes and approved script execution.
- The host configures executable path, trusted script hashes, allowed modules and remoting computer allowlist.
- PowerShell execution policy is not a security boundary. Do not rely on it to sandbox scripts.
- This pack does not elevate privileges. A tool can perform only actions allowed to the ULTK process identity.

## Not included in this increment

Registry writes, firewall rule changes, user/group/account administration, package installation, Windows Update, disk/volume management, certificate store mutation, arbitrary cmdlet invocation, persistent interactive runspaces, general-purpose remoting command execution, DSC and Intune/Active Directory administration are not included.

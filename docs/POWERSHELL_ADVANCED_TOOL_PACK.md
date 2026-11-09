# Advanced PowerShell Administration Tool Families

This increment extends the dedicated PowerShell pack without introducing an unrestricted model-supplied PowerShell script tool. Every operation has a separate ULTK capability, and mutating operations are constrained by host-owned resource allowlists and opt-in flags.

## Installation

Install the original pack and the advanced pack independently:

    from ultk import ToolEngine

    engine = ToolEngine(policy=your_permission_policy)

    engine.install_powershell_tools(
        executable=r"C:\Program Files\PowerShell\7\pwsh.exe",
        working_root=r"C:\ULTK-Workspace",
        allowed_modules=frozenset({"PSWindowsUpdate", "ActiveDirectory", "GroupPolicy"}),
        allowed_computers=frozenset({"srv01.example.internal"}),
    )

    engine.install_advanced_powershell_tools(
        executable=r"C:\Program Files\PowerShell\7\pwsh.exe",
        working_root=r"C:\ULTK-Workspace",
        allowed_modules=frozenset({"PSWindowsUpdate", "ActiveDirectory", "GroupPolicy"}),
        allowed_computers=frozenset({"srv01.example.internal"}),
        allowed_session_commands=frozenset({
            "Get-Process", "Get-Service", "Get-ComputerInfo", "Get-Date",
            "Select-Object", "Sort-Object", "Measure-Object",
            "Write-Output",
        }),
        allowed_remote_commands=frozenset({"Get-Service", "Get-Process", "Get-EventLog"}),
        advanced_policy={
            "allowed_registry_roots": frozenset({r"HKLM:\Software\ULTK"}),
            "allowed_firewall_rule_names": frozenset({"ULTK-HTTPS-In"}),
            "allowed_local_users": frozenset({"ultk-worker"}),
            "allowed_local_groups": frozenset({"ULTK-Operators"}),
            "local_user_password_env": "ULTK_PROVISIONED_ACCOUNT_PASSWORD",
            "allowed_update_kbs": frozenset({"KB5030001"}),
            "allow_windows_update_install": False,
            "allowed_disk_numbers": frozenset({3}),
            "allowed_drive_letters": frozenset({"R", "S"}),
            "allow_storage_mutations": False,
            "allowed_certificate_stores": frozenset({r"Cert:\CurrentUser\My"}),
            "allowed_certificate_thumbprints": frozenset(),
            "allowed_install_modules": {"PSWindowsUpdate": frozenset({"2.2.1.5"})},
            "allowed_package_names": frozenset({"ExamplePackage"}),
            "allowed_package_versions": {"ExamplePackage": frozenset({"1.2.3"})},
            "allowed_package_sources": frozenset({"InternalRepo"}),
            "allowed_ad_domains": frozenset({"example.internal"}),
            "allowed_ad_group_dns": frozenset({"CN=ULTK-Operators,OU=Groups,DC=example,DC=internal"}),
            "allowed_ad_member_dns": frozenset({"CN=ultk-worker,OU=Users,DC=example,DC=internal"}),
            "allowed_gpo_names": frozenset({"ULTK-Workstation-Policy"}),
            "allowed_gpo_targets": frozenset({"OU=Workstations,DC=example,DC=internal"}),
            "allowed_gpo_registry_keys": frozenset({r"HKLM\Software\Policies\ULTK"}),
            "allowed_task_names": frozenset({"ULTK-Maintenance"}),
            "allowed_task_paths": frozenset({chr(92) + "ULTK" + chr(92)}),
            "approved_task_templates": {
                "maintenance": {
                    "executable": r"C:\ULTK\maintenance.exe",
                    "arguments": "--approved-maintenance",
                    "working_directory": r"C:\ULTK",
                }
            },
            "allowed_audit_subcategories": frozenset({"Logon", "Logoff"}),
            "allow_security_policy_changes": False,
            "allow_audit_disable": False,
            "approved_security_templates": {},
        },
    )

advanced_policy is host application configuration. Do not populate it from an LLM request. Defaults are deny/disabled; only configure resources the host intends to expose.

## Implemented families

### 1. Persistent interactive PowerShell sessions

- session_open, session_list, session_execute, session_workflow, session_variables, session_get_variable, session_close.
- A session can also own persistent remote PSSessions through remote_session_open, remote_session_invoke and remote_session_close.
- Each session owns a separate long-running PowerShell process and runspace. Session variables persist between calls and are isolated from other sessions.
- session_workflow accepts up to 20 steps, validates every step before executing any step, then executes sequentially in the same runspace. Runtime failures can occur after earlier steps have completed; this is not a transaction and side effects are not rolled back.
- Session commands must be explicitly host-allowlisted by exact cmdlet name. Only cmdlets are accepted; aliases, functions, dynamic command names and non-cmdlet command types are rejected. A session may be opened solely for persistent remoting when local command allowlists are empty.
- The parser rejects member access, method invocation, type expressions, subexpressions, scriptblocks, redirection, function/class definitions, loops and control-flow constructs. Assignments are limited to session variables. Several high-impact cmdlets are hard-blocked even if accidentally allowlisted.
- Sessions are in-memory processes, not durable runspaces: process/service restart destroys them. The host must associate each session ID with an authenticated principal, enforce ownership on every call, expire abandoned sessions and close them on logout.

This is a deliberately restricted interactive command environment, not a general unrestricted PowerShell terminal. It is not an AST-level sandbox; host allowlisted cmdlets are trusted code and can still have side effects through their own parameters. Commands such as file writes, process termination, service mutation and remote execution belong to their dedicated tool families.

### 2. Authorized PowerShell remoting

- remote_invoke invokes one exact host-allowlisted cmdlet on an exact host-allowlisted computer.
- One-shot remote_invoke uses WS-Management Invoke-Command. Persistent remote_session_open creates a PSSession, remote_session_invoke reuses it, and remote_session_close removes it. UseSSL is enabled by default and configurable at session creation.
- Uses the Windows integrated authentication context of the ULTK process. No model-provided credentials, Basic authentication or arbitrary scriptblocks are accepted. Persistent remote PSSessions are owned by a local ULTK session and are removed on explicit close or best-effort local session shutdown.
- Remote cmdlet names and parameter keys/values are bounded. Remote hosts and cmdlets must be host-allowlisted; dynamic code execution and remote session-control cmdlets are blocked. The remote endpoint, firewall, WinRM listener, authentication, and machine identity remain host/administrator responsibilities.
- Remote command/module execution occurs on the remote host with the ULTK identity's remoting privileges. Treat allowlisted remote cmdlets and modules as trusted executable code.

### 3. Registry writes

- Set/create a value, remove one value, or remove one empty key.
- Writable paths must be descendants of exact host-configured registry roots. Wildcards and parent traversal are rejected.
- Registry value types are constrained to String, ExpandString, MultiString, DWORD, QWORD and Binary with type-specific validation.
- Recursive key deletion is not exposed.

### 4. Windows Defender Firewall

- List rules; create, enable, disable and remove a rule.
- Every mutating rule name must be exact and host-allowlisted.
- Protocol, direction, action, port and profile are enumerated/bounded. Host policy should reserve dedicated rule names for ULTK-managed rules.

### 5. Local users and groups

- List users/groups; create, enable, disable and remove host-allowlisted users; create/remove host-allowlisted groups; add/remove a user from an allowlisted group.
- Account names and group names are exact allowlist entries.
- User creation obtains its password from a host-configured environment variable. The password is not an LLM argument or tool result. The host should rotate and protect that secret and ensure the ULTK process environment is not exposed to untrusted plugins.
- Membership in privileged groups is a high-impact operation and should require human approval.

### 6. Windows Update

- List available updates (through the host-installed, host-allowlisted PSWindowsUpdate module) and inspect installed hotfix history.
- Install only explicitly host-allowlisted KB IDs, only when allow_windows_update_install=True.
- Automatic reboot is suppressed. A separate, human-controlled maintenance/reboot process is required.
- PSWindowsUpdate and its dependencies are trusted third-party code; pin and verify their versions and repository.

### 7. Disks, partitions and volumes

- Inspect disks, partitions and volumes.
- Set a host-allowlisted disk online/offline, initialize a host-allowlisted RAW disk as GPT/MBR, create a bounded partition, resize a partition within Windows-reported supported bounds, assign an allowlisted drive letter, and change an allowlisted volume label.
- Mutations require allow_storage_mutations=True and exact host-allowlisted disk numbers.
- Formatting, partition deletion, disk cleaning, secure erase, dynamic disk conversion and storage-pool administration are not exposed in this increment. Disk/partition operations can cause data loss; require human approval and backups.

### 8. Certificate stores

- List certificates in exact host-allowlisted Cert: stores.
- Import public CER/CRT/DER certificates from working_root.
- Remove only certificates whose thumbprints are explicitly host-allowlisted.
- PFX/private-key import/export and private-key extraction are not exposed.

### 9. Package and module management

- Install/uninstall exact host-allowlisted PowerShell module versions from host-allowlisted repositories.
- Install/uninstall package versions pinned by package name, version and source allowlists.
- Installation can execute package/module installation scripts. Treat repositories, package providers, packages and modules as trusted supply-chain inputs; use internal repositories and pin hashes/signatures where supported.

### 10. Active Directory and Group Policy

- List AD users/groups within a host-allowlisted domain and domain DN search base.
- Create, enable, disable or remove host-allowlisted AD users; create/remove host-allowlisted groups; add/remove exact host-allowlisted group/member DNs. AD user creation uses the same host-injected password secret as local account provisioning.
- List, create and delete host-allowlisted GPOs; link/unlink them only to exact host-allowlisted OU targets; set registry policy values only under host-allowlisted GPO names and registry policy keys.
- Requires trusted RSAT ActiveDirectory and GroupPolicy modules and a domain identity with appropriately scoped rights. Domain, group, member, GPO, OU and policy-key allowlists must be configured by the host.
- This increment does not provide arbitrary LDAP filters, arbitrary DN targeting, domain-controller discovery, forest-wide schema changes, replication management, or arbitrary GPO script deployment.

### 11. Scheduled tasks

- Create/update a scheduled task using a host-approved task template; delete an exact host-allowlisted task.
- The template fixes the executable, arguments and working directory. The model can select the template and a bounded Once/Daily/Weekly trigger, not submit an arbitrary executable or action.
- Task names and task paths are host-allowlisted. Tasks run as the current user with an interactive logon and limited run level.
- No highest-privilege run level, password credentials, arbitrary triggers, arbitrary task actions or remote scheduled task deployment.

### 12. Windows security policy

- Inspect local security policy exported by secedit, account policy, audit policy, Defender status/preferences and firewall profiles.
- Change success/failure audit settings only for host-allowlisted audit subcategories and only when allow_security_policy_changes=True. Disabling either audit outcome also requires the separate allow_audit_disable=True opt-in; by default the tool only enables auditing.
- Apply local security policy only from host-approved INF templates pinned by SHA-256, copied to private staging and limited to host-approved secedit areas. No model-authored INF path or policy content is accepted.
- Enable selected Defender hardening features (PUA protection, Controlled Folder Access and Network Protection). Weakening settings are not exposed.
- Security policy changes require explicit capabilities and human approval. Local policy, domain GPO and Defender Tamper Protection may override or reject changes.

### Host-pinned security template configuration

The approved_security_templates host policy maps a template ID to a relative INF file, SHA-256 digest and approved secedit areas. Example shape:

    "approved_security_templates": {
        "workstation-baseline": {
            "path": "security/workstation-baseline.inf",
            "sha256": "HOST_COMPUTED_64_HEX_SHA256",
            "areas": ["securitypolicy", "user_rights"]
        }
    }

The file must reside under working_root, contain no symlink path components, be at most 1 MB and match its pinned hash. The tool stages and re-hashes a private copy before calling secedit. Applying any template also requires allow_security_policy_changes=True and the host's approval policy. Keep templates in version control, review them before approval and update the hash whenever the content changes.

## Authorization and operational requirements

Each tool declares its own capability, including powershell:session:execute, powershell:remoting:execute, powershell:remoting:session:*, powershell:registry:write, powershell:firewall:create, powershell:identity:*, powershell:updates:install, powershell:storage:*, powershell:certificates:*, powershell:modules:install, powershell:active_directory:*, powershell:gpo:*, powershell:tasks:* and powershell:security:*.

Configure production policy to require human approval for all state-changing operations, especially remote commands, registry/firewall changes, identity changes, Windows Update, storage, certificate deletion, package installation, AD/GPO changes, scheduled task changes and security policy. A capability name is not itself an approval mechanism; the host PermissionPolicy must enforce the approval flow.

## Verification status

Tests have been authored but intentionally not run during implementation. No claim is made that Windows integration, remoting, RSAT, Windows Update, storage, firewall, certificates, scheduled tasks or security-policy operations have been validated. See docs/VERIFICATION_LEDGER.md.

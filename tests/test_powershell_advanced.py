"""Advanced PowerShell tool pack tests; deliberately deferred until final validation."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ultk.builtins.powershell import PowerShellToolPack
from ultk.builtins.powershell_advanced import (
    AdvancedPowerShellToolPack,
    create_advanced_powershell_tools,
)
from ultk.exceptions import ToolExecutionError


@pytest.fixture
def base(tmp_path: Path) -> PowerShellToolPack:
    executable = shutil.which("pwsh")
    if not executable:
        pytest.skip("PowerShell 7 is required.")
    return PowerShellToolPack(executable=executable, working_root=tmp_path)


def test_advanced_factory_registers_separate_permission_families(base: PowerShellToolPack) -> None:
    tools = create_advanced_powershell_tools(base=base)
    names = {tool.spec.name for tool in tools}
    expected = {
        "powershell.session_open", "powershell.session_execute", "powershell.session_workflow",
        "powershell.session_close", "powershell.remote_invoke",
        "powershell.remote_session_open", "powershell.remote_session_invoke", "powershell.remote_session_close",
        "powershell.registry_set_value", "powershell.firewall_create_rule",
        "powershell.create_local_user", "powershell.create_local_group",
        "powershell.windows_update_install", "powershell.initialize_disk",
        "powershell.create_partition", "powershell.resize_partition",
        "powershell.import_public_certificate", "powershell.install_module",
        "powershell.install_package", "powershell.ad_list_users",
        "powershell.ad_create_user", "powershell.ad_create_group", "powershell.gpo_set_registry_value",
        "powershell.apply_security_template",
        "powershell.create_scheduled_task", "powershell.delete_scheduled_task",
        "powershell.inspect_security_policy", "powershell.set_audit_policy",
        "powershell.harden_defender_setting",
    }
    assert expected <= names
    assert len(names) >= 50
    assert all(tool.spec.capabilities for tool in tools)


def test_persistent_sessions_are_disabled_without_host_command_allowlist(base: PowerShellToolPack) -> None:
    pack = AdvancedPowerShellToolPack(base)
    with pytest.raises(ToolExecutionError):
        pack.sessions.open("disabled by default")


def test_persistent_sessions_reject_high_risk_cmdlet_allowlists(base: PowerShellToolPack) -> None:
    with pytest.raises(ToolExecutionError):
        AdvancedPowerShellToolPack(base, allowed_session_commands=frozenset({"Get-Service", "Invoke-Expression"}))
    with pytest.raises(ToolExecutionError):
        AdvancedPowerShellToolPack(base, allowed_session_commands=frozenset({"Get-Service", "Remove-Item"}))
    with pytest.raises(ToolExecutionError):
        AdvancedPowerShellToolPack(base, allowed_session_commands=frozenset({"Set-MpPreference"}))


def test_registry_write_requires_path_inside_exact_host_root(base: PowerShellToolPack) -> None:
    pack = AdvancedPowerShellToolPack(
        base, allowed_registry_roots=frozenset({r"HKLM:\Software\Example"})
    )
    assert pack._registry_path(r"HKLM:\Software\Example\Settings") == r"HKLM:\Software\Example\Settings"
    with pytest.raises(ToolExecutionError):
        pack._registry_path(r"HKLM:\Software\ExampleEvil\Settings")
    with pytest.raises(ToolExecutionError):
        pack._registry_path(r"HKCU:\Software\Other")


def test_firewall_rules_require_exact_names(base: PowerShellToolPack) -> None:
    pack = AdvancedPowerShellToolPack(base, allowed_firewall_rule_names=frozenset({"ULTK-HTTPS-In"}))
    assert pack._firewall_name("ULTK-HTTPS-In") == "ULTK-HTTPS-In"
    with pytest.raises(ToolExecutionError):
        pack._firewall_name("Allow-All")


def test_local_users_and_groups_require_exact_allowlists(base: PowerShellToolPack) -> None:
    pack = AdvancedPowerShellToolPack(
        base, allowed_local_users=frozenset({"ultk-worker"}),
        allowed_local_groups=frozenset({"ULTK-Operators"}),
    )
    assert pack._user("ultk-worker") == "ultk-worker"
    assert pack._group("ULTK-Operators") == "ULTK-Operators"
    with pytest.raises(ToolExecutionError):
        pack._user("Administrator")
    with pytest.raises(ToolExecutionError):
        pack._group("Administrators")


def test_disk_numbers_are_host_allowlisted(base: PowerShellToolPack) -> None:
    pack = AdvancedPowerShellToolPack(base, allowed_disk_numbers=frozenset({3}))
    assert pack._disk(3) == 3
    with pytest.raises(ToolExecutionError):
        pack._disk(0)


def test_ad_domains_are_host_allowlisted(base: PowerShellToolPack) -> None:
    pack = AdvancedPowerShellToolPack(
        base, allowed_ad_domains=frozenset({"example.internal"}),
        allowed_gpo_names=frozenset({"ULTK-Workstation-Policy"}),
    )
    assert pack._ad_domain("EXAMPLE.INTERNAL") == "example.internal"
    with pytest.raises(ToolExecutionError):
        pack._ad_domain("untrusted.example")


def test_package_install_requires_exact_pinned_version_and_source(base: PowerShellToolPack) -> None:
    pack = AdvancedPowerShellToolPack(
        base, allowed_package_names=frozenset({"ExamplePackage"}),
        allowed_package_versions={"ExamplePackage": frozenset({"1.2.3"})},
        allowed_package_sources=frozenset({"InternalRepo"}),
    )
    with pytest.raises(ToolExecutionError):
        pack.package_install("ExamplePackage", "latest", "InternalRepo")
    with pytest.raises(ToolExecutionError):
        pack.package_install("ExamplePackage", "1.2.3", "PSGallery")


def test_certificate_thumbprints_are_exactly_pinned(base: PowerShellToolPack) -> None:
    pack = AdvancedPowerShellToolPack(
        base, allowed_certificate_stores=frozenset({r"Cert:\CurrentUser\My"}),
        allowed_certificate_thumbprints=frozenset({"A" * 40}),
    )
    assert "A" * 40 in pack.allowed_cert_thumbprints
    assert "B" * 40 not in pack.allowed_cert_thumbprints


def test_task_paths_and_names_are_host_allowlisted(base: PowerShellToolPack) -> None:
    task_root = chr(92) + "ULTK" + chr(92)
    pack = AdvancedPowerShellToolPack(
        base, allowed_task_names=frozenset({"ULTK-Maintenance"}),
        allowed_task_paths=frozenset({task_root}),
    )
    assert "ULTK-Maintenance" in pack.allowed_tasks
    assert task_root in pack.allowed_task_paths


def test_audit_policy_changes_are_disabled_by_default(base: PowerShellToolPack) -> None:
    pack = AdvancedPowerShellToolPack(base)
    assert pack.allow_security is False
    assert pack.allow_audit_disable is False


def test_windows_update_install_requires_explicit_policy(base: PowerShellToolPack) -> None:
    pack = AdvancedPowerShellToolPack(base)
    assert pack.allow_update_install is False
    assert pack.allowed_kbs == frozenset()


def test_storage_mutations_are_disabled_by_default(base: PowerShellToolPack) -> None:
    pack = AdvancedPowerShellToolPack(base, allowed_disk_numbers=frozenset({3}))
    assert pack.allow_storage is False
    assert pack._disk(3) == 3


def test_gpo_registry_keys_are_host_allowlisted(base: PowerShellToolPack) -> None:
    pack = AdvancedPowerShellToolPack(
        base, allowed_ad_domains=frozenset({"example.internal"}),
        allowed_gpo_names=frozenset({"ULTK-Policy"}),
        allowed_gpo_registry_keys=frozenset({r"HKLM\Software\Policies\Example"}),
    )
    with pytest.raises(ToolExecutionError):
        pack.gpo_registry_set(
            "ULTK-Policy", "example.internal", r"HKLM\Software\Policies\Other",
            "Enabled", 1, "DWord",
        )



def test_persistent_session_variables_survive_calls_and_are_isolated(base: PowerShellToolPack) -> None:
    from ultk.builtins.powershell_advanced import PersistentPowerShellSessions

    manager = PersistentPowerShellSessions(
        base.executable, base.root, frozenset({"Write-Output"}), 15, base.max_output
    )
    first = manager.open("first")
    second = manager.open("second")
    try:
        manager.execute(first["session_id"], "$ultkValue = 'persistent-state'")
        response = manager.execute(first["session_id"], "Write-Output $ultkValue")
        assert "persistent-state" in str(response)
        with pytest.raises(ToolExecutionError):
            manager.get_variable(second["session_id"], "ultkValue")
    finally:
        manager.close(first["session_id"])
        manager.close(second["session_id"])


def test_persistent_session_rejects_member_access_and_unapproved_commands(base: PowerShellToolPack) -> None:
    from ultk.builtins.powershell_advanced import PersistentPowerShellSessions

    manager = PersistentPowerShellSessions(
        base.executable, base.root, frozenset({"Write-Output"}), 15, base.max_output
    )
    session = manager.open("restricted")
    try:
        with pytest.raises(ToolExecutionError):
            manager.validate(session["session_id"], "$x.ToString()")
        with pytest.raises(ToolExecutionError):
            manager.validate(session["session_id"], "Get-Process")
    finally:
        manager.close(session["session_id"])


def test_session_workflow_prevalidates_all_steps(base: PowerShellToolPack) -> None:
    from ultk.builtins.powershell_advanced import PersistentPowerShellSessions

    manager = PersistentPowerShellSessions(
        base.executable, base.root, frozenset({"Write-Output"}), 15, base.max_output
    )
    session = manager.open("workflow")
    try:
        with pytest.raises(ToolExecutionError):
            manager.workflow(session["session_id"], [
                "Write-Output 'step-one'",
                "Start-Process calc.exe",
            ])
    finally:
        manager.close(session["session_id"])


def test_session_variable_reader_rejects_internal_names(base: PowerShellToolPack) -> None:
    from ultk.builtins.powershell_advanced import PersistentPowerShellSessions

    manager = PersistentPowerShellSessions(
        base.executable, base.root, frozenset({"Write-Output"}), 15, base.max_output
    )
    with pytest.raises(ToolExecutionError):
        manager.get_variable("a" * 32, "allowed")


def test_session_tool_factory_requires_separate_capabilities(base: PowerShellToolPack) -> None:
    tools = create_advanced_powershell_tools(
        base=base, allowed_session_commands=frozenset({"Write-Output"})
    )
    by_name = {tool.spec.name: tool for tool in tools}
    assert by_name["powershell.session_execute"].spec.capabilities == frozenset({"powershell:session:execute"})
    assert by_name["powershell.remote_invoke"].spec.capabilities == frozenset({"powershell:remoting:execute"})



def test_remote_cmdlet_allowlist_blocks_dynamic_code(base: PowerShellToolPack) -> None:
    with pytest.raises(ToolExecutionError):
        AdvancedPowerShellToolPack(
            base, allowed_computers=frozenset({"srv01"}),
            allowed_remote_commands=frozenset({"Invoke-Expression"}),
        )


def test_remote_session_manager_requires_explicit_host_and_cmdlet_allowlists(base: PowerShellToolPack) -> None:
    from ultk.builtins.powershell_advanced import PersistentPowerShellSessions

    manager = PersistentPowerShellSessions(
        base.executable, base.root, frozenset(), 15, base.max_output,
        frozenset({"srv01.example.internal"}), frozenset({"Get-Service"}),
    )
    assert manager.allowed_computers == frozenset({"srv01.example.internal"})
    assert manager.allowed_remote_commands == frozenset({"Get-Service"})



def test_persistent_session_blocks_output_variable_parameter_aliases(base: PowerShellToolPack) -> None:
    from ultk.builtins.powershell_advanced import PersistentPowerShellSessions

    manager = PersistentPowerShellSessions(
        base.executable, base.root, frozenset({"Get-Process"}), 15, base.max_output
    )
    session = manager.open("variable-guard")
    try:
        with pytest.raises(ToolExecutionError):
            manager.validate(session["session_id"], "Get-Process -OutVariable allowed")
        with pytest.raises(ToolExecutionError):
            manager.validate(session["session_id"], "Get-Process -ov allowed")
    finally:
        manager.close(session["session_id"])



def test_security_template_requires_host_sha256_pin(base: PowerShellToolPack) -> None:
    import hashlib

    template = base.root / "approved-policy.inf"
    template.write_text("[Version]\nSignature=\"$CHICAGO$\"\n", encoding="utf-8")
    digest = hashlib.sha256(template.read_bytes()).hexdigest()
    pack = AdvancedPowerShellToolPack(
        base,
        allow_security_policy_changes=True,
        approved_security_templates={
            "workstation-baseline": {
                "path": "approved-policy.inf",
                "sha256": digest,
                "areas": ["securitypolicy", "user_rights"],
            }
        },
    )
    resolved = pack._resolve_security_template("workstation-baseline")
    assert resolved["sha256"] == digest
    assert resolved["areas"] == ["securitypolicy", "user_rights"]


def test_security_template_rejects_modified_and_unapproved_files(base: PowerShellToolPack) -> None:
    import hashlib

    template = base.root / "approved-policy.inf"
    template.write_text("[Version]\nSignature=\"$CHICAGO$\"\n", encoding="utf-8")
    digest = hashlib.sha256(template.read_bytes()).hexdigest()
    pack = AdvancedPowerShellToolPack(
        base,
        approved_security_templates={
            "baseline": {
                "path": "approved-policy.inf",
                "sha256": digest,
                "areas": ["securitypolicy"],
            }
        },
    )
    template.write_text("[Version]\nSignature=\"$CHICAGO$\"\n; changed\n", encoding="utf-8")
    with pytest.raises(ToolExecutionError):
        pack._resolve_security_template("baseline")
    with pytest.raises(ToolExecutionError):
        pack._resolve_security_template("not-approved")


def test_security_template_rejects_parent_traversal(base: PowerShellToolPack) -> None:
    pack = AdvancedPowerShellToolPack(
        base,
        approved_security_templates={
            "escape": {
                "path": "../outside.inf",
                "sha256": "0" * 64,
                "areas": ["securitypolicy"],
            }
        },
    )
    with pytest.raises(ToolExecutionError):
        pack._resolve_security_template("escape")



def test_remote_computer_allowlist_rejects_host_lists_and_wildcards(base: PowerShellToolPack) -> None:
    with pytest.raises(ToolExecutionError):
        AdvancedPowerShellToolPack(
            base, allowed_computers=frozenset({"srv01,srv02"}),
            allowed_remote_commands=frozenset({"Get-Service"}),
        )
    with pytest.raises(ToolExecutionError):
        AdvancedPowerShellToolPack(
            base, allowed_computers=frozenset({"*.example.internal"}),
            allowed_remote_commands=frozenset({"Get-Service"}),
        )


def test_non_ssl_remoting_is_disabled_by_default(base: PowerShellToolPack) -> None:
    pack = AdvancedPowerShellToolPack(
        base, allowed_computers=frozenset({"srv01.example.internal"}),
        allowed_remote_commands=frozenset({"Get-Service"}),
    )
    assert pack.allow_insecure_remoting is False

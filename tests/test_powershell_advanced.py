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
        "powershell.registry_set_value", "powershell.firewall_create_rule",
        "powershell.create_local_user", "powershell.create_local_group",
        "powershell.windows_update_install", "powershell.initialize_disk",
        "powershell.create_partition", "powershell.resize_partition",
        "powershell.import_public_certificate", "powershell.install_module",
        "powershell.install_package", "powershell.ad_list_users",
        "powershell.ad_create_group", "powershell.gpo_set_registry_value",
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


def test_ad_domains_and_gpo_names_are_host_allowlisted(base: PowerShellToolPack) -> None:
    pack = AdvancedPowerShellToolPack(
        base, allowed_ad_domains=frozenset({"example.internal"}),
        allowed_gpo_names=frozenset({"ULTK-Workstation-Policy"}),
    )
    assert pack._ad_domain("EXAMPLE.INTERNAL") == "example.internal"
    with pytest.raises(ToolExecutionError):
        pack._ad_domain("untrusted.example")
    with pytest.raises(ToolExecutionError):
        pack.gpo_create("Unapproved", "example.internal")


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
    with pytest.raises(ToolExecutionError):
        pack.audit_policy_set("Logon", True, True)


def test_windows_update_install_requires_explicit_policy(base: PowerShellToolPack) -> None:
    pack = AdvancedPowerShellToolPack(base)
    with pytest.raises(ToolExecutionError):
        pack.windows_update_install(["KB5030001"])


def test_storage_mutations_are_disabled_by_default(base: PowerShellToolPack) -> None:
    pack = AdvancedPowerShellToolPack(base, allowed_disk_numbers=frozenset({3}))
    with pytest.raises(ToolExecutionError):
        pack.disk_initialize(3, "GPT")


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

"""Computer/OS pack tests; authored but intentionally deferred until final validation."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from ultk.builtins.computer_os import ComputerOSPack, create_computer_os_tools
from ultk.exceptions import ToolExecutionError


@pytest.fixture
def pack(tmp_path: Path) -> ComputerOSPack:
    root = tmp_path / "managed"
    root.mkdir()
    return ComputerOSPack(
        filesystem_root=root,
        state_database=tmp_path / "state" / "computer.sqlite3",
        allowed_services=frozenset({"ultk-test-service"}),
        allow_posix_chmod=True,
    )


def test_persistent_desktop_session_lifecycle(pack: ComputerOSPack) -> None:
    created = pack.session_create("test desktop", {"active_window": "Editor", "monitor": 1})
    session_id = created["session_id"]
    assert pack.session_get(session_id)["state"]["active_window"] == "Editor"
    pack.session_update(session_id, {"active_window": "Terminal"})
    assert pack.session_get(session_id)["state"]["active_window"] == "Terminal"
    assert pack.session_list()[0]["session_id"] == session_id
    pack.session_close(session_id)
    assert pack.session_get(session_id)["closed"] is True
    assert pack.session_list() == []


def test_session_state_must_be_json_compatible(pack: ComputerOSPack) -> None:
    with pytest.raises(ToolExecutionError):
        pack.session_create("bad state", {"not_json": object()})


def test_session_update_rejects_closed_session(pack: ComputerOSPack) -> None:
    session_id = pack.session_create("closing")["session_id"]
    pack.session_close(session_id)
    with pytest.raises(ToolExecutionError):
        pack.session_update(session_id, {"x": 1})


def test_filesystem_root_rejects_traversal(pack: ComputerOSPack) -> None:
    with pytest.raises(ToolExecutionError):
        pack.resolve("../outside")


def test_filesystem_root_rejects_symlink_escape(pack: ComputerOSPack, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (pack.root / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ToolExecutionError):
        pack.resolve("escape/file.txt")


@pytest.mark.skipif(os.name == "nt", reason="POSIX chmod is not supported on Windows.")
def test_chmod_rejects_symlink_even_when_target_is_inside_root(pack: ComputerOSPack) -> None:
    target = pack.root / "target.txt"
    target.write_text("data", encoding="utf-8")
    (pack.root / "link.txt").symlink_to(target)
    with pytest.raises(ToolExecutionError):
        pack.chmod("link.txt", 0o600)


def test_chmod_rejects_out_of_range_mode(pack: ComputerOSPack) -> None:
    target = pack.root / "target.txt"
    target.write_text("data", encoding="utf-8")
    with pytest.raises(ToolExecutionError):
        pack.chmod("target.txt", 0o1000)


def test_service_mutation_requires_exact_host_allowlist(pack: ComputerOSPack) -> None:
    with pytest.raises(ToolExecutionError):
        pack.service_action("sshd", "stop")
    with pytest.raises(ToolExecutionError):
        pack.service_action("ultk-test-service; whoami", "stop")


def test_event_watch_persistence(pack: ComputerOSPack) -> None:
    watch = pack.create_event_watch("", "test journal watch")
    assert pack.list_event_watches()[0]["watch_id"] == watch["watch_id"]
    pack.delete_event_watch(watch["watch_id"])
    assert pack.list_event_watches() == []


def test_keyboard_shortcut_rejects_secure_attention_sequence(pack: ComputerOSPack) -> None:
    with pytest.raises(ToolExecutionError):
        pack.keyboard_shortcut(["ctrl", "alt", "delete"])


def test_keyboard_sequence_prevalidates_all_hotkeys(pack: ComputerOSPack) -> None:
    with pytest.raises(ToolExecutionError):
        pack.keyboard_sequence([{"action": "type", "text": "should not be sent"},
                                {"action": "hotkey", "keys": ["ctrl", "alt", "delete"]}])


def test_device_eject_requires_exact_host_allowlist(pack: ComputerOSPack) -> None:
    with pytest.raises(ToolExecutionError):
        pack.eject_device("/dev/sdb")


def test_windows_acl_mutation_is_disabled_by_default(pack: ComputerOSPack) -> None:
    with pytest.raises(ToolExecutionError):
        pack.grant_windows_acl("some-file", "S-1-5-18", "RX")


def test_tool_factory_registers_all_expected_domains(tmp_path: Path) -> None:
    tools = create_computer_os_tools(
        filesystem_root=tmp_path / "files",
        state_database=tmp_path / "state.sqlite3",
    )
    names = {tool.spec.name for tool in tools}
    assert len(names) >= 25
    assert {
        "computer_os.desktop_session_create",
        "computer_os.list_monitors",
        "computer_os.snap_window",
        "computer_os.arrange_windows",
        "computer_os.virtual_desktops",
        "computer_os.keyboard_shortcut",
        "computer_os.keyboard_sequence",
        "computer_os.accessibility_inspect",
        "computer_os.service_action",
        "computer_os.chmod",
        "computer_os.hardware_info",
        "computer_os.usb_devices",
        "computer_os.read_recent_events",
    } <= names
    assert all(tool.spec.capabilities for tool in tools)


def test_linux_event_watch_channel_validation(pack: ComputerOSPack) -> None:
    if os.name == "nt":
        pytest.skip("Linux journal channel validation is not applicable.")
    if __import__("platform").system() != "Linux":
        pytest.skip("Linux journal channel validation is not applicable.")
    with pytest.raises(ToolExecutionError):
        pack.create_event_watch("arbitrary-command", "bad channel")


def test_desktop_workflow_prevalidates_all_steps_before_input(pack: ComputerOSPack, monkeypatch) -> None:
    from types import SimpleNamespace
    import ultk.builtins.computer_os as computer_os

    calls = []
    backend = SimpleNamespace(
        click=lambda **kwargs: calls.append(("click", kwargs)),
        moveTo=lambda *args, **kwargs: calls.append(("move", args)),
        write=lambda *args, **kwargs: calls.append(("write", args)),
        press=lambda *args, **kwargs: calls.append(("press", args)),
        hotkey=lambda *args, **kwargs: calls.append(("hotkey", args)),
    )
    monkeypatch.setattr(computer_os, "_optional", lambda name: backend)
    with pytest.raises(ToolExecutionError, match="unsupported action"):
        pack.desktop_workflow([
            {"action": "click", "x": 20, "y": 30},
            {"action": "unknown"},
        ])
    assert calls == []


def test_desktop_workflow_executes_bounded_pointer_and_keyboard_steps(pack: ComputerOSPack, monkeypatch) -> None:
    from types import SimpleNamespace
    import ultk.builtins.computer_os as computer_os

    calls = []
    backend = SimpleNamespace(
        click=lambda **kwargs: calls.append(("click", kwargs)),
        moveTo=lambda *args, **kwargs: calls.append(("move", args)),
        write=lambda *args, **kwargs: calls.append(("write", args)),
        press=lambda *args, **kwargs: calls.append(("press", args)),
        hotkey=lambda *args, **kwargs: calls.append(("hotkey", args)),
    )
    monkeypatch.setattr(computer_os, "_optional", lambda name: backend)
    result = pack.desktop_workflow([
        {"action": "move", "x": 120, "y": 240},
        {"action": "click", "x": 120, "y": 240, "button": "right"},
        {"action": "type", "text": "ULTK"},
        {"action": "hotkey", "keys": ["ctrl", "s"]},
    ])
    assert result["steps_completed"] == 4
    assert [item[0] for item in calls] == ["move", "click", "write", "hotkey"]


def test_multi_monitor_snap_uses_monitor_origin(pack: ComputerOSPack, monkeypatch) -> None:
    from types import SimpleNamespace

    window = SimpleNamespace(
        title="Editor",
        moveTo=lambda x, y: setattr(window, "position", (x, y)),
        resizeTo=lambda width, height: setattr(window, "size", (width, height)),
    )
    monkeypatch.setattr(pack, "monitors", lambda: [
        {"index": 0, "x": -1920, "y": 0, "width": 1920, "height": 1080, "primary": False},
        {"index": 1, "x": 0, "y": 0, "width": 2560, "height": 1440, "primary": True},
    ])
    monkeypatch.setattr(pack, "_window", lambda selector: window)
    result = pack.snap_window("Editor", 0, "right")
    assert result["geometry"] == {"x": -960, "y": 0, "width": 960, "height": 1080}
    assert window.position == (-960, 0)
    assert window.size == (960, 1080)


def test_desktop_workflow_tool_is_registered(tmp_path: Path) -> None:
    names = {tool.spec.name for tool in create_computer_os_tools(
        filesystem_root=tmp_path / "files",
        state_database=tmp_path / "state.sqlite3",
    )}
    assert "computer_os.desktop_workflow" in names

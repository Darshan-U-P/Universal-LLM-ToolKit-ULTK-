from __future__ import annotations

import ctypes
import os
import platform
from pathlib import Path
from types import SimpleNamespace

import pytest

from ultk.builtins.computer_os import ComputerOSPack
from ultk.exceptions import ToolExecutionError


@pytest.fixture
def pack(tmp_path: Path) -> ComputerOSPack:
    root = tmp_path / "managed"
    root.mkdir()
    return ComputerOSPack(
        filesystem_root=root,
        state_database=tmp_path / "state" / "computer.sqlite3",
        allowed_eject_devices=frozenset({"USB\\VID_1234&PID_5678\\SERIAL"}),
    )


def test_sway_tree_is_converted_to_bounded_window_rows(pack, monkeypatch) -> None:
    monkeypatch.setattr(pack, "_sway_request", lambda *args: {
        "type": "root",
        "nodes": [{
            "type": "output", "nodes": [{
                "type": "workspace", "name": "2:web", "nodes": [{
                    "type": "con", "id": 77, "name": "Browser",
                    "app_id": "firefox", "focused": True,
                    "rect": {"x": 10, "y": 20, "width": 900, "height": 700},
                    "nodes": [], "floating_nodes": [],
                }],
            }],
        }],
    })
    rows = pack._sway_windows()
    assert rows == [{
        "title": "Browser", "app_id": "firefox", "left": 10, "top": 20,
        "width": 900, "height": 700, "active": True, "visible": True,
        "scratchpad": False, "workspace": "2:web", "container_id": 77, "backend": "sway-ipc",
    }]


def test_sway_window_action_uses_container_id_and_validated_geometry(pack, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(pack, "_sway_window", lambda selector: {
        "title": "Editor", "container_id": 12,
    })
    monkeypatch.setattr(pack, "_sway_request", lambda *args: calls.append(args) or [{"success": True}])
    result = pack.sway_window_action("Editor", "move", x=-120, y=50)
    assert result["backend"] == "sway-ipc"
    assert calls == [("[con_id=12] move position -120 50",)]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"action": "move", "x": 40001, "y": 0},
        {"action": "resize", "width": 20, "height": 100},
        {"action": "resize", "width": 100, "height": 20001},
    ],
)
def test_sway_window_action_rejects_unbounded_geometry(pack, monkeypatch, kwargs) -> None:
    monkeypatch.setattr(pack, "_sway_window", lambda selector: {
        "title": "Editor", "container_id": 12,
    })
    with pytest.raises(ToolExecutionError):
        pack.sway_window_action("Editor", **kwargs)


def test_sway_window_selector_rejects_ambiguous_matches(pack, monkeypatch) -> None:
    monkeypatch.setattr(pack, "_sway_windows", lambda: [
        {"title": "Editor - one"}, {"title": "Editor - two"},
    ])
    with pytest.raises(ToolExecutionError, match="exactly one"):
        pack._sway_window("Editor")


def test_sway_workspace_creation_rejects_existing_workspace(pack, monkeypatch) -> None:
    monkeypatch.setattr(pack, "_sway_enabled", lambda: True)
    monkeypatch.setattr(pack, "_sway_request", lambda *args: [
        {"num": 3, "name": "3:term", "focused": True},
    ])
    with pytest.raises(ToolExecutionError, match="already exists"):
        pack.virtual_desktops("create", 3)


def test_sway_workspace_switch_requires_existing_workspace(pack, monkeypatch) -> None:
    monkeypatch.setattr(pack, "_sway_enabled", lambda: True)
    monkeypatch.setattr(pack, "_sway_request", lambda *args: [])
    with pytest.raises(ToolExecutionError, match="does not exist"):
        pack.virtual_desktops("switch", 3)


def test_atspi_accessibility_click_invokes_exact_named_element(pack, monkeypatch) -> None:
    class Actions:
        nActions = 1

        @staticmethod
        def getName(index):
            return "click"

        @staticmethod
        def doAction(index):
            return True

    class Node:
        name = "Save"

        def __init__(self):
            self.childCount = 0

        @staticmethod
        def queryAction():
            return Actions()

    node = Node()
    app = SimpleNamespace(name="Editor", childCount=1, getChildAtIndex=lambda index: node)
    desktop = SimpleNamespace(childCount=1, getChildAtIndex=lambda index: app)
    fake = SimpleNamespace(Registry=SimpleNamespace(getDesktop=lambda index: desktop))
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr("ultk.builtins.computer_os._optional", lambda name: fake)
    result = pack.accessibility_click("Editor", "Save")
    assert result["backend"] == "Linux AT-SPI"
    assert result["status"] == "invoke_requested"


def test_atspi_accessibility_click_rejects_duplicate_element_names(pack, monkeypatch) -> None:
    class Node:
        name = "Save"
        childCount = 0

    children = [Node(), Node()]
    app = SimpleNamespace(name="Editor", childCount=2, getChildAtIndex=lambda index: children[index])
    desktop = SimpleNamespace(childCount=1, getChildAtIndex=lambda index: app)
    fake = SimpleNamespace(Registry=SimpleNamespace(getDesktop=lambda index: desktop))
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr("ultk.builtins.computer_os._optional", lambda name: fake)
    with pytest.raises(ToolExecutionError, match="exactly one"):
        pack.accessibility_click("Editor", "Save")


def test_macos_accessibility_click_uses_ax_press(pack, monkeypatch) -> None:
    calls = []
    root = object()
    element = object()
    fake_quartz = SimpleNamespace(
        kAXPressAction="AXPress",
        kAXErrorSuccess=0,
        AXUIElementPerformAction=lambda selected, action: calls.append((selected, action)) or 0,
    )
    monkeypatch.setattr(pack, "_mac_accessibility_app", lambda title: (fake_quartz, root, "Editor"))
    monkeypatch.setattr(
        pack, "_mac_ax_value",
        lambda quartz, selected, attribute: "save-button" if selected is element and attribute == "AXIdentifier" else
        ([element] if selected is root and attribute == "AXChildren" else None),
    )
    result = pack._mac_accessibility_click("Editor", "save-button")
    assert calls == [(element, "AXPress")]
    assert result["backend"] == "macOS Accessibility API"


def test_macos_accessibility_inspection_returns_roles_and_identifiers(pack, monkeypatch) -> None:
    root, child = object(), object()
    fake_quartz = SimpleNamespace()
    monkeypatch.setattr(pack, "_mac_accessibility_app", lambda title: (fake_quartz, root, "Editor"))
    values = {
        (root, "AXRole"): "AXApplication",
        (root, "AXChildren"): [child],
        (child, "AXRole"): "AXButton",
        (child, "AXTitle"): "Save",
        (child, "AXIdentifier"): "save-button",
        (child, "AXEnabled"): True,
    }
    monkeypatch.setattr(pack, "_mac_ax_value", lambda quartz, node, attr: values.get((node, attr)))
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    result = pack.accessibility_inspect("Editor", 10)
    assert result["backend"] == "macOS Accessibility API"
    assert any(item["automation_id"] == "save-button" for item in result["elements"])


def test_windows_safe_eject_uses_configuration_manager_api(pack, monkeypatch) -> None:
    class NativeFunction:
        def __init__(self, callback):
            self.callback = callback
            self.argtypes = None
            self.restype = None

        def __call__(self, *args):
            return self.callback(*args)

    def locate(devinst_ptr, device_id, flags):
        devinst_ptr._obj.value = 42
        return 0

    def eject(devinst, veto_ptr, veto_name, max_chars, flags):
        veto_ptr._obj.value = 0
        return 0

    fake_dll = SimpleNamespace(
        CM_Locate_DevNodeW=NativeFunction(locate),
        CM_Request_Device_EjectW=NativeFunction(eject),
    )
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: fake_dll, raising=False)
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    result = pack.eject_device("USB\\VID_1234&PID_5678\\SERIAL")
    assert result["api"] == "CM_Request_Device_EjectW"
    assert result["status"] == "eject_requested"


def test_windows_safe_eject_rejects_device_not_in_allowlist(pack) -> None:
    with pytest.raises(ToolExecutionError, match="allowlist"):
        pack.eject_device("USB\\VID_9999&PID_9999\\UNKNOWN")


def test_generic_window_action_routes_through_sway_proxy(pack, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(pack, "_sway_enabled", lambda: True)
    monkeypatch.setattr(pack, "_sway_window", lambda selector: {
        "title": "Editor", "container_id": 12, "scratchpad": False,
    })
    monkeypatch.setattr(pack, "_sway_request", lambda *args: calls.append(args) or [{"success": True}])
    result = pack.window_action("Editor", "maximize")
    assert result["action"] == "maximize"
    assert calls == [("[con_id=12] fullscreen enable",)]


def test_platform_specific_tools_are_registered_with_control_capabilities(tmp_path: Path) -> None:
    from ultk.builtins.computer_os import create_computer_os_tools

    tools = {
        tool.spec.name: tool
        for tool in create_computer_os_tools(
            filesystem_root=tmp_path / "files",
            state_database=tmp_path / "state.sqlite3",
        )
    }
    assert "computer_os.sway_window_action" in tools
    assert tools["computer_os.sway_window_action"].spec.capabilities == frozenset({"computer:window:control"})
    assert "computer_os.accessibility_click" in tools
    assert tools["computer_os.accessibility_click"].spec.capabilities == frozenset({"computer:accessibility:control"})
    assert "computer_os.eject_usb_device" in tools
    assert tools["computer_os.eject_usb_device"].spec.capabilities == frozenset({"system:devices:eject"})

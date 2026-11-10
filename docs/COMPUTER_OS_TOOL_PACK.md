# Comprehensive Computer and Operating-System Tool Pack

The computer_os pack complements the existing computer, computer_advanced, system, process_management and powershell packs. It provides a single installation surface for desktop context, multi-display/window control, keyboard automation, accessibility, OS services, filesystem permissions, hardware/device inventory and event logs.

## Installation

    from ultk import ToolEngine

    engine = ToolEngine(policy=your_permission_policy)
    engine.install_computer_os_tools(
        filesystem_root=r"C:\ULTK-Managed",
        state_database=r"C:\ULTK-State\computer-os.sqlite3",
        allowed_services=frozenset({"Spooler"}),
        allowed_acl_sids=frozenset({"S-1-5-18"}),
        allow_windows_acl_changes=False,
        allowed_eject_devices=frozenset(),
        allow_posix_chmod=True,
        allow_posix_chown=False,
    )

The filesystem root confines metadata and POSIX permission operations. Service mutation is restricted to exact service names supplied by the host. All operations still require the matching ULTK capability.

## Tool families

| Family | Capabilities |
|---|---|
| Persistent desktop contexts | Create, update, inspect, list and close SQLite-backed logical desktop sessions |
| Displays | Enumerate monitor geometry with screeninfo; primary-display fallback |
| Windows | Enumerate, move, resize, maximize, minimize, restore, activate, close, snap and arrange windows |
| Virtual desktops | Windows current/create/switch through optional pyvda; Linux X11 list/switch through wmctrl; Sway workspace list/current/create/switch through compositor IPC |
| Keyboard | Allowlisted shortcuts and prevalidated bounded key/type/wait sequences |
| Accessibility | Windows UI Automation inspection and click; Linux AT-SPI inspection and exact accessible-name action invocation; macOS Accessibility API inspection and AXPress invocation |
| Services | Read service inventory on Windows/Linux/macOS; allowlisted start/stop/restart on Windows/Linux |
| Filesystem permissions | Metadata, POSIX chmod, optional host-enabled chown; paths confined to filesystem_root |
| Windows ACL | Inspect ACLs and optionally grant R/RX/M to a host-allowlisted numeric SID on one object |
| USB ejection | Allowlisted safe power-off/eject on Linux (udisksctl), macOS (diskutil) and Windows (Configuration Manager CM_Request_Device_EjectW) |
| Hardware | CPU, memory, disks, thermal sensors and battery where supported |
| Devices | USB inventory through pyudev (Linux), pnputil (Windows) or system_profiler (macOS) |
| Networking | Interface addresses, state, MTU and link speed |
| Events | Bounded recent event snapshots and persistent watch definitions |

## Optional dependencies

Install the optional platform extra:

    pip install "universal-llm-toolkit[computer-os]"

It includes PyWinCtl, PyAutoGUI, screeninfo and platform-marked pywinauto, pyvda or pyudev dependencies. Linux AT-SPI also requires the system accessibility stack and its Python bindings. Native commands such as systemctl, wmctrl, journalctl, wevtutil, pnputil and system_profiler are provided by the operating system.

## Session semantics

desktop_session_* creates persistent logical ULTK context records in SQLite. They retain state such as a selected application, active window, monitor arrangement or workflow context. They do not create, log in to, or isolate an operating-system user session. The host application is responsible for associating session IDs with authenticated users.

Event watches are durable watch definitions. They do not start background daemons; the host scheduler must poll the definition and call read_recent_events at its chosen interval.

## Platform coverage and limitations

- Windows: PyWinCtl window operations, pywinauto UI Automation, optional pyvda virtual desktops, Service Control Manager, Event Log, pnputil USB inventory. Use the PowerShell pack for deeper Windows administration.
- Linux X11: PyWinCtl, AT-SPI, systemd/journal, pyudev and wmctrl virtual desktops. Linux Wayland: Sway sessions now have a dedicated compositor-IPC backend for window enumeration, exact-title unique window actions and workspace list/current/create/switch. Global pointer/keyboard input still depends on compositor/portal permissions and is not claimed as universal Wayland support. Other Wayland compositors require their own adapters.
- macOS: PyWinCtl where supported, native Accessibility API inspection and AXPress invocation through PyObjC, launchd service listing, unified log snapshots and system_profiler USB inventory. Native macOS Spaces enumeration/creation/switching is not exposed by this pack; private APIs are intentionally avoided.

## Security boundaries

- Model input is never passed to a shell. Native commands use fixed executable arguments with shell=False; subprocess environment is restricted to required OS, user-session and display-session variables; no model-supplied environment is accepted.
- Window selectors must uniquely identify one window. UIA clicks require an exact automation ID and enabled/visible control.
- Keyboard shortcuts and sequences have key, step, text and delay bounds. Desktop automation can still trigger consequential actions in the foreground application; use narrow capabilities and host approval.
- Service mutations require an exact host-configured allowlist. The host must require approval for stop/restart/start operations.
- Filesystem metadata and permission changes are confined to a host-configured root. Symlinks are rejected for chmod/chown. Path checks do not eliminate filesystem TOCTOU races; this is not an OS sandbox.
- POSIX ownership changes are disabled by default. Windows ACL grants are disabled by default, require host opt-in and an exact SID allowlist, and are limited to R/RX/M on a single object. Windows ACL inheritance and recursive grants are not changed.
- Hardware inventory may reveal device identifiers. USB serial numbers are returned only by the Linux pyudev backend; restrict access appropriately. Safe eject requires an exact host allowlist of platform-specific device identifiers. Windows Configuration Manager may refuse ejection when a device is busy or another driver vetoes it; ULTK reports the veto and does not force removal. Eject can interrupt I/O and must require human approval.
- Event log access may require elevated privileges and can expose sensitive operational data. Output and event counts are bounded.
- The pack does not elevate privileges and cannot bypass OS permissions.

## Not implemented in this increment

Native macOS Spaces management, Wayland support outside the Sway compositor adapter, Windows recursive/inherited ACL and ownership changes, USB driver installation/configuration, service creation/deletion, user/account administration, background event-monitor daemons, isolated OS desktop sessions and remote OS management remain outside this pack.


## Multi-monitor GUI workflows

The computer_os pack exposes monitor discovery, window enumeration, window actions,
monitor-relative snapping and batch window arrangement. Coordinates returned by monitor
enumeration use the desktop's virtual-screen coordinate space; monitor-relative placement
is translated to the selected monitor's physical origin, including monitors positioned left
of or above the primary display.

The computer_os.desktop_workflow tool accepts up to 50 prevalidated steps: pointer move/click,
text entry, allowlisted key presses and shortcuts, bounded waits, window actions, monitor
snapping and screenshots. The workflow validates the complete sequence before dispatching
input so an invalid later step does not leave a partially executed sequence. It is bounded
but not transactional: an OS/window-manager failure during execution can still leave earlier
steps applied. Consequential desktop actions should require application-level approval.

The existing computer.mouse, computer.keyboard and computer.desktop_workflow tools remain
available for backward compatibility. The new computer_os workflow is the monitor-aware
composition surface.

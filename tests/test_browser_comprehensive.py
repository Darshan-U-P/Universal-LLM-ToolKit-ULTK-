from __future__ import annotations

from ultk.builtins.browser_comprehensive import BrowserControlPlane, create_comprehensive_browser_tools


def test_profile_lifecycle_and_profile_state_is_separate(tmp_path):
    browser = BrowserControlPlane(tmp_path)
    assert browser.create_profile("work")["created"] is True
    assert browser.create_profile("personal")["created"] is True
    names = {item["name"] for item in browser.list_profiles()["profiles"]}
    assert names == {"work", "personal"}
    assert browser.delete_profile("work")["deleted"] is True
    assert {item["name"] for item in browser.list_profiles()["profiles"]} == {"personal"}


def test_profile_name_validation_rejects_path_components(tmp_path):
    browser = BrowserControlPlane(tmp_path)
    try:
        browser.create_profile("../outside")
    except Exception as exc:
        assert "safe ASCII" in str(exc)
    else:
        raise AssertionError("path-like profile name was accepted")


def test_comprehensive_browser_tools_have_unique_names_and_submission_capability(tmp_path):
    tools = create_comprehensive_browser_tools(profile_root=tmp_path)
    names = [tool.spec.name for tool in tools]
    assert len(names) == len(set(names))
    assert {
        "browser.profile_create", "browser.navigate", "browser.snapshot", "browser.tabs", "browser.popup_capture",
        "browser.frame_interact", "browser.cookies", "browser.scrape_structured",
        "browser.network_inspect", "browser.websocket_probe", "browser.test_run",
        "browser.challenge_detect", "browser.auth_status", "browser.auth_handoff", "browser.form_preview",
        "browser.form_submit", "web.change_monitor_add", "web.change_monitor_check",
        "browser.extensions_list",
    }.issubset(set(names))
    submit = next(tool for tool in tools if tool.spec.name == "browser.form_submit")
    assert submit.spec.capabilities == frozenset({"browser:submit:consequential"})


def test_browser_extension_paths_are_host_configured(tmp_path):
    extension = tmp_path / "trusted-extension"
    extension.mkdir()
    (extension / "manifest.json").write_text('{"manifest_version":3,"name":"test","version":"1.0"}')
    browser = BrowserControlPlane(tmp_path / "profiles", headless=False,
                                  extension_dirs=(extension,))
    assert browser.list_extensions()["extensions"][0]["manifest_present"] is True

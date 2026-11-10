"""Semantic, accessibility-oriented browser inspection and interaction tools.

This pack complements the selector-based browser tools with exact, bounded locators.
It never evaluates model-supplied JavaScript or accepts arbitrary CSS selectors.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ultk.builtins._common import FunctionTool, object_schema
from ultk.builtins.browser_automation import _with_page
from ultk.exceptions import ToolExecutionError

_STRATEGIES = {"role", "label", "text", "placeholder", "alt", "test_id"}
_ROLES = {
    "alert", "button", "checkbox", "combobox", "dialog", "heading", "link",
    "listbox", "menuitem", "option", "radio", "searchbox", "slider", "spinbutton",
    "switch", "tab", "textbox",
}
_ACTIONS = {"click", "fill", "type", "press", "check", "uncheck", "select", "hover"}
_KEYS = {
    "Enter", "Tab", "Escape", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight",
    "Backspace", "Delete", "Home", "End", "PageUp", "PageDown",
}


def _locator(page: Any, strategy: str, target: str, role: str | None = None):
    if strategy == "role":
        if role not in _ROLES:
            raise ToolExecutionError("A supported accessible role is required for role matching.")
        return page.get_by_role(role, name=target, exact=True)
    if strategy == "label":
        return page.get_by_label(target, exact=True)
    if strategy == "text":
        return page.get_by_text(target, exact=True)
    if strategy == "placeholder":
        return page.get_by_placeholder(target, exact=True)
    if strategy == "alt":
        return page.get_by_alt_text(target, exact=True)
    if strategy == "test_id":
        return page.get_by_test_id(target)
    raise ToolExecutionError("Unsupported browser locator strategy.")


def _validate_target(strategy: str, target: str, role: str | None = None) -> None:
    if strategy not in _STRATEGIES:
        raise ToolExecutionError("Unsupported browser locator strategy.")
    if not isinstance(target, str) or not target.strip() or len(target) > 300:
        raise ToolExecutionError("A non-empty browser target of at most 300 characters is required.")
    if strategy == "role" and role not in _ROLES:
        raise ToolExecutionError("A supported accessible role is required for role matching.")
    if strategy != "role" and role is not None:
        raise ToolExecutionError("The role field is only valid with the role locator strategy.")


def _inspect(root: str, session_id: str, max_items: int) -> dict[str, Any]:
    if not 1 <= max_items <= 100:
        raise ToolExecutionError("max_items must be between 1 and 100.")

    script = """elements => elements.filter(el => {
      const rect = el.getBoundingClientRect();
      const style = window.getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden'
        && style.display !== 'none' && !el.closest('[aria-hidden="true"]');
    }).slice(0, limit).map((el, index) => {
      const labels = el.labels ? Array.from(el.labels).map(x => x.innerText.trim()).filter(Boolean) : [];
      const name = el.getAttribute('aria-label') || labels.join(' ')
        || el.getAttribute('placeholder') || el.getAttribute('title')
        || el.innerText || el.value || el.getAttribute('alt') || '';
      const tag = el.tagName.toLowerCase();
      const implicit = tag === 'button' ? 'button' : tag === 'a' ? 'link'
        : tag === 'textarea' ? 'textbox' : tag === 'select' ? 'combobox'
        : tag === 'input' ? (el.type === 'checkbox' ? 'checkbox'
          : el.type === 'radio' ? 'radio' : el.type === 'submit' ? 'button' : 'textbox') : '';
      return {index, tag, role: el.getAttribute('role') || implicit,
        name: String(name).trim().slice(0, 300),
        type: el.getAttribute('type') || null,
        href: el.href || null, placeholder: el.getAttribute('placeholder'),
        disabled: Boolean(el.disabled), checked: Boolean(el.checked),
        required: Boolean(el.required)};
    })"""
    def run(page):
        controls = page.locator(
            "button, a[href], input:not([type=hidden]), textarea, select, "
            "[role=button], [role=link], [role=checkbox], [role=radio], [role=tab], "
            "[contenteditable=true]"
        ).evaluate_all(script.replace("limit", str(max_items)))
        return {
            "url": page.url,
            "title": page.title(),
            "text": page.locator("body").inner_text(timeout=5000)[:12000],
            "controls": controls,
            "controls_truncated": len(controls) >= max_items,
        }
    return _with_page(root, session_id, run)


def _act(
    root: str,
    session_id: str,
    strategy: str,
    target: str,
    action: str,
    role: str | None = None,
    value: str | None = None,
    key: str | None = None,
) -> dict[str, Any]:
    _validate_target(strategy, target, role)
    if action not in _ACTIONS:
        raise ToolExecutionError("Unsupported semantic browser action.")
    if action in {"fill", "type"} and (value is None or len(value) > 10000):
        raise ToolExecutionError("fill/type requires a value of at most 10000 characters.")
    if action == "press" and key not in _KEYS:
        raise ToolExecutionError("Browser key is not allowlisted.")
    if action != "press" and key is not None:
        raise ToolExecutionError("key is only valid for the press action.")
    if action not in {"fill", "type"} and value is not None:
        raise ToolExecutionError("value is only valid for fill and type actions.")
    if action == "select" and (not value or len(value) > 500):
        raise ToolExecutionError("select requires an option label/value up to 500 characters.")
    if action != "select" and action not in {"fill", "type"} and value is not None:
        raise ToolExecutionError("value is not valid for this action.")

    def run(page):
        locator = _locator(page, strategy, target, role)
        count = locator.count()
        if count != 1:
            raise ToolExecutionError(
                f"Browser target must resolve to exactly one element; found {count}."
            )
        if action == "click":
            locator.click(timeout=10000)
        elif action == "fill":
            locator.fill(value, timeout=10000)
        elif action == "type":
            locator.press_sequentially(value, timeout=10000)
        elif action == "press":
            locator.press(key, timeout=10000)
        elif action == "check":
            locator.check(timeout=10000)
        elif action == "uncheck":
            locator.uncheck(timeout=10000)
        elif action == "select":
            locator.select_option(label=value, timeout=10000)
        elif action == "hover":
            locator.hover(timeout=10000)
        return {
            "action": action, "strategy": strategy, "target": target,
            "url": page.url,
        }
    return _with_page(root, session_id, run)


def _wait_for(
    root: str, session_id: str, strategy: str, target: str,
    state: str, timeout_ms: int, role: str | None = None,
) -> dict[str, Any]:
    _validate_target(strategy, target, role)
    if state not in {"visible", "hidden", "attached", "detached"}:
        raise ToolExecutionError("Unsupported browser wait state.")
    if not 100 <= timeout_ms <= 10000:
        raise ToolExecutionError("Browser wait timeout must be between 100 and 10000 ms.")

    def run(page):
        locator = _locator(page, strategy, target, role)
        locator.wait_for(state=state, timeout=timeout_ms)
        count = locator.count()
        if state in {"visible", "attached"} and count != 1:
            raise ToolExecutionError(
                f"Browser target must resolve to exactly one element; found {count}."
            )
        return {"state": state, "strategy": strategy, "target": target,
                "matches": count, "url": page.url}
    return _with_page(root, session_id, run)


def create_semantic_browser_tools(
    *, session_root: str | Path = "./browser_sessions",
) -> tuple[FunctionTool, ...]:
    """Create bounded accessible-name browser inspection and interaction tools."""
    root = str(Path(session_root).expanduser().resolve())
    session = {"type": "string", "minLength": 1, "maxLength": 100}
    strategy = {"type": "string", "enum": sorted(_STRATEGIES)}
    target = {"type": "string", "minLength": 1, "maxLength": 300}
    role = {"type": "string", "enum": sorted(_ROLES)}
    return (
        FunctionTool(
            "browser.inspect_interactive",
            "Inspect visible page text and a bounded list of interactive controls with accessible names.",
            object_schema({"session_id": session, "max_items": {
                "type": "integer", "minimum": 1, "maximum": 100}},
                ["session_id"]),
            "browser:read",
            lambda session_id, max_items=60: _inspect(root, session_id, max_items),
            timeout=25,
        ),
        FunctionTool(
            "browser.semantic_act",
            "Interact with exactly one accessible browser element using role, label, text, placeholder, alt text or test id.",
            object_schema({
                "session_id": session, "strategy": strategy, "target": target,
                "action": {"type": "string", "enum": sorted(_ACTIONS)},
                "role": role, "value": {"type": "string", "maxLength": 10000},
                "key": {"type": "string", "maxLength": 20},
            }, ["session_id", "strategy", "target", "action"]),
            "browser:interact",
            lambda session_id, strategy, target, action, role=None, value=None, key=None:
                _act(root, session_id, strategy, target, action, role, value, key),
            timeout=30,
        ),
        FunctionTool(
            "browser.wait_for_target",
            "Wait for one semantic browser target to reach a bounded visibility/attachment state.",
            object_schema({
                "session_id": session, "strategy": strategy, "target": target,
                "state": {"type": "string", "enum": ["visible", "hidden", "attached", "detached"]},
                "timeout_ms": {"type": "integer", "minimum": 100, "maximum": 10000},
                "role": role,
            }, ["session_id", "strategy", "target", "state", "timeout_ms"]),
            "browser:read",
            lambda session_id, strategy, target, state, timeout_ms, role=None:
                _wait_for(root, session_id, strategy, target, state, timeout_ms, role),
            timeout=15,
        ),
    )

from __future__ import annotations

import pytest

from ultk.builtins.integrations import (
    _allowed_redirect,
    _build_url,
    _validate_endpoint,
    create_rest_tools,
)
from ultk.engine import ToolEngine
from ultk.permissions import AllowListPolicy


def endpoint_config() -> dict:
    return {
        "base_url": "https://api.example.com/v1",
        "allowed_path_prefixes": ["users", "posts"],
        "write_methods": ["POST", "PATCH"],
        "token_env": "ULTK_TEST_API_TOKEN",
    }


def test_rest_endpoint_builds_only_allowlisted_paths() -> None:
    endpoint = _validate_endpoint("service", endpoint_config())
    url = _build_url(endpoint, "users/42", {"active": True, "tag": ["a", "b"]})
    assert url.startswith("https://api.example.com/v1/users/42?")
    with pytest.raises(Exception, match="path"):
        _build_url(endpoint, "admin/users", None)
    with pytest.raises(Exception, match="traversal"):
        _build_url(endpoint, "users/../admin", None)
    with pytest.raises(Exception, match="URL"):
        _build_url(endpoint, "https://attacker.example/path", None)


def test_rest_redirects_must_remain_on_same_host_and_path_scope() -> None:
    endpoint = _validate_endpoint("service", endpoint_config())
    assert _allowed_redirect(endpoint, "https://api.example.com/v1/users/43")
    assert not _allowed_redirect(endpoint, "https://attacker.example/v1/users/43")
    assert not _allowed_redirect(endpoint, "https://api.example.com/v1/admin")


def test_rest_tools_expose_mutations_only_when_host_enables_them() -> None:
    read_tools = create_rest_tools({"service": endpoint_config()}, allow_writes=False)
    assert {tool.spec.name for tool in read_tools} == {"integrations.service_get"}

    write_tools = create_rest_tools({"service": endpoint_config()}, allow_writes=True)
    assert {tool.spec.name for tool in write_tools} == {
        "integrations.service_get",
        "integrations.service_mutate",
    }
    mutation = next(tool for tool in write_tools if tool.spec.name.endswith("_mutate"))
    assert mutation.spec.input_schema["properties"]["method"]["enum"] == ["PATCH", "POST"]
    assert "headers" not in mutation.spec.input_schema["properties"]


def test_engine_registers_only_host_configured_integrations() -> None:
    engine = ToolEngine(policy=AllowListPolicy({"integrations.service_get"}))
    engine.install_rest_tools({"service": endpoint_config()})
    assert [tool.spec.name for tool in engine.registry.list()] == ["integrations.service_get"]

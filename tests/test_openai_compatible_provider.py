from __future__ import annotations

import json
import urllib.request

import pytest

from ultk.exceptions import ConfigurationError
from ultk.models import AssistantTurn
from ultk.providers.openai_compatible import OpenAICompatibleProvider


def test_provider_parses_tool_calls_into_provider_neutral_contract() -> None:
    turn = OpenAICompatibleProvider._parse_completion({
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "I will check.",
                "tool_calls": [{
                    "id": "call-123",
                    "type": "function",
                    "function": {"name": "system.get_platform_info", "arguments": "{}"},
                }],
            }
        }]
    })
    assert isinstance(turn, AssistantTurn)
    assert turn.content == "I will check."
    assert turn.tool_calls[0].id == "call-123"
    assert turn.tool_calls[0].arguments == {}


def test_provider_rejects_malformed_tool_arguments() -> None:
    with pytest.raises(ConfigurationError, match="malformed"):
        OpenAICompatibleProvider._parse_completion({
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "function": {"name": "test.tool", "arguments": "{bad json"},
                    }],
                }
            }]
        })


def test_provider_accepts_only_https_or_explicit_loopback_http() -> None:
    local = OpenAICompatibleProvider(
        base_url="http://127.0.0.1:11434/v1",
        model="local-model",
    )
    assert local.endpoint == "http://127.0.0.1:11434/v1/chat/completions"
    with pytest.raises(ConfigurationError, match="HTTPS"):
        OpenAICompatibleProvider(
            base_url="http://api.example.com/v1",
            model="remote-model",
        )


def test_provider_sanitizes_messages_and_keeps_host_credentials(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self, limit):
            return json.dumps({
                "choices": [{"message": {"role": "assistant", "content": "ready"}}]
            }).encode("utf-8")

    class FakeOpener:
        request = None

        def open(self, request, timeout):
            self.request = request
            return FakeResponse()

    opener = FakeOpener()
    monkeypatch.setattr(
        urllib.request, "build_opener", lambda *handlers: opener
    )
    monkeypatch.setenv("ULTK_TEST_PROVIDER_KEY", "host-secret")
    provider = OpenAICompatibleProvider(
        base_url="https://provider.example/v1",
        model="test-model",
        api_key_env="ULTK_TEST_PROVIDER_KEY",
    )
    turn = provider._complete_sync(
        [{"role": "tool", "name": "test.tool", "tool_call_id": "id",
          "content": "result", "is_error": True}],
        [],
    )
    assert turn.content == "ready"
    assert opener.request.get_header("Authorization") == "Bearer host-secret"
    request_body = json.loads(opener.request.data)
    assert "is_error" not in request_body["messages"][0]
    assert request_body["model"] == "test-model"

"""OpenAI-compatible chat-completions adapter for hosted and local endpoints."""

from __future__ import annotations

import asyncio
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from ultk.exceptions import ConfigurationError
from ultk.models import AssistantTurn, ToolCallRequest


class _SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, origin: tuple[str, str, int]) -> None:
        super().__init__()
        self.origin = origin

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        origin = (
            parsed.scheme,
            parsed.hostname or "",
            parsed.port or (443 if parsed.scheme == "https" else 80),
        )
        if origin != self.origin:
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class OpenAICompatibleProvider:
    """Provider adapter for OpenAI-compatible /chat/completions APIs.

    The endpoint, model and credential environment variable are host configuration.
    The model never receives control over the API host or authorization headers.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key_env: str | None = None,
        timeout_seconds: int = 60,
        max_response_bytes: int = 5_000_000,
        max_request_bytes: int = 2_000_000,
        temperature: float | None = None,
        max_tokens: int | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> None:
        parsed = urllib.parse.urlsplit(base_url)
        is_loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if (
            parsed.scheme != "https" and not (parsed.scheme == "http" and is_loopback)
        ) or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ConfigurationError(
                "Provider base URL must be HTTPS, or HTTP on an explicit loopback host."
            )
        if not model or len(model) > 200:
            raise ConfigurationError("A model name of at most 200 characters is required.")
        if api_key_env is not None and not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*", api_key_env
        ):
            raise ConfigurationError("api_key_env must be a valid environment variable name.")
        if not 1 <= timeout_seconds <= 180:
            raise ConfigurationError("timeout_seconds must be between 1 and 180.")
        if not 1 <= max_response_bytes <= 20_000_000:
            raise ConfigurationError("max_response_bytes must be between 1 byte and 20 MB.")
        if not 1 <= max_request_bytes <= 10_000_000:
            raise ConfigurationError("max_request_bytes must be between 1 byte and 10 MB.")
        if temperature is not None and not 0 <= temperature <= 2:
            raise ConfigurationError("temperature must be between 0 and 2.")
        if max_tokens is not None and max_tokens < 1:
            raise ConfigurationError("max_tokens must be positive.")
        fixed_headers = dict(extra_headers or {})
        if any(
            not isinstance(key, str)
            or not isinstance(value, str)
            or key.casefold() in {"host", "content-length", "cookie", "authorization"}
            or "\r" in key or "\n" in key or "\r" in value or "\n" in value
            for key, value in fixed_headers.items()
        ):
            raise ConfigurationError("extra_headers contains an unsafe or invalid header.")
        self.base_url = base_url.rstrip("/") + "/"
        self.endpoint = urllib.parse.urljoin(self.base_url, "chat/completions")
        self.origin = (
            parsed.scheme,
            parsed.hostname.casefold(),
            parsed.port or (443 if parsed.scheme == "https" else 80),
        )
        self.model = model
        self.api_key_env = api_key_env
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self.max_request_bytes = max_request_bytes
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.extra_headers = fixed_headers

    @staticmethod
    def _normalize_messages(
        messages: Sequence[Mapping[str, object]],
    ) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        allowed = {"role", "content", "name", "tool_calls", "tool_call_id"}
        for message in messages:
            role = message.get("role")
            if role not in {"system", "user", "assistant", "tool"}:
                raise ConfigurationError("Conversation contains an unsupported message role.")
            normalized.append({
                key: value for key, value in message.items()
                if key in allowed and value is not None
            })
        return normalized

    @staticmethod
    def _parse_completion(payload: Mapping[str, Any]) -> AssistantTurn:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ConfigurationError("Provider response did not contain any choices.")
        message = choices[0].get("message") if isinstance(choices[0], Mapping) else None
        if not isinstance(message, Mapping):
            raise ConfigurationError("Provider response did not contain an assistant message.")
        content = message.get("content")
        if content is not None and not isinstance(content, str):
            if isinstance(content, list):
                content = "".join(
                    part.get("text", "") for part in content
                    if isinstance(part, Mapping) and isinstance(part.get("text", ""), str)
                )
            else:
                raise ConfigurationError("Provider returned an unsupported content type.")
        tool_calls: list[ToolCallRequest] = []
        raw_calls = message.get("tool_calls") or []
        if not isinstance(raw_calls, list) or len(raw_calls) > 32:
            raise ConfigurationError(
                "Provider returned an invalid or oversized tool_calls collection."
            )
        for raw_call in raw_calls:
            if not isinstance(raw_call, Mapping):
                raise ConfigurationError("Provider returned an invalid tool call.")
            function = raw_call.get("function")
            if not isinstance(function, Mapping):
                raise ConfigurationError("Provider tool call is missing its function payload.")
            name = function.get("name")
            raw_arguments = function.get("arguments", "{}")
            if not isinstance(name, str) or not name:
                raise ConfigurationError("Provider tool call is missing a function name.")
            if isinstance(raw_arguments, str):
                try:
                    arguments = json.loads(raw_arguments)
                except json.JSONDecodeError as exc:
                    raise ConfigurationError("Provider returned malformed tool arguments.") from exc
            else:
                arguments = raw_arguments
            if not isinstance(arguments, dict):
                raise ConfigurationError("Provider tool arguments must be a JSON object.")
            call_id = raw_call.get("id")
            tool_calls.append(ToolCallRequest(
                str(call_id) if call_id else uuid.uuid4().hex,
                name,
                arguments,
            ))
        return AssistantTurn(content=content, tool_calls=tuple(tool_calls))

    def _complete_sync(
        self,
        messages: Sequence[Mapping[str, object]],
        tools: Sequence[Mapping[str, object]],
    ) -> AssistantTurn:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._normalize_messages(messages),
        }
        if tools:
            payload["tools"] = list(tools)
            payload["tool_choice"] = "auto"
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens
        try:
            request_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ConfigurationError("Conversation or tool schema is not JSON serializable.") from exc
        if len(request_data) > self.max_request_bytes:
            raise ConfigurationError("Provider request exceeds the configured size limit.")
        headers = {"Content-Type": "application/json", "Accept": "application/json",
                   **self.extra_headers}
        if self.api_key_env:
            api_key = os.environ.get(self.api_key_env)
            if not api_key:
                raise ConfigurationError("Provider API key environment variable is not set.")
            headers["Authorization"] = f"Bearer {api_key}"
        request = urllib.request.Request(
            self.endpoint, data=request_data, headers=headers, method="POST"
        )
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _SameOriginRedirect(self.origin)
        )
        try:
            with opener.open(request, timeout=self.timeout_seconds) as response:
                response_data = response.read(self.max_response_bytes + 1)
        except urllib.error.HTTPError as exc:
            raise ConfigurationError(f"Provider returned HTTP {exc.code}.") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ConfigurationError(
                f"Provider request failed ({type(exc).__name__})."
            ) from exc
        if len(response_data) > self.max_response_bytes:
            raise ConfigurationError("Provider response exceeds the configured size limit.")
        try:
            response_payload = json.loads(response_data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConfigurationError("Provider response was not valid UTF-8 JSON.") from exc
        if not isinstance(response_payload, Mapping):
            raise ConfigurationError("Provider response must be a JSON object.")
        return self._parse_completion(response_payload)

    async def complete(
        self,
        messages: Sequence[Mapping[str, object]],
        tools: Sequence[Mapping[str, object]],
    ) -> AssistantTurn:
        return await asyncio.wait_for(
            asyncio.to_thread(self._complete_sync, messages, tools),
            timeout=self.timeout_seconds + 2,
        )

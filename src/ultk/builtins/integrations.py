"""Host-configured REST/webhook integrations with no model-controlled credentials."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any

from ultk.builtins._common import FunctionTool, object_schema
from ultk.exceptions import ToolExecutionError


_ALIAS = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
_SAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _validate_endpoint(alias: str, config: Mapping[str, Any]) -> dict[str, Any]:
    if not _ALIAS.fullmatch(alias):
        raise ValueError(f"Invalid integration endpoint alias: {alias}")
    base_url = str(config.get("base_url", ""))
    parsed = urllib.parse.urlsplit(base_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"Endpoint '{alias}' must use a credential-free HTTPS base URL.")
    prefixes = tuple(config.get("allowed_path_prefixes", ("",)))
    if not prefixes or any(
        not isinstance(prefix, str)
        or prefix.startswith("/")
        or ".." in prefix.split("/")
        for prefix in prefixes
    ):
        raise ValueError(f"Endpoint '{alias}' has invalid path prefixes.")
    methods = frozenset(str(method).upper() for method in config.get("write_methods", ()))
    if not methods.issubset(_SAFE_METHODS):
        raise ValueError(f"Endpoint '{alias}' has unsupported write methods.")
    token_env = config.get("token_env")
    if token_env is not None and (
        not isinstance(token_env, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token_env)
    ):
        raise ValueError(f"Endpoint '{alias}' has an invalid token environment variable name.")
    headers = config.get("headers", {})
    if not isinstance(headers, Mapping) or any(
        not isinstance(key, str) or not isinstance(value, str)
        or key.casefold() in {"host", "content-length", "cookie", "authorization"}
        for key, value in headers.items()
    ):
        raise ValueError(f"Endpoint '{alias}' has invalid fixed headers.")
    return {
        "base_url": base_url.rstrip("/") + "/",
        "hostname": parsed.hostname.casefold(),
        "port": parsed.port or 443,
        "prefixes": prefixes,
        "base_path": parsed.path.rstrip("/"),
        "write_methods": methods,
        "token_env": token_env,
        "token_header": str(config.get("token_header", "Authorization")),
        "token_prefix": str(config.get("token_prefix", "Bearer ")),
        "headers": dict(headers),
    }


def _build_url(endpoint: Mapping[str, Any], path: str,
               query: Mapping[str, Any] | None) -> str:
    if not isinstance(path, str) or not path or len(path) > 1000:
        raise ToolExecutionError("A relative API path of at most 1000 characters is required.")
    parsed_path = urllib.parse.urlsplit(path)
    decoded_path = urllib.parse.unquote(parsed_path.path)
    segments = decoded_path.replace("\\", "/").split("/")
    if parsed_path.scheme or parsed_path.netloc or parsed_path.query or parsed_path.fragment:
        raise ToolExecutionError("API path must not contain a URL, query or fragment.")
    if any(segment in {".", ".."} for segment in segments):
        raise ToolExecutionError("API path traversal is not allowed.")
    relative = decoded_path.lstrip("/")
    if not any(
        not prefix
        or relative == prefix.rstrip("/")
        or relative.startswith(prefix.rstrip("/") + "/")
        for prefix in endpoint["prefixes"]
    ):
        raise ToolExecutionError("API path is outside the configured path prefixes.")
    url = urllib.parse.urljoin(str(endpoint["base_url"]), urllib.parse.quote(relative, safe="/:@-._~"))
    parsed = urllib.parse.urlsplit(url)
    if parsed.hostname is None or parsed.hostname.casefold() != endpoint["hostname"]:
        raise ToolExecutionError("Resolved API URL does not match the configured host.")
    if query:
        flattened: list[tuple[str, str]] = []
        for key, value in query.items():
            if not isinstance(key, str) or len(key) > 200:
                raise ToolExecutionError("Query parameter names must be bounded strings.")
            values = value if isinstance(value, list) else [value]
            if len(values) > 100 or any(
                not isinstance(item, (str, int, float, bool)) for item in values
            ):
                raise ToolExecutionError("Query values must be bounded scalar values.")
            flattened.extend((key, str(item)) for item in values)
        url += ("&" if parsed.query else "?") + urllib.parse.urlencode(flattened)
    return url


def _allowed_redirect(endpoint: Mapping[str, Any], url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.hostname.casefold() != endpoint["hostname"]
        or (parsed.port or 443) != endpoint["port"]
        or parsed.username is not None
        or parsed.password is not None
    ):
        return False
    path = urllib.parse.unquote(parsed.path)
    base_path = str(endpoint["base_path"])
    if base_path and not (path == base_path or path.startswith(base_path + "/")):
        return False
    relative_path = path[len(base_path):].lstrip("/")
    return any(
        not prefix
        or relative_path == prefix.rstrip("/")
        or relative_path.startswith(prefix.rstrip("/") + "/")
        for prefix in endpoint["prefixes"]
    )


class _SameEndpointRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, endpoint: Mapping[str, Any]) -> None:
        super().__init__()
        self.endpoint = endpoint

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _allowed_redirect(self.endpoint, newurl):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _request(endpoint: Mapping[str, Any], method: str, path: str,
             query: Mapping[str, Any] | None, body: Any,
             max_response_bytes: int, timeout_seconds: int) -> dict[str, Any]:
    url = _build_url(endpoint, path, query)
    headers = {"Accept": "application/json", **endpoint["headers"]}
    token_env = endpoint["token_env"]
    if token_env:
        token = os.environ.get(str(token_env))
        if not token:
            raise ToolExecutionError("A required host-configured API credential is unavailable.")
        headers[str(endpoint["token_header"])] = str(endpoint["token_prefix"]) + token
    data = None
    if body is not None:
        try:
            data = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ToolExecutionError("Request body must be JSON serializable.") from exc
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _SameEndpointRedirect(endpoint)
    )
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            final_url = response.geturl()
            if not _allowed_redirect(endpoint, final_url):
                raise ToolExecutionError("API response URL left the configured endpoint.")
            payload = response.read(max_response_bytes + 1)
            status = response.status
            content_type = response.headers.get("Content-Type", "")
            response_headers = {
                key: response.headers.get(key)
                for key in ("Content-Type", "ETag", "Last-Modified", "Retry-After")
                if response.headers.get(key) is not None
            }
    except urllib.error.HTTPError as exc:
        payload = exc.read(max_response_bytes + 1)
        if len(payload) > max_response_bytes:
            raise ToolExecutionError("API error response exceeds the configured size limit.") from exc
        raise ToolExecutionError(f"API endpoint returned HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ToolExecutionError(f"API request failed ({type(exc).__name__}).") from exc
    if len(payload) > max_response_bytes:
        raise ToolExecutionError("API response exceeds the configured size limit.")
    text = payload.decode("utf-8", errors="replace")
    if "json" in content_type.casefold():
        try:
            result: Any = json.loads(text) if text else None
        except json.JSONDecodeError:
            result = text
    else:
        result = text
    return {
        "status": status,
        "url": final_url,
        "content_type": content_type,
        "headers": response_headers,
        "body": result,
        "bytes_received": len(payload),
    }


def create_rest_tools(
    endpoints: Mapping[str, Mapping[str, Any]],
    *,
    allow_writes: bool = False,
    max_response_bytes: int = 1_000_000,
    timeout_seconds: int = 20,
) -> tuple[FunctionTool, ...]:
    if not endpoints:
        return ()
    if not 1 <= max_response_bytes <= 10_000_000:
        raise ValueError("max_response_bytes must be between 1 byte and 10 MB.")
    if not 1 <= timeout_seconds <= 60:
        raise ValueError("timeout_seconds must be between 1 and 60.")
    tools: list[FunctionTool] = []
    common_properties = {
        "path": {"type": "string", "minLength": 1, "maxLength": 1000},
        "query": {"type": "object"},
    }
    for alias, raw_config in endpoints.items():
        endpoint = _validate_endpoint(alias, raw_config)
        tools.append(FunctionTool(
            f"integrations.{alias}_get",
            f"Send an allowlisted GET request to the host-configured '{alias}' API endpoint.",
            object_schema(common_properties, ["path"]),
            "integration:http:read",
            lambda path, query=None, config=endpoint: _request(
                config, "GET", path, query, None, max_response_bytes, timeout_seconds
            ),
            timeout=timeout_seconds + 2,
            output_limit=min(max_response_bytes + 2000, 1_000_000),
        ))
        if allow_writes and endpoint["write_methods"]:
            tools.append(FunctionTool(
                f"integrations.{alias}_mutate",
                f"Send a configured mutation request to the host-configured '{alias}' API endpoint.",
                object_schema({
                    **common_properties,
                    "method": {"type": "string", "enum": sorted(endpoint["write_methods"])},
                    "body": {},
                }, ["path", "method"]),
                "integration:http:write",
                lambda path, method, query=None, body=None, config=endpoint: _request(
                    config, method, path, query, body,
                    max_response_bytes, timeout_seconds
                ),
                timeout=timeout_seconds + 2,
                output_limit=min(max_response_bytes + 2000, 1_000_000),
            ))
    return tuple(tools)

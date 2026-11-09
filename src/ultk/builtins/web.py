"""Bounded web retrieval, page analysis and browser automation tools."""
from __future__ import annotations

import hashlib
import ipaddress
import os
import socket
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from ultk.builtins._common import FunctionTool, object_schema
from ultk.exceptions import ToolExecutionError


def _validate_public_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ToolExecutionError("Only credential-free HTTP(S) URLs are accepted.")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
        for item in addresses:
            address = ipaddress.ip_address(item[4][0])
            if not address.is_global:
                raise ToolExecutionError("Requests to private, loopback, link-local or reserved IPs are blocked.")
    except socket.gaierror as exc:
        raise ToolExecutionError("Hostname could not be resolved.") from exc
    return url


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _request(url: str, max_bytes: int = 2_000_000) -> tuple[str, bytes, str]:
    current = _validate_public_url(url)
    opener = urllib.request.build_opener(_SafeRedirect())
    request = urllib.request.Request(current, headers={"User-Agent": "ULTK/0.1 (+https://github.com/Darshan-U-P/Universal-LLM-ToolKit-ULTK-)"})
    try:
        with opener.open(request, timeout=12) as response:
            final_url = _validate_public_url(response.geturl())
            data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise ToolExecutionError("Response exceeds configured byte limit.")
            return final_url, data, response.headers.get_content_type()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ToolExecutionError(f"HTTP request failed ({type(exc).__name__}).") from exc


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self.title = ""
        self._in_title = False
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "a" and values.get("href"):
            self.links.append({"text": "", "href": values["href"][:1000]})
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"} and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._skip:
            return
        text = " ".join(data.split())
        if not text:
            return
        self.parts.append(text)
        if self._in_title:
            self.title += text + " "
        if self.links and not self.links[-1].get("text"):
            self.links[-1]["text"] = text[:180]


def _fetch_url(url: str, max_bytes: int = 1_000_000) -> dict[str, Any]:
    final_url, data, content_type = _request(url, max_bytes)
    if content_type not in {"text/html", "text/plain", "application/json", "application/xml"}:
        raise ToolExecutionError(f"Unsupported text content type: {content_type}")
    return {"url": final_url, "content_type": content_type,
            "body": data.decode("utf-8", errors="replace")[:30000],
            "bytes_read": len(data)}


def _extract(url: str, max_bytes: int = 1_000_000) -> dict[str, Any]:
    final_url, data, content_type = _request(url, max_bytes)
    if content_type != "text/html":
        raise ToolExecutionError("Page extraction requires text/html.")
    parser = _TextParser()
    parser.feed(data.decode("utf-8", errors="replace"))
    text = " ".join(" ".join(parser.parts).split())
    return {"url": final_url, "title": parser.title.strip(),
            "text": text[:25000], "links": parser.links[:100]}


def _search(query: str, limit: int = 5) -> dict[str, Any]:
    if not query.strip() or len(query) > 300 or not 1 <= limit <= 10:
        raise ToolExecutionError("Search query or result limit is invalid.")
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    _, data, _ = _request(url, 1_000_000)
    parser = _TextParser()
    parser.feed(data.decode("utf-8", errors="replace"))
    # Search result markup is intentionally parsed conservatively; return links only.
    results = []
    for link in parser.links:
        href = urllib.parse.urljoin("https://duckduckgo.com", link["href"])
        if href.startswith("https://") and link["text"]:
            results.append({"title": link["text"], "url": href})
        if len(results) >= limit:
            break
    return {"query": query, "results": results}


def _download(url: str, filename: str, download_root: str, max_bytes: int = 5_000_000,
              expected_sha256: str | None = None) -> dict[str, Any]:
    root = Path(download_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if not filename or filename in {".", ".."} or "/" in filename or "\\" in filename:
        raise ToolExecutionError("filename must be a simple file name.")
    target = (root / filename).resolve()
    if not target.is_relative_to(root):
        raise ToolExecutionError("Download path escapes configured root.")
    final_url, data, content_type = _request(url, max_bytes)
    digest = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None and (
        len(expected_sha256) != 64 or digest.casefold() != expected_sha256.casefold()
    ):
        raise ToolExecutionError("Downloaded file SHA-256 does not match expected checksum.")
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=root, prefix=".ultk-download-", delete=False) as handle:
            handle.write(data)
            temporary_path = handle.name
        os.replace(temporary_path, target)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)
    return {"url": final_url, "path": str(target), "bytes_written": len(data),
            "content_type": content_type, "sha256": digest,
            "checksum_verified": expected_sha256 is not None}


def _browser_open(url: str, timeout_ms: int = 10000) -> dict[str, Any]:
    _validate_public_url(url)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ToolExecutionError("Install the optional 'playwright' dependency and browser binaries.") from exc
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        def guard_route(route):
            try:
                _validate_public_url(route.request.url)
                route.continue_()
            except Exception:  # noqa: BLE001 - abort requests that fail URL validation
                route.abort()

        page.route("**/*", guard_route)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=min(timeout_ms, 20000))
            _validate_public_url(page.url)
            result = {"url": page.url, "title": page.title(),
                      "text": page.locator("body").inner_text(timeout=5000)[:20000]}
            return result
        finally:
            browser.close()


def create_web_tools(*, download_root: str = "./downloads") -> tuple[FunctionTool, ...]:
    """Create web tools. Browser automation additionally requires Playwright."""
    root = str(Path(download_root).expanduser().resolve())
    return (
        FunctionTool("web.search", "Search the public web using DuckDuckGo HTML results.",
                     object_schema({"query": {"type": "string", "minLength": 1, "maxLength": 300},
                                    "limit": {"type": "integer", "minimum": 1, "maximum": 10}},
                                   ["query"]), "web:search", _search, timeout=20),
        FunctionTool("web.fetch_url", "Fetch a bounded public HTTP(S) text or JSON resource.",
                     object_schema({"url": {"type": "string", "format": "uri"},
                                    "max_bytes": {"type": "integer", "minimum": 1, "maximum": 2000000}},
                                   ["url"]), "web:fetch", _fetch_url, timeout=20),
        FunctionTool("web.extract_page", "Extract title, readable text and links from a public HTML page.",
                     object_schema({"url": {"type": "string", "format": "uri"},
                                    "max_bytes": {"type": "integer", "minimum": 1, "maximum": 2000000}},
                                   ["url"]), "web:extract", _extract, timeout=20),
        FunctionTool("web.download_file", "Download a public URL into the configured download directory.",
                     object_schema({"url": {"type": "string", "format": "uri"},
                                    "filename": {"type": "string", "minLength": 1, "maxLength": 180},
                                    "max_bytes": {"type": "integer", "minimum": 1, "maximum": 5000000},
                                    "expected_sha256": {"type": "string", "pattern": "^[A-Fa-f0-9]{64}$"}},
                                   ["url", "filename"]),
                     "web:download", lambda url, filename, max_bytes=5000000, expected_sha256=None:
                     _download(url, filename, root, max_bytes, expected_sha256),
                     timeout=30),
        FunctionTool("web.browser_open", "Open a public page in headless Chromium and return visible text.",
                     object_schema({"url": {"type": "string", "format": "uri"},
                                    "timeout_ms": {"type": "integer", "minimum": 1000, "maximum": 20000}},
                                   ["url"]), "web:browser", _browser_open, timeout=30),
        FunctionTool("web.analyze_site", "Summarize page title, text length, links and metadata from an HTML page.",
                     object_schema({"url": {"type": "string", "format": "uri"}}, ["url"]),
                     "web:analyze", lambda url: _extract(url, 1000000), timeout=20),
    )

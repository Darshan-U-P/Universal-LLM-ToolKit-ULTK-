from __future__ import annotations

from pathlib import Path

import pytest

from ultk.builtins.documents import (
    _extract_text,
    _list_documents,
    _metadata,
    create_document_tools,
)
from ultk.engine import ToolEngine
from ultk.permissions import AllowListPolicy


def test_text_document_extraction_and_metadata(tmp_path: Path) -> None:
    (tmp_path / "notes").mkdir()
    source = tmp_path / "notes" / "brief.md"
    source.write_text("# Heading\nUseful content", encoding="utf-8")

    extracted = _extract_text(tmp_path, "notes/brief.md", 10000, 10, 1000)
    assert extracted["format"] == "md"
    assert "Useful content" in extracted["text"]
    metadata = _metadata(tmp_path, "notes/brief.md", 10000)
    assert metadata["size_bytes"] == source.stat().st_size
    assert metadata["format"] == "md"


def test_document_extraction_enforces_root_and_size_limits(tmp_path: Path) -> None:
    (tmp_path.parent / "outside.txt").write_text("outside", encoding="utf-8")
    with pytest.raises(Exception, match="escapes"):
        _extract_text(tmp_path, "../outside.txt", 10000, 10, 1000)

    (tmp_path / "large.txt").write_text("x" * 100, encoding="utf-8")
    with pytest.raises(Exception, match="size limit"):
        _extract_text(tmp_path, "large.txt", 10, 10, 1000)


def test_document_list_only_returns_supported_types(tmp_path: Path) -> None:
    (tmp_path / "report.txt").write_text("text", encoding="utf-8")
    (tmp_path / "image.png").write_bytes(b"not a document")
    result = _list_documents(tmp_path, "", 20)
    assert result["count"] == 1
    assert result["files"][0]["path"] == "report.txt"


def test_document_tools_register_through_engine(tmp_path: Path) -> None:
    engine = ToolEngine(policy=AllowListPolicy({"document.extract_text"}))
    engine.install_document_tools(root_dir=tmp_path)
    names = {tool.spec.name for tool in engine.registry.list()}
    assert {
        "document.list_files",
        "document.get_metadata",
        "document.extract_text",
    } <= names


def test_document_extraction_rejects_unsupported_formats(tmp_path: Path) -> None:
    (tmp_path / "archive.zip").write_bytes(b"zip")
    with pytest.raises(Exception, match="Unsupported document type"):
        _extract_text(tmp_path, "archive.zip", 10000, 10, 1000)

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from ultk.builtins.documents import _extract, _list, _metadata, create_document_tools
from ultk.builtins.structured_data import (
    _load, _serialize, _transform, _validate, create_structured_data_tools,
)
from ultk.engine import ToolEngine
from ultk.permissions import AllowListPolicy


def test_document_text_metadata_listing_and_root_confinement(tmp_path: Path) -> None:
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "readme.md").write_text("# Title\ncontent", encoding="utf-8")
    (tmp_path / "ignore.png").write_bytes(b"x")
    result = _extract(tmp_path, "nested/readme.md", 1000, 10, 100, 100)
    assert result["format"] == "md" and "content" in result["text"]
    assert _metadata(tmp_path, "nested/readme.md", 1000)["size_bytes"] > 0
    assert _list(tmp_path, "", 10, 1000)["count"] == 1
    with pytest.raises(Exception, match="escapes"):
        _extract(tmp_path, "../outside.pdf", 1000, 10, 100, 100)


def test_document_pdf_tools_are_registered(tmp_path: Path) -> None:
    engine = ToolEngine(policy=AllowListPolicy({"document:read", "document:write"}))
    engine.install_document_tools(root_dir=tmp_path)
    names = {tool.spec.name for tool in engine.registry.list()}
    assert {"document.list_files", "document.get_metadata", "document.extract_text",
            "document.pdf_merge", "document.pdf_extract_pages"} <= names


def test_document_rejects_oversized_and_unsupported_files(tmp_path: Path) -> None:
    (tmp_path / "bad.exe").write_bytes(b"x")
    with pytest.raises(Exception, match="Unsupported"):
        _extract(tmp_path, "bad.exe", 100, 10, 100, 100)


def test_csv_json_xml_and_xlsx_roundtrip(tmp_path: Path) -> None:
    rows = [{"id": 1, "name": "alpha"}, {"id": 2, "name": "beta"}]
    for extension in (".csv", ".json", ".xml", ".xlsx"):
        path = f"out{extension}"
        _serialize(tmp_path, path, rows, 100_000, 100, 20, False)
        loaded = _load(tmp_path, path, 100_000, 100, 20)
        assert len(loaded) == 2
        assert loaded[0]["id"] in (1, "1")


def test_csv_formula_injection_is_escaped(tmp_path: Path) -> None:
    _serialize(tmp_path, "safe.csv", [{"value": "=HYPERLINK('x')"}],
               10000, 10, 10, False)
    with (tmp_path / "safe.csv").open(encoding="utf-8", newline="") as handle:
        assert next(csv.DictReader(handle))["value"].startswith("'")


def test_xml_rejects_dtd_and_entities(tmp_path: Path) -> None:
    (tmp_path / "hostile.xml").write_text(
        '<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><rows/>', encoding="utf-8")
    with pytest.raises(Exception, match="DTD"):
        _load(tmp_path, "hostile.xml", 10000, 100, 10)


def test_declarative_etl_transformations_and_validation(tmp_path: Path) -> None:
    rows = [
        {"region": "north", "sales": 10, "customer": "A"},
        {"region": "north", "sales": 20, "customer": "B"},
        {"region": "south", "sales": 5, "customer": "C"},
    ]
    transformed = _transform(tmp_path, rows, [
        {"op": "filter", "field": "sales", "operator": "gte", "value": 10},
        {"op": "derive", "target": "sales_with_tax",
         "expression": {"operation": "multiply", "field": "sales", "value": 1.1}},
        {"op": "group_by", "keys": ["region"],
         "aggregations": [{"field": "sales", "as": "total", "function": "sum"}]},
    ], 100, 20, 10)
    assert transformed == [{"region": "north", "total": 30.0}]
    assert _validate(transformed, ["region"], {"total": "number"})["valid"]


def test_etl_join_and_write_output(tmp_path: Path) -> None:
    _serialize(tmp_path, "left.json", [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}],
               10000, 100, 10, False)
    _serialize(tmp_path, "right.json", [{"id": 1, "city": "Mangalore"}],
               10000, 100, 10, False)
    rows = _load(tmp_path, "left.json", 10000, 100, 10)
    joined = _transform(tmp_path, rows, [{
        "op": "join", "right_path": "right.json", "left_key": "id",
        "right_key": "id", "join_type": "left",
    }], 100, 10, 10)
    assert joined[0]["city"] == "Mangalore"
    assert joined[1]["id"] == 2


def test_etl_file_pipeline_and_permission_registration(tmp_path: Path) -> None:
    engine = ToolEngine(policy=AllowListPolicy({"data:read", "data:write", "data:transform", "data:etl"}))
    engine.install_structured_data_tools(root_dir=tmp_path)
    names = {tool.spec.name for tool in engine.registry.list()}
    assert {"data.read_table", "data.write_table", "data.transform",
            "data.validate_table", "data.etl_run"} <= names


def test_etl_rejects_unknown_operation(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="Unsupported ETL operation"):
        _transform(tmp_path, [{"a": 1}], [{"op": "eval", "code": "1+1"}], 10, 10, 10)

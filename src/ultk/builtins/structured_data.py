"""Bounded structured-file I/O and declarative ETL tools.

No model-supplied Python, SQL, XPath, regex, or expression strings are evaluated.
ETL transforms are a small allowlisted operation language over bounded row objects.
"""
from __future__ import annotations

import csv
import json
import math
import os
import tempfile
import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from ultk.builtins._common import FunctionTool, object_schema
from ultk.exceptions import ToolExecutionError

_FORMATS = {".csv", ".json", ".xml", ".xlsx"}
_SCALARS = (str, int, float, bool, type(None))


def _path(root: Path, relative: str, max_bytes: int, *, exists: bool = True) -> Path:
    if not isinstance(relative, str) or not relative or len(relative) > 500:
        raise ToolExecutionError("A relative data path of 1–500 characters is required.")
    candidate = Path(relative)
    if candidate.is_absolute():
        raise ToolExecutionError("Absolute paths are not allowed.")
    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root):
        raise ToolExecutionError("Path escapes the configured data root.")
    if exists:
        if not resolved.is_file():
            raise ToolExecutionError("Data file does not exist.")
        if resolved.stat().st_size > max_bytes:
            raise ToolExecutionError("Data file exceeds the configured byte limit.")
        if resolved.suffix.casefold() not in _FORMATS:
            raise ToolExecutionError("Unsupported data format.")
    elif resolved.suffix.casefold() not in _FORMATS:
        raise ToolExecutionError("Output must use CSV, JSON, XML or XLSX.")
    return resolved


def _atomic_write(path: Path, data: bytes, *, overwrite: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise ToolExecutionError("Destination exists; set overwrite=true explicitly.")
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=".ultk-data-", delete=False) as handle:
            handle.write(data)
            temp_name = handle.name
        if overwrite:
            os.replace(temp_name, path)
        else:
            os.link(temp_name, path)
            os.unlink(temp_name)
    except FileExistsError as exc:
        raise ToolExecutionError("Destination already exists.") from exc
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def _json_safe(value: Any, depth: int = 0) -> Any:
    if depth > 20:
        raise ToolExecutionError("Nested data exceeds the maximum depth.")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ToolExecutionError("NaN and infinity are not valid JSON values.")
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, list):
        return [_json_safe(item, depth + 1) for item in value]
    if isinstance(value, dict):
        if len(value) > 1000 or not all(isinstance(k, str) for k in value):
            raise ToolExecutionError("Objects must have at most 1000 string keys.")
        return {k: _json_safe(v, depth + 1) for k, v in value.items()}
    raise ToolExecutionError(f"Unsupported data value type: {type(value).__name__}.")


def _read_csv(path: Path, max_rows: int, max_columns: int) -> list[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise ToolExecutionError("CSV requires a header row.")
            if (any(not name for name in reader.fieldnames)
                    or len(reader.fieldnames) > max_columns
                    or len(set(reader.fieldnames)) != len(reader.fieldnames)):
                raise ToolExecutionError("CSV headers must be unique and within the column limit.")
            rows = []
            for row in reader:
                if len(rows) >= max_rows:
                    raise ToolExecutionError("CSV row count exceeds the configured limit.")
                if None in row:
                    raise ToolExecutionError("CSV row contains more fields than the header.")
                rows.append(dict(row))
            return rows
    except UnicodeDecodeError as exc:
        raise ToolExecutionError("CSV files must use UTF-8 encoding.") from exc


def _read_json(path: Path, max_rows: int) -> list[dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ToolExecutionError("File is not valid UTF-8 JSON.") from exc
    if isinstance(value, dict) and isinstance(value.get("rows"), list):
        value = value["rows"]
    if not isinstance(value, list) or len(value) > max_rows or any(not isinstance(r, dict) for r in value):
        raise ToolExecutionError("JSON table must be an array of objects (or an object with a rows array).")
    return [_json_safe(row) for row in value]


def _xml_parse(path: Path, max_rows: int) -> list[dict[str, Any]]:
    raw = path.read_bytes()
    upper = raw.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ToolExecutionError("XML DTDs and entity declarations are not allowed.")
    try:
        try:
            from defusedxml import ElementTree as SafeET
            root = SafeET.fromstring(raw)
        except ImportError:
            root = ET.fromstring(raw)
    except Exception as exc:
        raise ToolExecutionError(f"XML parsing failed ({type(exc).__name__}).") from exc
    records = list(root)
    if len(records) > max_rows:
        raise ToolExecutionError("XML record count exceeds the configured limit.")
    output = []
    for record in records:
        row: dict[str, Any] = {"_tag": record.tag}
        for child in list(record):
            key = child.attrib.get("name", child.tag)
            if key in row:
                current = row[key]
                row[key] = current + [child.text or ""] if isinstance(current, list) else [current, child.text or ""]
            else:
                row[key] = child.text or ""
        if record.text and record.text.strip():
            row["_text"] = record.text.strip()
        output.append(row)
    return output


def _xlsx_read(path: Path, max_rows: int, max_columns: int, sheet: str | None) -> list[dict[str, Any]]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise ToolExecutionError("Install the 'structured-data' extra to read XLSX files.") from exc
    workbook = None
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
        if sheet is not None:
            if sheet not in workbook.sheetnames:
                raise ToolExecutionError("Requested worksheet does not exist.")
            worksheet = workbook[sheet]
        else:
            worksheet = workbook.active
        iterator = worksheet.iter_rows(values_only=True)
        header = next(iterator, None)
        if not header:
            return []
        columns = [str(value).strip() if value is not None else "" for value in header]
        while columns and not columns[-1]:
            columns.pop()
        if not columns or len(columns) > max_columns or any(not c for c in columns) or len(set(columns)) != len(columns):
            raise ToolExecutionError("XLSX header row must contain unique non-empty column names.")
        rows = []
        for values in iterator:
            if len(rows) >= max_rows:
                raise ToolExecutionError("XLSX row count exceeds the configured limit.")
            rows.append({columns[i]: _json_safe(values[i]) if i < len(values) else None
                         for i in range(len(columns))})
        return rows
    except ToolExecutionError:
        raise
    except Exception as exc:
        raise ToolExecutionError(f"XLSX parsing failed ({type(exc).__name__}).") from exc
    finally:
        if workbook is not None:
            workbook.close()


def _load(root: Path, relative: str, max_bytes: int, max_rows: int,
          max_columns: int, sheet: str | None = None) -> list[dict[str, Any]]:
    path = _path(root, relative, max_bytes)
    ext = path.suffix.casefold()
    if ext == ".csv":
        rows = _read_csv(path, max_rows, max_columns)
    elif ext == ".json":
        rows = _read_json(path, max_rows)
    elif ext == ".xml":
        rows = _xml_parse(path, max_rows)
    else:
        rows = _xlsx_read(path, max_rows, max_columns, sheet)
    if len(rows) > max_rows:
        raise ToolExecutionError("Row count exceeds the configured limit.")
    if any(len(row) > max_columns for row in rows):
        raise ToolExecutionError("Column count exceeds the configured limit.")
    return rows


def _safe_spreadsheet_text(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def _serialize(root: Path, relative: str, rows: list[dict[str, Any]], max_bytes: int,
               max_rows: int, max_columns: int, overwrite: bool, sheet_name: str = "Data") -> dict[str, Any]:
    if len(rows) > max_rows or any(not isinstance(row, dict) for row in rows):
        raise ToolExecutionError("Output rows must be objects within the configured row limit.")
    columns: list[str] = []
    for row in rows:
        for key in row:
            if not isinstance(key, str) or not key:
                raise ToolExecutionError("Column names must be non-empty strings.")
            if key not in columns:
                columns.append(key)
    if len(columns) > max_columns:
        raise ToolExecutionError("Output exceeds the configured column limit.")
    path = _path(root, relative, max_bytes, exists=False)
    ext = path.suffix.casefold()
    try:
        if ext == ".json":
            data = json.dumps({"columns": columns, "rows": _json_safe(rows)},
                              ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
        elif ext == ".csv":
            import io
            buffer = io.StringIO(newline="")
            writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({k: _safe_spreadsheet_text(_json_safe(v)) for k, v in row.items()})
            data = buffer.getvalue().encode("utf-8")
        elif ext == ".xml":
            root_element = ET.Element("rows")
            for row in rows:
                record = ET.SubElement(root_element, "row")
                for key in columns:
                    child = ET.SubElement(record, "field", name=key)
                    value = row.get(key)
                    child.text = "" if value is None else str(_json_safe(value))
            data = ET.tostring(root_element, encoding="utf-8", xml_declaration=True)
        else:
            try:
                from openpyxl import Workbook
            except ImportError as exc:
                raise ToolExecutionError("Install the 'structured-data' extra to write XLSX files.") from exc
            import io
            workbook = Workbook(write_only=True)
            worksheet = workbook.create_sheet(title=sheet_name[:31] or "Data")
            worksheet.append(columns)
            for row in rows:
                worksheet.append([_safe_spreadsheet_text(_json_safe(row.get(column))) for column in columns])
            buffer = io.BytesIO()
            workbook.save(buffer)
            data = buffer.getvalue()
    except ToolExecutionError:
        raise
    except Exception as exc:
        raise ToolExecutionError(f"Could not serialize output ({type(exc).__name__}).") from exc
    if len(data) > max_bytes:
        raise ToolExecutionError("Serialized output exceeds the configured byte limit.")
    _atomic_write(path, data, overwrite=overwrite)
    return {"path": relative, "format": ext[1:], "rows_written": len(rows),
            "columns": columns, "bytes_written": len(data)}


def _filter(rows: list[dict[str, Any]], field: str, operator: str, value: Any) -> list[dict[str, Any]]:
    allowed = {"eq", "ne", "gt", "gte", "lt", "lte", "contains", "in", "is_null", "not_null"}
    if operator not in allowed:
        raise ToolExecutionError("Unsupported filter operator.")
    def match(row: dict[str, Any]) -> bool:
        actual = row.get(field)
        try:
            if operator == "eq":
                return actual == value
            if operator == "ne":
                return actual != value
            if operator == "gt":
                return actual is not None and actual > value
            if operator == "gte":
                return actual is not None and actual >= value
            if operator == "lt":
                return actual is not None and actual < value
            if operator == "lte":
                return actual is not None and actual <= value
            if operator == "contains":
                return value in actual if actual is not None else False
            if operator == "in":
                return actual in value
            if operator == "is_null":
                return actual is None
            return actual is not None
        except (TypeError, ValueError):
            return False
    return [row for row in rows if match(row)]


def _derive_value(row: dict[str, Any], operation: dict[str, Any]) -> Any:
    op = operation["operation"]
    field = operation.get("field")
    value = row.get(field) if field else operation.get("value")
    if op == "constant":
        return operation.get("value")
    if op == "lower":
        return str(value or "").lower()
    if op == "upper":
        return str(value or "").upper()
    if op == "trim":
        return str(value or "").strip()
    if op == "coalesce":
        return next((row.get(name) for name in operation.get("fields", []) if row.get(name) is not None), None)
    if op == "concat":
        return str(row.get(operation["left"], "")) + str(row.get(operation["right"], ""))
    right = operation.get("value", 0)
    try:
        left_num, right_num = float(value), float(right)
        if op == "add":
            result = left_num + right_num
        elif op == "subtract":
            result = left_num - right_num
        elif op == "multiply":
            result = left_num * right_num
        elif op == "divide":
            if right_num == 0:
                return None
            result = left_num / right_num
        else:
            raise ToolExecutionError("Unsupported derive operation.")
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _transform(root: Path, rows: list[dict[str, Any]], operations: list[dict[str, Any]],
               max_rows: int, max_columns: int, max_operations: int,
               max_file_bytes: int = 25_000_000) -> list[dict[str, Any]]:
    if not 1 <= len(operations) <= max_operations:
        raise ToolExecutionError("ETL operation count is outside the configured bound.")
    result = [dict(row) for row in rows]
    for step in operations:
        op = step.get("op")
        if op == "select":
            fields = step.get("fields", [])
            if not fields or len(fields) > max_columns:
                raise ToolExecutionError("select requires 1–max_columns fields.")
            result = [{field: row.get(field) for field in fields} for row in result]
        elif op == "rename":
            mapping = step.get("mapping", {})
            if not mapping or len(mapping) > max_columns:
                raise ToolExecutionError("rename requires a non-empty bounded mapping.")
            result = [{mapping.get(k, k): v for k, v in row.items()} for row in result]
        elif op == "filter":
            result = _filter(result, step["field"], step["operator"], step.get("value"))
        elif op == "sort":
            field = step["field"]
            result.sort(key=lambda row: (row.get(field) is None, str(row.get(field))),
                        reverse=bool(step.get("descending", False)))
        elif op == "deduplicate":
            keys = step.get("keys", [])
            seen = set()
            unique = []
            for row in result:
                token = tuple(json.dumps(_json_safe(row.get(key)), sort_keys=True) for key in keys) if keys else json.dumps(_json_safe(row), sort_keys=True)
                if token not in seen:
                    seen.add(token)
                    unique.append(row)
            result = unique
        elif op == "derive":
            target = step["target"]
            spec = step["expression"]
            if not isinstance(spec, dict) or spec.get("operation") not in {
                "constant", "lower", "upper", "trim", "coalesce", "concat",
                "add", "subtract", "multiply", "divide"}:
                raise ToolExecutionError("derive expression uses an unsupported operation.")
            result = [{**row, target: _derive_value(row, spec)} for row in result]
        elif op == "group_by":
            keys = step.get("keys", [])
            aggregations = step.get("aggregations", [])
            groups: dict[str, list[dict[str, Any]]] = {}
            for row in result:
                token = json.dumps([_json_safe(row.get(k)) for k in keys], sort_keys=True)
                groups.setdefault(token, []).append(row)
            grouped = []
            for members in groups.values():
                item = {key: members[0].get(key) for key in keys}
                for agg in aggregations:
                    field, name, fn = agg["field"], agg["as"], agg["function"]
                    values = [r.get(field) for r in members if r.get(field) is not None]
                    nums = [float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
                    if fn == "count":
                        value = len(values)
                    elif fn == "sum":
                        value = sum(nums)
                    elif fn == "avg":
                        value = sum(nums) / len(nums) if nums else None
                    elif fn == "min":
                        value = min(values) if values else None
                    elif fn == "max":
                        value = max(values) if values else None
                    elif fn == "first":
                        value = values[0] if values else None
                    else:
                        raise ToolExecutionError("Unsupported aggregation function.")
                    item[name] = value
                grouped.append(item)
            result = grouped
        elif op == "join":
            right_path = step["right_path"]
            right_rows = _load(root, right_path, max_file_bytes,
                               max_rows, max_columns, step.get("right_sheet"))
            left_key, right_key = step["left_key"], step["right_key"]
            join_type = step.get("join_type", "inner")
            if join_type not in {"inner", "left"}:
                raise ToolExecutionError("Only inner and left joins are supported.")
            right_index: dict[str, list[dict[str, Any]]] = {}
            for row in right_rows:
                right_index.setdefault(json.dumps(_json_safe(row.get(right_key)), sort_keys=True), []).append(row)
            merged = []
            suffix = step.get("suffix", "_right")
            for left in result:
                matches = right_index.get(json.dumps(_json_safe(left.get(left_key)), sort_keys=True), [])
                if not matches and join_type == "left":
                    merged.append(dict(left))
                for right in matches:
                    combined = dict(left)
                    for key, value in right.items():
                        if key == right_key and right_key == left_key:
                            continue
                        target = key if key not in combined else key + suffix
                        combined[target] = value
                    merged.append(combined)
                    if len(merged) > max_rows:
                        raise ToolExecutionError("Join output exceeds the configured row limit.")
            result = merged
        else:
            raise ToolExecutionError(f"Unsupported ETL operation: {op!r}.")
        if len(result) > max_rows or any(len(row) > max_columns for row in result):
            raise ToolExecutionError("ETL output exceeds configured row or column limits.")
    return result


def _validate(rows: list[dict[str, Any]], required: list[str],
              field_types: dict[str, str]) -> dict[str, Any]:
    errors = []
    allowed = {"string", "integer", "number", "boolean", "array", "object", "nullable"}
    if set(field_types.values()) - allowed:
        raise ToolExecutionError("Unsupported field type in validation schema.")
    for index, row in enumerate(rows):
        for field in required:
            if field not in row or row[field] is None:
                errors.append({"row": index, "field": field, "error": "required"})
        for field, expected in field_types.items():
            value = row.get(field)
            if value is None and expected == "nullable":
                continue
            valid = {
                "string": lambda v: isinstance(v, str),
                "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
                "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v)),
                "boolean": lambda v: isinstance(v, bool),
                "array": lambda v: isinstance(v, list),
                "object": lambda v: isinstance(v, dict),
                "nullable": lambda v: v is not None,
            }[expected](value)
            if not valid:
                errors.append({"row": index, "field": field, "error": f"expected {expected}"})
        if len(errors) >= 100:
            break
    return {"valid": not errors, "rows_checked": len(rows), "error_count": len(errors), "errors": errors}


def _transform_result(root: Path, rows: list[dict[str, Any]], operations: list[dict[str, Any]],
                      max_rows: int, max_columns: int, max_operations: int,
                      max_file_bytes: int) -> dict[str, Any]:
    transformed = _transform(root, rows, operations, max_rows, max_columns,
                              max_operations, max_file_bytes)
    return {"rows": transformed, "row_count": len(transformed)}


def create_structured_data_tools(*, root_dir: str | Path, max_file_bytes: int = 25_000_000,
                                 max_rows: int = 50_000, max_columns: int = 500,
                                 max_operations: int = 30) -> tuple[FunctionTool, ...]:
    root = Path(root_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if not 1 <= max_file_bytes <= 500_000_000 or not 1 <= max_rows <= 1_000_000:
        raise ValueError("Invalid structured-data byte or row limit.")
    if not 1 <= max_columns <= 2000 or not 1 <= max_operations <= 100:
        raise ValueError("Invalid structured-data column or operation limit.")
    path_prop = {"type": "string", "minLength": 1, "maxLength": 500}
    return (
        FunctionTool("data.read_table", "Read a bounded CSV, JSON, XML or XLSX table.",
            object_schema({"path": path_prop, "sheet": {"type": "string", "maxLength": 31},
                           "limit": {"type": "integer", "minimum": 1, "maximum": max_rows}}, ["path"]),
            "data:read", lambda path, sheet=None, limit=max_rows: {
                "path": path, "rows": _load(root, path, max_file_bytes, limit, max_columns, sheet),
                "row_limit": limit}, timeout=60, output_limit=200_000),
        FunctionTool("data.write_table", "Write table rows to CSV, JSON, XML or XLSX within the configured root.",
            object_schema({"path": path_prop,
                           "rows": {"type": "array", "maxItems": max_rows, "items": {"type": "object"}},
                           "overwrite": {"type": "boolean"}, "sheet_name": {"type": "string", "maxLength": 31}},
                          ["path", "rows"]),
            "data:write", lambda path, rows, overwrite=False, sheet_name="Data":
                _serialize(root, path, rows, max_file_bytes, max_rows, max_columns, overwrite, sheet_name),
            timeout=60, output_limit=5000),
        FunctionTool("data.transform", "Apply bounded declarative transformations to an in-memory row set.",
            object_schema({"rows": {"type": "array", "maxItems": max_rows, "items": {"type": "object"}},
                           "operations": {"type": "array", "minItems": 1, "maxItems": max_operations,
                                          "items": {"type": "object"}}}, ["rows", "operations"]),
            "data:transform", lambda rows, operations: _transform_result(
                root, rows, operations, max_rows, max_columns, max_operations, max_file_bytes),
            timeout=60, output_limit=200_000),
        FunctionTool("data.validate_table", "Validate table rows against required columns and primitive field types.",
            object_schema({"rows": {"type": "array", "maxItems": max_rows, "items": {"type": "object"}},
                           "required": {"type": "array", "items": {"type": "string", "maxLength": 200},
                                        "maxItems": max_columns},
                           "field_types": {"type": "object", "additionalProperties": {"type": "string"}}},
                          ["rows"]),
            "data:read", lambda rows, required=None, field_types=None:
                _validate(rows, required or [], field_types or {}),
            timeout=30, output_limit=20_000),
        FunctionTool("data.etl_run", "Read a source table, apply safe declarative ETL steps, and write a destination table.",
            object_schema({"source": path_prop, "destination": path_prop,
                           "sheet": {"type": "string", "maxLength": 31},
                           "destination_sheet": {"type": "string", "maxLength": 31},
                           "operations": {"type": "array", "minItems": 1, "maxItems": max_operations,
                                          "items": {"type": "object"}},
                           "overwrite": {"type": "boolean"}}, ["source", "destination", "operations"]),
            "data:etl", lambda source, destination, operations, sheet=None,
                destination_sheet="Data", overwrite=False:
                _etl(root, source, destination, operations, sheet, destination_sheet,
                     overwrite, max_file_bytes, max_rows, max_columns, max_operations),
            timeout=120, output_limit=10_000),
    )


def _etl(root: Path, source: str, destination: str, operations: list[dict[str, Any]],
         sheet: str | None, destination_sheet: str, overwrite: bool, max_bytes: int,
         max_rows: int, max_columns: int, max_operations: int) -> dict[str, Any]:
    rows = _load(root, source, max_bytes, max_rows, max_columns, sheet)
    transformed = _transform(root, rows, operations, max_rows, max_columns, max_operations, max_bytes)
    written = _serialize(root, destination, transformed, max_bytes, max_rows,
                         max_columns, overwrite, destination_sheet)
    return {"source": source, "destination": written, "rows_read": len(rows),
            "rows_written": len(transformed), "operations_applied": len(operations)}

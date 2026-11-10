"""Bounded document discovery, extraction and safe PDF operations.

Parsers are optional dependencies. All paths are relative to a host-configured root.
Parsing untrusted office/PDF files should still run in an OS-restricted worker.
"""
from __future__ import annotations

import os
import tempfile
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from ultk.builtins._common import FunctionTool, object_schema
from ultk.exceptions import ToolExecutionError

_SUPPORTED = {".txt", ".md", ".pdf", ".docx", ".pptx", ".xlsx", ".xls", ".odt", ".ods"}


def _rooted(root: Path, relative: str, max_bytes: int, *, must_exist: bool = True) -> Path:
    if not isinstance(relative, str) or not relative or len(relative) > 500:
        raise ToolExecutionError("A relative document path of 1–500 characters is required.")
    candidate = Path(relative)
    if candidate.is_absolute():
        raise ToolExecutionError("Absolute document paths are not allowed.")
    path = (root / candidate).resolve()
    if not path.is_relative_to(root):
        raise ToolExecutionError("Document path escapes the configured root.")
    if must_exist:
        if not path.is_file():
            raise ToolExecutionError("Document does not exist or is not a regular file.")
        if path.stat().st_size > max_bytes:
            raise ToolExecutionError("Document exceeds the configured byte limit.")
        if path.suffix.casefold() not in _SUPPORTED:
            raise ToolExecutionError("Unsupported document format.")
    return path


def _append(parts: list[str], text: str, limit: int) -> None:
    remaining = limit - sum(map(len, parts))
    if remaining > 0:
        parts.append(text[:remaining])


def _pdf(path: Path, max_units: int, max_chars: int) -> dict[str, Any]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ToolExecutionError("Install the 'documents' extra to parse PDF files.") from exc
    try:
        reader = PdfReader(str(path), strict=False)
        if reader.is_encrypted:
            raise ToolExecutionError("Encrypted PDFs are not supported.")
        total = len(reader.pages)
        parts: list[str] = []
        for i, page in enumerate(reader.pages[:max_units]):
            _append(parts, f"\n[Page {i + 1}]\n", max_chars)
            _append(parts, page.extract_text(extraction_mode="layout") or "", max_chars)
            if sum(map(len, parts)) >= max_chars:
                break
        return {"text": "".join(parts), "units_processed": min(total, max_units),
                "total_units": total, "truncated": total > max_units or sum(map(len, parts)) >= max_chars,
                "metadata": {str(k): str(v)[:1000] for k, v in (reader.metadata or {}).items()}}
    except ToolExecutionError:
        raise
    except Exception as exc:
        raise ToolExecutionError(f"PDF parsing failed ({type(exc).__name__}).") from exc


def _docx(path: Path, max_units: int, max_chars: int) -> dict[str, Any]:
    try:
        from docx import Document
    except ImportError as exc:
        raise ToolExecutionError("Install the 'documents' extra to parse DOCX files.") from exc
    try:
        doc = Document(str(path))
        parts: list[str] = []
        for paragraph in doc.paragraphs[:max_units * 200]:
            _append(parts, paragraph.text + "\n", max_chars)
        table_count = 0
        for table_count, table in enumerate(doc.tables[:max_units], start=1):
            _append(parts, f"\n[Table {table_count}]\n", max_chars)
            for row in table.rows:
                _append(parts, " | ".join(cell.text for cell in row.cells) + "\n", max_chars)
                if sum(map(len, parts)) >= max_chars:
                    break
            if sum(map(len, parts)) >= max_chars:
                break
        return {"text": "".join(parts), "units_processed": min(len(doc.tables), max_units),
                "total_units": len(doc.tables), "paragraphs": len(doc.paragraphs),
                "tables": len(doc.tables), "truncated": sum(map(len, parts)) >= max_chars}
    except Exception as exc:
        raise ToolExecutionError(f"DOCX parsing failed ({type(exc).__name__}).") from exc


def _pptx(path: Path, max_units: int, max_chars: int) -> dict[str, Any]:
    try:
        from pptx import Presentation
    except ImportError as exc:
        raise ToolExecutionError("Install the 'documents' extra to parse PPTX files.") from exc
    try:
        presentation = Presentation(str(path))
        total = len(presentation.slides)
        parts: list[str] = []
        for index, slide in enumerate(presentation.slides, start=1):
            if index > max_units:
                break
            _append(parts, f"\n[Slide {index}]\n", max_chars)
            for shape in slide.shapes:
                if getattr(shape, "has_text_frame", False):
                    _append(parts, shape.text + "\n", max_chars)
                if getattr(shape, "has_table", False):
                    for row in shape.table.rows:
                        _append(parts, " | ".join(cell.text for cell in row.cells) + "\n", max_chars)
                if sum(map(len, parts)) >= max_chars:
                    break
            if sum(map(len, parts)) >= max_chars:
                break
        return {"text": "".join(parts), "units_processed": min(total, max_units),
                "total_units": total, "truncated": total > max_units or sum(map(len, parts)) >= max_chars}
    except Exception as exc:
        raise ToolExecutionError(f"PPTX parsing failed ({type(exc).__name__}).") from exc


def _xlsx(path: Path, max_units: int, max_chars: int, max_rows: int) -> dict[str, Any]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise ToolExecutionError("Install the 'documents' extra to parse XLSX files.") from exc
    workbook = None
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
        names = workbook.sheetnames
        parts: list[str] = []
        processed_rows = 0
        for sheet in workbook.worksheets[:max_units]:
            _append(parts, f"\n[Sheet {sheet.title}]\n", max_chars)
            for row_index, row in enumerate(sheet.iter_rows(values_only=True)):
                if row_index >= max_rows:
                    _append(parts, "[Row limit reached]\n", max_chars)
                    break
                values = []
                for value in row:
                    if isinstance(value, (datetime, date, time)):
                        values.append(value.isoformat())
                    else:
                        values.append("" if value is None else str(value))
                _append(parts, " | ".join(values) + "\n", max_chars)
                processed_rows += 1
                if sum(map(len, parts)) >= max_chars:
                    break
            if sum(map(len, parts)) >= max_chars:
                break
        return {"text": "".join(parts), "units_processed": min(len(names), max_units),
                "total_units": len(names), "rows_processed": processed_rows,
                "truncated": len(names) > max_units or processed_rows >= max_rows
                or sum(map(len, parts)) >= max_chars}
    except Exception as exc:
        raise ToolExecutionError(f"XLSX parsing failed ({type(exc).__name__}).") from exc
    finally:
        if workbook is not None:
            workbook.close()


def _xls(path: Path, max_units: int, max_chars: int, max_rows: int) -> dict[str, Any]:
    try:
        import xlrd
    except ImportError as exc:
        raise ToolExecutionError("Install the 'documents-xls' extra to parse legacy XLS files.") from exc
    try:
        book = xlrd.open_workbook(str(path), on_demand=True)
        names = book.sheet_names()
        parts: list[str] = []
        processed = 0
        for name in names[:max_units]:
            sheet = book.sheet_by_name(name)
            _append(parts, f"\n[Sheet {name}]\n", max_chars)
            for row_index in range(min(sheet.nrows, max_rows)):
                _append(parts, " | ".join(str(v) for v in sheet.row_values(row_index)) + "\n", max_chars)
                processed += 1
                if sum(map(len, parts)) >= max_chars:
                    break
            if sum(map(len, parts)) >= max_chars:
                break
        book.release_resources()
        return {"text": "".join(parts), "units_processed": min(len(names), max_units),
                "total_units": len(names), "rows_processed": processed,
                "truncated": len(names) > max_units or processed >= max_rows
                or sum(map(len, parts)) >= max_chars}
    except Exception as exc:
        raise ToolExecutionError(f"XLS parsing failed ({type(exc).__name__}).") from exc


def _odf(path: Path, extension: str, max_units: int, max_chars: int) -> dict[str, Any]:
    try:
        from odf import table as odf_table
        from odf import text as odf_text
        from odf.opendocument import load
        from odf.teletype import extractText
    except ImportError as exc:
        raise ToolExecutionError("Install the 'documents-odf' extra to parse ODT/ODS files.") from exc
    try:
        document = load(str(path))
        parts: list[str] = []
        if extension == ".odt":
            paragraphs = document.getElementsByType(odf_text.P)
            for paragraph in paragraphs[:max_units * 200]:
                _append(parts, extractText(paragraph) + "\n", max_chars)
            total = len(paragraphs)
        else:
            tables = document.getElementsByType(odf_table.Table)
            for index, sheet in enumerate(tables[:max_units], start=1):
                _append(parts, f"\n[Sheet {index}]\n", max_chars)
                for row in sheet.getElementsByType(odf_table.TableRow):
                    cells = row.getElementsByType(odf_table.TableCell)
                    _append(parts, " | ".join(extractText(cell) for cell in cells) + "\n", max_chars)
                    if sum(map(len, parts)) >= max_chars:
                        break
            total = len(tables)
        return {"text": "".join(parts), "units_processed": min(total, max_units),
                "total_units": total, "truncated": total > max_units
                or sum(map(len, parts)) >= max_chars}
    except Exception as exc:
        raise ToolExecutionError(f"ODF parsing failed ({type(exc).__name__}).") from exc


def _extract(root: Path, relative: str, max_bytes: int, max_units: int,
             max_chars: int, max_rows: int) -> dict[str, Any]:
    if not 1 <= max_units <= 200 or not 1 <= max_chars <= 200_000:
        raise ToolExecutionError("max_units must be 1–200 and max_chars 1–200000.")
    if not 1 <= max_rows <= 20_000:
        raise ToolExecutionError("max_rows must be between 1 and 20000.")
    path = _rooted(root, relative, max_bytes)
    ext = path.suffix.casefold()
    if ext in {".txt", ".md"}:
        try:
            value = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ToolExecutionError("Text files must be UTF-8.") from exc
        return {"path": relative, "format": ext[1:], "text": value[:max_chars],
                "units_processed": 1, "total_units": 1, "truncated": len(value) > max_chars}
    parsers = {
        ".pdf": lambda: _pdf(path, max_units, max_chars),
        ".docx": lambda: _docx(path, max_units, max_chars),
        ".pptx": lambda: _pptx(path, max_units, max_chars),
        ".xlsx": lambda: _xlsx(path, max_units, max_chars, max_rows),
        ".xls": lambda: _xls(path, max_units, max_chars, max_rows),
        ".odt": lambda: _odf(path, ext, max_units, max_chars),
        ".ods": lambda: _odf(path, ext, max_units, max_chars),
    }
    return {"path": relative, "format": ext[1:], **parsers[ext]()}


def _metadata(root: Path, relative: str, max_bytes: int) -> dict[str, Any]:
    path = _rooted(root, relative, max_bytes)
    stat = path.stat()
    return {"path": relative, "format": path.suffix.casefold()[1:],
            "size_bytes": stat.st_size,
            "modified_time": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat()}


def _list(root: Path, directory: str, limit: int, max_bytes: int) -> dict[str, Any]:
    if not 1 <= limit <= 1000:
        raise ToolExecutionError("limit must be between 1 and 1000.")
    base = root if not directory else (root / directory).resolve()
    if not base.is_relative_to(root) or not base.is_dir():
        raise ToolExecutionError("Directory is invalid or escapes the configured root.")
    found = []
    for path in sorted(base.rglob("*")):
        try:
            resolved = path.resolve()
            if path.is_file() and resolved.is_relative_to(root) and resolved.suffix.casefold() in _SUPPORTED:
                size = resolved.stat().st_size
                found.append({"path": str(resolved.relative_to(root)),
                              "format": resolved.suffix.casefold()[1:],
                              "size_bytes": size, "within_size_limit": size <= max_bytes})
                if len(found) >= limit:
                    break
        except OSError:
            continue
    return {"files": found, "count": len(found), "limit": limit}


def _atomic_output(path: Path, data: bytes, *, overwrite: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise ToolExecutionError("Destination already exists; set overwrite=true explicitly.")
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=".ultk-doc-", delete=False) as handle:
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


def _pdf_merge(root: Path, inputs: list[str], output: str, max_bytes: int,
               max_pages: int, overwrite: bool) -> dict[str, Any]:
    if not 2 <= len(inputs) <= 20:
        raise ToolExecutionError("PDF merge requires 2–20 input files.")
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError as exc:
        raise ToolExecutionError("Install the 'documents' extra to merge PDF files.") from exc
    target = _rooted(root, output, max_bytes, must_exist=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix.casefold() != ".pdf":
        raise ToolExecutionError("PDF output path must end in .pdf.")
    writer = PdfWriter()
    total = 0
    for item in inputs:
        source = _rooted(root, item, max_bytes)
        if source.suffix.casefold() != ".pdf":
            raise ToolExecutionError("All merge inputs must be PDF files.")
        try:
            reader = PdfReader(str(source), strict=False)
            if reader.is_encrypted:
                raise ToolExecutionError("Encrypted PDFs cannot be merged.")
            total += len(reader.pages)
            if total > max_pages:
                raise ToolExecutionError("Merged PDF exceeds the configured page limit.")
            for page in reader.pages:
                writer.add_page(page)
        except ToolExecutionError:
            raise
        except Exception as exc:
            raise ToolExecutionError(f"PDF input could not be parsed ({type(exc).__name__}).") from exc
    with tempfile.NamedTemporaryFile("w+b", dir=target.parent, prefix=".ultk-pdf-", delete=False) as handle:
        temp = Path(handle.name)
    try:
        with temp.open("wb") as stream:
            writer.write(stream)
        if temp.stat().st_size > max_bytes:
            raise ToolExecutionError("Merged PDF exceeds the configured output byte limit.")
        _atomic_output(target, temp.read_bytes(), overwrite=overwrite)
    finally:
        temp.unlink(missing_ok=True)
    return {"path": output, "pages": total, "bytes_written": target.stat().st_size}


def _pdf_extract_pages(root: Path, source_name: str, output: str, start_page: int,
                        end_page: int, max_bytes: int, max_pages: int,
                        overwrite: bool) -> dict[str, Any]:
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError as exc:
        raise ToolExecutionError("Install the 'documents' extra to extract PDF pages.") from exc
    source = _rooted(root, source_name, max_bytes)
    target = _rooted(root, output, max_bytes, must_exist=False)
    if source.suffix.casefold() != ".pdf" or target.suffix.casefold() != ".pdf":
        raise ToolExecutionError("Source and destination must be PDF files.")
    if start_page < 1 or end_page < start_page or end_page - start_page + 1 > max_pages:
        raise ToolExecutionError("Page range is invalid or exceeds the configured limit.")
    try:
        reader = PdfReader(str(source), strict=False)
        if reader.is_encrypted:
            raise ToolExecutionError("Encrypted PDFs are not supported.")
        if end_page > len(reader.pages):
            raise ToolExecutionError("Requested page range exceeds the PDF page count.")
        writer = PdfWriter()
        for index in range(start_page - 1, end_page):
            writer.add_page(reader.pages[index])
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w+b", dir=target.parent, prefix=".ultk-pdf-", delete=False) as handle:
            temp = Path(handle.name)
        try:
            with temp.open("wb") as stream:
                writer.write(stream)
            if temp.stat().st_size > max_bytes:
                raise ToolExecutionError("Extracted PDF exceeds the configured byte limit.")
            _atomic_output(target, temp.read_bytes(), overwrite=overwrite)
        finally:
            temp.unlink(missing_ok=True)
        return {"path": output, "pages": end_page - start_page + 1,
                "bytes_written": target.stat().st_size}
    except ToolExecutionError:
        raise
    except Exception as exc:
        raise ToolExecutionError(f"PDF page extraction failed ({type(exc).__name__}).") from exc


def create_document_tools(*, root_dir: str | Path, max_file_bytes: int = 25_000_000,
                          max_output_chars: int = 50_000, max_pdf_pages: int = 500) -> tuple[FunctionTool, ...]:
    root = Path(root_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if not 1 <= max_file_bytes <= 500_000_000:
        raise ValueError("max_file_bytes must be between 1 byte and 500 MB.")
    if not 1 <= max_output_chars <= 200_000 or not 1 <= max_pdf_pages <= 5000:
        raise ValueError("Invalid document output or page limit.")
    path_prop = {"type": "string", "minLength": 1, "maxLength": 500}
    return (
        FunctionTool("document.list_files", "List supported documents under the configured root.",
            object_schema({"directory": {"type": "string", "maxLength": 500},
                           "limit": {"type": "integer", "minimum": 1, "maximum": 1000}}),
            "document:read", lambda directory="", limit=100: _list(root, directory, limit, max_file_bytes)),
        FunctionTool("document.get_metadata", "Get bounded metadata for a supported document.",
            object_schema({"path": path_prop}, ["path"]), "document:read",
            lambda path: _metadata(root, path, max_file_bytes)),
        FunctionTool("document.extract_text", "Extract bounded text from TXT, Markdown, PDF, DOCX, PPTX, XLSX, XLS, ODT or ODS.",
            object_schema({"path": path_prop,
                "max_units": {"type": "integer", "minimum": 1, "maximum": 200},
                "max_chars": {"type": "integer", "minimum": 1, "maximum": max_output_chars},
                "max_rows": {"type": "integer", "minimum": 1, "maximum": 20000}}, ["path"]),
            "document:read", lambda path, max_units=50, max_chars=max_output_chars, max_rows=2000:
                _extract(root, path, max_file_bytes, max_units, max_chars, max_rows),
            timeout=90, output_limit=max_output_chars + 4000),
        FunctionTool("document.pdf_merge", "Merge 2–20 PDFs into a new PDF inside the configured root.",
            object_schema({"inputs": {"type": "array", "minItems": 2, "maxItems": 20,
                                      "items": path_prop},
                           "output": path_prop,
                           "overwrite": {"type": "boolean"}},
                          ["inputs", "output"]),
            "document:write", lambda inputs, output, overwrite=False:
                _pdf_merge(root, inputs, output, max_file_bytes, max_pdf_pages, overwrite),
            timeout=90, output_limit=2000),
        FunctionTool("document.pdf_extract_pages", "Extract an inclusive page range into a new PDF.",
            object_schema({"source": path_prop, "output": path_prop,
                           "start_page": {"type": "integer", "minimum": 1},
                           "end_page": {"type": "integer", "minimum": 1},
                           "overwrite": {"type": "boolean"}},
                          ["source", "output", "start_page", "end_page"]),
            "document:write", lambda source, output, start_page, end_page, overwrite=False:
                _pdf_extract_pages(root, source, output, start_page, end_page,
                                    max_file_bytes, max_pdf_pages, overwrite),
            timeout=90, output_limit=2000),
    )

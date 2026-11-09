"""Bounded text extraction and metadata tools for common office documents."""

from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from ultk.builtins._common import FunctionTool, object_schema
from ultk.exceptions import ToolExecutionError


_SUPPORTED = {".txt", ".md", ".pdf", ".docx", ".pptx", ".xlsx"}


def _document_path(root: Path, relative_path: str, max_file_bytes: int) -> Path:
    if not relative_path or len(relative_path) > 500:
        raise ToolExecutionError("A relative document path of at most 500 characters is required.")
    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise ToolExecutionError("Absolute document paths are not allowed.")
    path = (root / candidate).resolve()
    if not path.is_relative_to(root):
        raise ToolExecutionError("Document path escapes the configured root.")
    if not path.is_file():
        raise ToolExecutionError("Document does not exist.")
    if path.stat().st_size > max_file_bytes:
        raise ToolExecutionError("Document exceeds the configured file-size limit.")
    if path.suffix.casefold() not in _SUPPORTED:
        raise ToolExecutionError(
            f"Unsupported document type: {path.suffix or '[no extension]'}."
        )
    return path


def _append_limited(parts: list[str], value: str, max_chars: int) -> None:
    current = sum(len(part) for part in parts)
    if current >= max_chars:
        return
    parts.append(value[: max_chars - current])


def _extract_pdf(path: Path, max_pages: int, max_chars: int) -> dict[str, Any]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ToolExecutionError("Install the 'documents' extra to read PDF files.") from exc
    reader = PdfReader(str(path), strict=False)
    if reader.is_encrypted:
        raise ToolExecutionError("Encrypted PDFs are not supported.")
    parts: list[str] = []
    page_count = min(len(reader.pages), max_pages)
    for index in range(page_count):
        _append_limited(parts, f"\n[Page {index + 1}]\n", max_chars)
        _append_limited(parts, reader.pages[index].extract_text() or "", max_chars)
    return {"text": "".join(parts), "pages_processed": page_count,
            "total_pages": len(reader.pages), "truncated": len(reader.pages) > page_count}


def _extract_docx(path: Path, max_chars: int) -> dict[str, Any]:
    try:
        from docx import Document
    except ImportError as exc:
        raise ToolExecutionError("Install the 'documents' extra to read DOCX files.") from exc
    document = Document(str(path))
    parts: list[str] = []
    for paragraph in document.paragraphs:
        _append_limited(parts, paragraph.text + "\n", max_chars)
    for table_index, table in enumerate(document.tables, start=1):
        _append_limited(parts, f"\n[Table {table_index}]\n", max_chars)
        for row in table.rows:
            _append_limited(parts, " | ".join(cell.text for cell in row.cells) + "\n", max_chars)
    return {"text": "".join(parts), "paragraphs": len(document.paragraphs),
            "tables": len(document.tables), "truncated": sum(map(len, parts)) >= max_chars}


def _extract_pptx(path: Path, max_pages: int, max_chars: int) -> dict[str, Any]:
    try:
        from pptx import Presentation
    except ImportError as exc:
        raise ToolExecutionError("Install the 'documents' extra to read PPTX files.") from exc
    presentation = Presentation(str(path))
    parts: list[str] = []
    slide_count = min(len(presentation.slides), max_pages)
    for index, slide in enumerate(presentation.slides[:slide_count], start=1):
        _append_limited(parts, f"\n[Slide {index}]\n", max_chars)
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False):
                _append_limited(parts, shape.text + "\n", max_chars)
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    _append_limited(
                        parts, " | ".join(cell.text for cell in row.cells) + "\n", max_chars
                    )
    return {"text": "".join(parts), "slides_processed": slide_count,
            "total_slides": len(presentation.slides),
            "truncated": len(presentation.slides) > slide_count or sum(map(len, parts)) >= max_chars}


def _cell_text(value: Any) -> str:
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if value is None:
        return ""
    return str(value)


def _extract_xlsx(path: Path, max_pages: int, max_chars: int) -> dict[str, Any]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise ToolExecutionError("Install the 'documents' extra to read XLSX files.") from exc
    workbook = load_workbook(path, read_only=True, data_only=True)
    parts: list[str] = []
    sheet_count = min(len(workbook.worksheets), max_pages)
    rows_processed = 0
    try:
        for worksheet in workbook.worksheets[:sheet_count]:
            _append_limited(parts, f"\n[Sheet {worksheet.title}]\n", max_chars)
            for row_index, row in enumerate(worksheet.iter_rows(values_only=True)):
                if row_index >= 2000:
                    _append_limited(parts, "[Row limit reached]\n", max_chars)
                    break
                rows_processed += 1
                _append_limited(
                    parts, " | ".join(_cell_text(value) for value in row) + "\n", max_chars
                )
                if sum(map(len, parts)) >= max_chars:
                    break
            if sum(map(len, parts)) >= max_chars:
                break
    finally:
        workbook.close()
    return {"text": "".join(parts), "sheets_processed": sheet_count,
            "total_sheets": len(workbook.sheetnames), "rows_processed": rows_processed,
            "truncated": len(workbook.worksheets) > sheet_count or sum(map(len, parts)) >= max_chars}


def _extract_text(root: Path, relative_path: str, max_file_bytes: int,
                  max_pages: int, max_chars: int) -> dict[str, Any]:
    path = _document_path(root, relative_path, max_file_bytes)
    if not 1 <= max_pages <= 100:
        raise ToolExecutionError("max_pages must be between 1 and 100.")
    if not 1 <= max_chars <= 200_000:
        raise ToolExecutionError("max_chars must be between 1 and 200000.")
    extension = path.suffix.casefold()
    if extension in {".txt", ".md"}:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ToolExecutionError("Text documents must use UTF-8 encoding.") from exc
        return {"path": relative_path, "format": extension[1:],
                "text": text[:max_chars], "truncated": len(text) > max_chars}
    if extension == ".pdf":
        result = _extract_pdf(path, max_pages, max_chars)
    elif extension == ".docx":
        result = _extract_docx(path, max_chars)
    elif extension == ".pptx":
        result = _extract_pptx(path, max_pages, max_chars)
    else:
        result = _extract_xlsx(path, max_pages, max_chars)
    return {"path": relative_path, "format": extension[1:], **result}


def _metadata(root: Path, relative_path: str, max_file_bytes: int) -> dict[str, Any]:
    path = _document_path(root, relative_path, max_file_bytes)
    stat = path.stat()
    return {
        "path": relative_path,
        "format": path.suffix.casefold()[1:],
        "size_bytes": stat.st_size,
        "modified_time": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(),
    }


def _list_documents(root: Path, relative_directory: str, limit: int) -> dict[str, Any]:
    if not 1 <= limit <= 500:
        raise ToolExecutionError("limit must be between 1 and 500.")
    directory = root if not relative_directory else (root / relative_directory).resolve()
    if not directory.is_relative_to(root) or not directory.is_dir():
        raise ToolExecutionError("Directory is invalid or escapes the configured root.")
    files = []
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.suffix.casefold() in _SUPPORTED:
            resolved = path.resolve()
            if resolved.is_relative_to(root):
                files.append({
                    "path": str(resolved.relative_to(root)),
                    "format": resolved.suffix.casefold()[1:],
                    "size_bytes": resolved.stat().st_size,
                })
                if len(files) >= limit:
                    break
    return {"files": files, "count": len(files), "limit": limit}


def create_document_tools(*, root_dir: str | Path,
                          max_file_bytes: int = 20_000_000,
                          max_output_chars: int = 50_000) -> tuple[FunctionTool, ...]:
    root = Path(root_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if not 1 <= max_file_bytes <= 200_000_000:
        raise ValueError("max_file_bytes must be between 1 byte and 200 MB.")
    if not 1 <= max_output_chars <= 200_000:
        raise ValueError("max_output_chars must be between 1 and 200000.")
    path_schema = {"path": {"type": "string", "minLength": 1, "maxLength": 500}}
    return (
        FunctionTool(
            "document.list_files",
            "List supported document files under a configured directory.",
            object_schema({
                "directory": {"type": "string", "maxLength": 500},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500},
            }),
            "document:read",
            lambda directory="", limit=100: _list_documents(root, directory, limit),
        ),
        FunctionTool(
            "document.get_metadata",
            "Get bounded metadata for a supported document file.",
            object_schema(path_schema, ["path"]),
            "document:read",
            lambda path: _metadata(root, path, max_file_bytes),
        ),
        FunctionTool(
            "document.extract_text",
            "Extract bounded text from UTF-8, PDF, DOCX, PPTX or XLSX files.",
            object_schema({
                **path_schema,
                "max_pages": {"type": "integer", "minimum": 1, "maximum": 100},
                "max_chars": {"type": "integer", "minimum": 1, "maximum": max_output_chars},
            }, ["path"]),
            "document:read",
            lambda path, max_pages=50, max_chars=max_output_chars: _extract_text(
                root, path, max_file_bytes, max_pages, max_chars
            ),
            timeout=60,
            output_limit=max_output_chars + 2000,
        ),
    )

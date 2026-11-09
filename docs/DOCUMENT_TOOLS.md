# Document Extraction Tools

The document pack provides bounded, read-only discovery, metadata and text extraction for common office formats.

## Installation

Install optional parsers:

```bash
pip install -e ".[documents]"
```

Then register the tools:

```python
engine.install_document_tools(
    root_dir="./workspace/documents",
    max_file_bytes=20_000_000,
    max_output_chars=50_000,
)
```

Available tools:
- `document.list_files` — list supported files under a configured directory.
- `document.get_metadata` — return file format, size and modification time.
- `document.extract_text` — extract text from UTF-8 TXT/Markdown, PDF, DOCX, PPTX and XLSX.

PDF pages and presentation slides are bounded by `max_pages`; extracted output is bounded by `max_chars`. XLSX extraction is read-only, uses cached cell values, and caps rows per sheet. The host also enforces file-size and tool-output limits.

## Not included yet

- OCR for scanned PDFs/images, layout/table reconstruction, handwriting recognition.
- Editing, signing, redaction, rendering and format conversion.
- XLS, ODT, ODS, RTF and other office formats.
- Semantic document indexing, chunking, embeddings and retrieval.
- Parser-level sandboxing. Treat complex/untrusted documents as hostile input and run parsers in a restricted worker for production use.

Optional parser behavior, malformed files, encrypted PDFs, large documents and Windows file handling remain on the deferred verification checklist.

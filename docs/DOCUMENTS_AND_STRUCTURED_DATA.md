# Document and Structured Data Tool Packs

ULTK provides two independently installable packs. Both are rooted in host-configured directories, enforce byte/row/output bounds, use separate read/write capabilities, and avoid executing model-supplied code.

## Installation

```bash
pip install -e ".[documents,structured-data]"
```

For legacy XLS and OpenDocument parsing:

```bash
pip install -e ".[documents-xls,documents-odf]"
```

## Document tools

Register with `engine.install_document_tools(root_dir="./workspace/documents")`.

| Tool | Capability | Purpose |
|---|---|---|
| `document.list_files` | `document:read` | Bounded discovery of supported files |
| `document.get_metadata` | `document:read` | Format, size and modification time |
| `document.extract_text` | `document:read` | Text extraction from TXT, Markdown, PDF, DOCX, PPTX, XLSX, XLS, ODT and ODS |
| `document.pdf_merge` | `document:write` | Merge bounded PDF inputs into a new file |
| `document.pdf_extract_pages` | `document:write` | Extract an inclusive PDF page range |

PDF/DOCX/PPTX/XLSX/ODF/XLS parsers are optional dependencies. OCR of scanned pages, handwriting recognition, layout-faithful conversion, editing/signing/redaction, and arbitrary format conversion are not provided by this pack.

## Structured-data tools

Register with `engine.install_structured_data_tools(root_dir="./workspace/data")`.

| Tool | Capability | Purpose |
|---|---|---|
| `data.read_table` | `data:read` | Read CSV, JSON, XML or XLSX into bounded row objects |
| `data.write_table` | `data:write` | Write bounded row objects to CSV, JSON, XML or XLSX |
| `data.transform` | `data:transform` | Apply safe declarative operations to supplied rows |
| `data.validate_table` | `data:read` | Validate required columns and primitive types |
| `data.etl_run` | `data:etl` | Read, transform and write a file-to-file ETL pipeline |

### Supported ETL operations

- `select`, `rename`, `filter` (eq/ne/gt/gte/lt/lte/contains/in/is_null/not_null)
- `sort`, `deduplicate`
- `derive` using constant/lower/upper/trim/coalesce/concat/add/subtract/multiply/divide
- `group_by` with count/sum/avg/min/max/first
- `join` with inner or left semantics and a second root-confined file

No Python, SQL, arbitrary expression, XPath or regex evaluation is exposed through ETL. Join inputs are read through the same bounded loader. CSV and XLSX exports escape formula-leading text values to reduce spreadsheet formula injection risk.

## Example

```python
from ultk.engine import ToolEngine
from ultk.permissions import AllowListPolicy

engine = ToolEngine(policy=AllowListPolicy({
    "document:read", "document:write",
    "data:read", "data:write", "data:transform", "data:etl",
}))
engine.install_document_tools(root_dir="./workspace/documents")
engine.install_structured_data_tools(root_dir="./workspace/data")
```

The application must still pass matching granted capabilities to execution. Installing a pack does not authorize its tools.

## Security and operational boundaries

- Paths are relative to a host-selected root and resolved before access; absolute paths and resolved traversal are rejected.
- Atomic file replacement is used for exports. Existing destinations are not overwritten unless the caller explicitly requests it.
- File bytes, row counts, columns, operation counts, output sizes and extracted characters/pages are bounded.
- XML DTD/entity declarations are rejected; defusedxml is used when installed.
- Spreadsheet formula-like strings are escaped on CSV/XLSX export. This is a safety transformation and may change the literal value.
- Parser libraries process complex attacker-controlled files. Path confinement and parser limits are not an OS sandbox. Run untrusted document parsing in a restricted worker/container with CPU, memory, filesystem and network limits.
- XLSX extraction uses cached values; formulas are not recalculated. Legacy XLS and ODT/ODS require their optional extras.
- XLSX/CSV values may be type-coerced by spreadsheet applications. Treat imported data as untrusted and validate it before business-critical use.
- The ETL engine is in-memory and bounded by configured rows/columns; it is not a distributed or streaming ETL engine.
- XML table convention: the root's direct child elements are records; each record's direct children become fields. Nested XML is represented only as text and is not a lossless round-trip format.
- PDF text extraction cannot recover text from image-only/scanned pages without a separate OCR pipeline.

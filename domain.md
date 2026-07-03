Domain layer implementation is complete. All four files compile, import cleanly, and include `__post_init__` invariant checks where the data contracts specify them.

---

## Models (`models.py`)

### Core document & indexing

| Model | Purpose |
|-------|---------|
| **`PDFDocument`** | Immutable PDF identity for a session: path, SHA-256 hash, page count, file size, and active profile. No page content — that comes from `PdfReader`. |
| **`TableTitle`** | Parsed regulatory heading anchor (e.g. `Table-5(a): Cross Subsidy Surcharge`) with normalized table number, title text, and optional provenance (page scan, TOC, FTS). |
| **`PageRecord`** | One indexed page: full text, detected titles, table flags, and lightweight metadata for discovery and search. |
| **`PageIndex`** | Full-PDF page index artifact: all `PageRecord`s plus workspace/hash metadata and rebuild versioning for cache invalidation. |
| **`TocEntry`** | Raw TOC line with embedded `TableTitle` and printed page number from front matter. |
| **`PageIndexResult`** | Index-stage return value: built `PageIndex` plus summary counts. |

### Discovery & user intent

| Model | Purpose |
|-------|---------|
| **`PageRange`** | Inclusive 1-based PDF page span for one parameter, with auditable source (`anchor_chain`, `user_confirmed`, etc.) and optional anchor titles. |
| **`ParameterDefinition`** | One discoverable parameter: ID, display name, anchor title, support flag, suggested range, and parser/routing hints. |
| **`ParameterCatalog`** | Full discovery output for one PDF: all parameters, counts, TOC offset calibration, and spurious-match audit trail. |
| **`UserSelection`** | Session checkpoint of user intent: which parameters to run, confirmed ranges, optional pattern overrides, and export preferences. |

### Extraction & normalization

| Model | Purpose |
|-------|---------|
| **`RawTable`** | Per-page unprocessed table from pdfplumber: string cell grid, dimensions, selected candidate index, and extraction warnings. |
| **`MergedTable`** | Multi-page concatenation after header stripping: merged rows, source pages, and merge audit log. |
| **`NormalizedTable`** | Geometry- and text-cleaned table ready for classification/parsing, with step trace and optional row labels. |
| **`StateBlock`** | Slice of a normalized matrix for one state/UT (cross-subsidy style): row range, block rows, pages, and parser hint. |

### Classification, parsing & validation

| Model | Purpose |
|-------|---------|
| **`PatternClassification`** | Classifier output: assigned `TablePattern`, confidence, routing source, feature signals, and low-confidence flags. |
| **`ParsedRecord`** | One semantic output row: flexible `fields` map (schema defined in parameter YAML) plus provenance. |
| **`ParseResult`** | Full parse output for one parameter: records, status (`success`/`partial`/`failed`), parser metadata, and errors. |
| **`ValidationCheck`** | Single rule outcome within a validation run. |
| **`ValidationReport`** | Post-parse quality gate: pass/fail, error/warning tallies, and per-check details. |

### Export & orchestration

| Model | Purpose |
|-------|---------|
| **`ExcelSheetInfo`** | Metadata for one Excel sheet: name, parameter, row count, columns. |
| **`ExcelWorkbook`** | Export deliverable envelope: path, sheets, workspace linkage, and formatting/validation summary. |
| **`StageRecord`** | One pipeline stage’s status in the manifest: completion time, artifact paths, input hash. |
| **`WorkspaceManifest`** | Root workspace index: embedded PDF, stage map, user selection, config hashes, invalidation state. |
| **`ExportResult`** | Export-stage return: `ExcelWorkbook` metadata. |
| **`PipelineResult`** | Pipeline run summary: updated manifest, processed parameters, export results. |

**Type alias:** `Scalar = str | int | float | bool` — allowed values in `ParsedRecord.fields`.

---

## Protocols (`protocols.py`)

| Protocol | Role |
|----------|------|
| **`PdfReader`** | PDF adapter contract: `page_count`, `extract_text(page)`, `extract_tables(page)`, context-manager lifecycle. Converts library types to `list[list[str]]` at the boundary. |
| **`ParserPlugin`** | Parser plugin contract: `parser_id`, `pattern`, and `parse(table, blocks, config) → ParseResult`. No PDF I/O. |
| **`PatternClassifier`** | Pattern scoring contract: `classify(table, config) → PatternClassification`. Must not invoke parsers. |
| **`ArtifactStore`** | Workspace persistence: `read(kind, parameter_id?)` and `write(kind, data, parameter_id?) → path`. Maps `ArtifactKind` to canonical paths. |
| **`ExcelExporter`** | Excel export: `export(sheets, path, format_config) → ExcelWorkbook`. Consumes tabular data only. |
| **`PageSearchIndex`** | FTS5 search: `query(text, limit) → list[int]` (1-based pages) and `build(page_index)`. |
| **`ValidationRule`** | Pluggable check: `rule_id` and `check(result, config) → ValidationReport`. Composed by the validation runner. |

All protocols are `@runtime_checkable` for isinstance checks in tests.

---

## Enums (`enums.py`)

| Enum | Values / purpose |
|------|------------------|
| **`TablePattern`** | Layout types for routing: `simple_flat`, `hierarchical_parent_child`, `continuation_rows`, `repeated_headers`, `multi_page`, `numeric_matrix`, `wide_table`, `state_block_matrix`, `simple_matrix`, `key_value`, `unknown`. |
| **`ParserFamily`** | Plugin families in registry: `narrative`, `numeric_matrix`, `wide_to_long`, `state_block_matrix`, `simple_matrix`, `key_value`. |
| **`ArtifactKind`** | Persisted artifact types: `manifest`, `page_index`, `parameter_catalog`, `raw_pages`, `records`, `excel`, etc. |
| **`SessionStage`** | Pipeline stages in manifest: `index` → `discover` → `select` → `extract` → `normalize` → `classify` → `parse` → `validate` → `export`. |
| **`StageStatus`** | Stage completion: `pending`, `complete`, `stale`, `failed`. |
| **`TitleSource`** | Title origin: `page_scan`, `toc`, `fts`. |
| **`PageRangeSource`** | Range provenance: `anchor_chain`, `toc_next_start`, `user_confirmed`, `user_override`, `query_resolved`. |
| **`SelectionMode`** | User selection mode: `catalog`, `query`, `batch`, `single`. |
| **`RowLabel`** | Normalization row class: `header`, `master`, `child`, `continuation`, `data`, `garbage`. |
| **`RoutingSource`** | Pattern routing: `config_override`, `classifier`, `user_confirmed`. |
| **`ParseStatus`** | Parse outcome: `success`, `partial`, `failed`. |
| **`BlockParserHint`** | Block parser suggestion: `matrix`, `simple_matrix`, `key_value`. |
| **`ExportMode`** | Excel packaging: `single_workbook`, `per_parameter`. |
| **`DiscoverySource`** | Parameter discovery: `toc`, `index`, `merged`. |
| **`ValidationSeverity`** | Check severity: `error`, `warning`, `info`. |

All enums are `str, Enum` for direct JSON serialization.

---

## Exceptions (`errors.py`)

| Exception | When raised |
|-----------|-------------|
| **`TableScraperError`** | Base for all pipeline errors; catch at CLI/API boundaries. |
| **`DiscoveryError`** | TOC extraction, catalog building, or page-range resolution fails. |
| **`ExtractionError`** | Raw table extraction from PDF fails. |
| **`NormalizationError`** | Geometry/text/hierarchy normalization fails. |
| **`PatternUnknownError`** | Classifier returns `unknown` with no override. |
| **`ParserNotFoundError`** | No registry plugin matches pattern or parameter. |
| **`ValidationError`** | Post-parse business rules fail with blocking errors (distinct from dataclass `ValueError`). |
| **`ConfigError`** | YAML loading or schema validation fails at startup. |
| **`WorkspaceError`** | Workspace lifecycle or artifact I/O fails. |

Dataclass invariant violations raise **`ValueError`** in `__post_init__` (structural checks); runtime pipeline failures use the hierarchy above.

---

## Validation highlights

Invariant checks enforced at construction time include:

- 64-char hex hashes on `PDFDocument` and `PageIndex`
- Contiguous pages `1..N` in `PageIndex`
- `TableTitle` pattern, non-empty title, TOC requires `printed_page`
- `ParameterCatalog` uniqueness, sort order, and count consistency
- `UserSelection` range coverage and query-mode requirements
- Table dimension consistency and all-string cells on table models
- `ParseResult` status/record/error consistency
- `ValidationReport` tally alignment with checks

Nothing outside `src/table_scraper/domain/` was modified. Recommended next step: `config/loader.py` and `storage/workspace.py`.
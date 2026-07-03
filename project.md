# Regulatory PDF Table Extraction Pipeline — Architecture Design Document

This document synthesizes the project specification from all materials in `docs/`: `Regulatory_Parameter_Extraction_Pipeline_Documentation.md`, `cross_subsidy_surcharge_scraping_pipeline.md`, `table_scraping.ipynb`, and `table_fetch (1).ipynb`. It describes intended architecture and design reasoning only — no implementation.

---

## 1. Overall Objective

The pipeline transforms a large, heterogeneous regulatory PDF (the CERC/URSI compliance report for power utilities — ~294 pages, mixed Hindi/English, OCR artifacts) into a **structured data warehouse** where each regulatory parameter is available as machine-readable records, ultimately exported to **Excel**.

The PDF contains dozens of regulatory tables spanning open access charges, tariff comparisons, return on equity, reliability of supply, green energy open access, and more. Tables differ radically in layout: narrative policy text, numeric matrices, wide voltage-level grids, and multi-level category matrices.

The pipeline must therefore be:

- **Parameter-driven** — each table family has its own schema and parser
- **Hierarchy-aware** — implicit parent/child relationships must be reconstructed
- **Multi-page capable** — tables span pages with repeated headers
- **OCR-tolerant** — handle `(cid:###)` artifacts without relying on image OCR as the primary path
- **Extensible** — new parameters added via configuration, not monolithic rewrites

---

## 2. Complete End-to-End Workflow (PDF → Excel)

```
┌─────────────────────────────────────────────────────────────────────────┐
│  INPUT: Regulatory PDF                                                  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  DISCOVERY LAYER                                                        │
│  • Build full-page index (text, table titles, metadata)                 │
│  • Extract TOC → parameter catalog → page ranges                        │
│  • Calibrate printed-page vs PDF-page offset                            │
│  • FTS5 / keyword search for section routing                            │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  USER / ROUTING LAYER                                                   │
│  • User selects parameter (from catalog or natural-language query)      │
│  • System resolves section start/end pages                              │
│  • Optional: user confirms/adjusts page range after preview             │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  EXTRACTION LAYER                                                       │
│  • pdfplumber: extract_tables() per page in range                       │
│  • Select largest table per page (rows × columns heuristic)             │
│  • Merge multi-page tables; strip repeated headers                      │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  NORMALIZATION LAYER                                                    │
│  • Structural cleanup (empty rows/columns)                              │
│  • OCR/text cleanup, English extraction, state canonicalization         │
│  • State propagation, hierarchy reconstruction                        │
│  • Wide → long normalization where needed                               │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  PARSING LAYER (parameter-specific)                                     │
│  • Route to parser family via Parameter Registry                        │
│  • Emit canonical records as List[Dictionary]                           │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  WAREHOUSE EXPORT                                                       │
│  • DataFrames → Excel workbook (one sheet per parameter)                │
│  • Post-export formatting (frozen headers, bold, column widths)         │
└─────────────────────────────────────────────────────────────────────────┘
```

Intermediate artifacts persist at each stage (JSON, CSV, SQLite) for inspection, debugging, and optional query/retrieval layers.

---

## 3. Every Major Phase of the Pipeline

The documentation describes evolution across **12+ phases**, grouped into logical stages:

### Stage A — Discovery & Indexing

| Phase | Name | Purpose |
|-------|------|---------|
| **1A** | TOC Parameter Discovery | Parse first ~15 pages; regex-match `TABLE-N(X): TITLE ... PAGE`; build `parameter_catalog.json` |
| **1B** | Page Range Computation | Sort catalog; infer end page from next parameter's start; output `parameter_ranges.json` |
| **1C** | Manual Page Verification | Preview first lines of discovered pages; confirm TOC correctness and detect offset |
| — | Page Offset Investigation | Search unique phrases (e.g. "Banking Charges") across all PDF pages to map printed page → PDF index |
| **2.3** (table_fetch) | Table-Title Indexing | Scan every page; detect table titles via regex; store in SQLite + CSV |
| — | FTS5 Search Index | Full-text search over page text and table titles for section routing |

### Stage B — Raw Extraction

| Phase | Name | Purpose |
|-------|------|---------|
| **2A** | Universal Parameter Family Extractor | Extract all tables from a page range; save raw JSON |
| **2B** | Table Shape Inspection | Compare row/column counts across detected tables per page |
| **2C** | Multi-Page Table Merge | Select largest table per page; skip repeated header rows; concatenate data rows |

### Stage C — Structural Normalization

| Phase | Name | Purpose |
|-------|------|---------|
| **3A** | State Propagation | Forward-fill blank state cells so child rows inherit state |
| **3B** | Row Classification | Classify rows as Master, Child, or Continuation |
| **3C** | Record Reconstruction | Build normalized DISCOM records with inheritance and policy append |
| **3D** | Group Discovery | Identify hidden state → utility hierarchies (e.g. Gujarat DISCOM groups) |
| **3E** | OCR Cleanup | Strip `(cid:###)`, normalize whitespace, extract English state names |
| **4** (table_fetch) | Geometry Normalization | Remove empty columns and completely empty rows (structural, not semantic) |
| **4.x** (table_fetch) | State Block Segmentation | Split open-access matrices into state-specific blocks using year pattern `20xx-xx` |

### Stage D — Parser Development & Production Hardening

| Phase | Name | Purpose |
|-------|------|---------|
| **4A** | Universal Narrative Parser | Reusable engine: extract → merge → propagate → classify → records |
| **5A** | Numeric Matrix Discovery | Identify transmission-style numeric hierarchy (state/utility × year/charges/units) |
| **6A–6E** | Generic Numeric Parser | Canonical state master; keyword-based header detection; payload inheritance |
| **7A–7B** | Production Banking Parser | Automatic repeated-header removal; OCR cleanup; garbage filtering |
| **8A–8C** | Universal Numeric Parser | Keyword header detector; parent detection via canonical states; child payload inheritance |
| **9A** | Schema Discovery Engine | `inspect_parameter_schema()` — column density analysis before writing parsers |
| **9B–9C** | Additional Surcharge Parser | State-only and state+utility record support |
| **10A–10B** | Wheeling Parser | Wide voltage columns → long-format records |

### Stage E — Export & Presentation

| Phase | Name | Purpose |
|-------|------|---------|
| **11** | Warehouse Export | All parsers → DataFrames → multi-sheet Excel (`Regulatory_Parameter_Warehouse.xlsx`) |
| **12** | Workbook Formatting | Frozen panes, bold headers, auto column width with clamp (max 60) |

### Stage F — Query & Retrieval (table_fetch track, primarily for Cross-Subsidy)

| Phase | Name | Purpose |
|-------|------|---------|
| **6.1–6.5** | Query Engine | State detection, keyword extraction, scoring, ranked search within state blocks |
| — | State Catalog | Map state name → block ID → normalized rows in `state_blocks_v2.json` |

---

## 4. Every Table Pattern Discovered

### From Regulatory Pipeline Documentation (Patterns 1–7)

| # | Pattern | Description |
|---|---------|-------------|
| **1** | Simple Flat Table | One row → one record; no hierarchy |
| **2** | Hierarchical Parent → Child | State parent with DISCOM children inheriting charge/period/policy |
| **3** | Continuation Rows | Policy text split across rows; append to previous record |
| **4** | Repeated Headers | Every page repeats table header; must detect and discard |
| **5** | Multi-Page Tables | Rows continue seamlessly across pages; merge before parsing |
| **6** | Numeric Matrix | Columns = measurements (year, charges, units); rows = state/utility hierarchy |
| **7** | Wide Tables | Multiple measurements in one row (e.g. voltage levels); normalize to long format |

### From Cross-Subsidy Documentation (Patterns A–E)

| Pattern | Description |
|---------|-------------|
| **A** | Section family with sub-tables — `Table-5: Open Access Charges` contains 5(a)–5(e) sub-parameters |
| **B** | State-based matrix rows — row starts with state, utility columns follow |
| **C** | Repeated category rows — HT, LT, EHT, Industrial, Domestic, Non-Domestic |
| **D** | Merged multi-row headers — top rows span multiple columns |
| **E** | State blocks — one state spans many rows and subcategories |

### From table_fetch Block-Level Detection

| Block Type | Detection Signal | Structure |
|------------|------------------|-----------|
| **matrix** | Header row starts with "Category"; single-column rows = section headers | Sections → categories → utility column values |
| **simple_matrix** | Header row starts with "Category"; no single-column section rows | Header columns + category data rows |
| **key_value** | No "Category" header pattern | Metric/value pairs, optionally grouped by utility |

---

## 5. Every Parser Family Described

### Primary Parser Families (table_scraping / Parameter Registry)

| Parser | Assigned Parameters | Input Pattern | Output Schema (representative) |
|--------|---------------------|---------------|-------------------------------|
| **Narrative Parser** | Banking Charges | Parent/child/continuation rows with DISCOM, charge, period, policy text | `{state, discom, charge, period, policy}` |
| **Numeric Parser** | Transmission Charge, Wheeling Charge (initially), Cross Subsidy Surcharge (registry) | State/utility rows with year + long/short term charges and units | `{state, utility, year, long_medium_charge, long_medium_unit, short_term_charge, short_term_unit}` |
| **Additional Surcharge Parser** | Additional Surcharge | State or utility rows with year + surcharge value; supports state-only and utility-specific | `{state, year, additional_surcharge}` (+ optional utility) |
| **Wheeling Parser** | Wheeling Charge | One utility row, multiple voltage columns | `{state, utility, year, voltage_level, wheeling_charge}` (wide → long) |

### Block-Level Parser Families (table_fetch / Cross-Subsidy track)

| Parser | Use Case | Output Structure |
|--------|----------|-----------------|
| **parse_matrix_state** | Complex open-access matrices with HT/LT sections and utility columns | `{state, start_page, parser_type: "matrix", sections: [{name, columns, rows}]}` |
| **parse_simple_matrix_state** | Flat category × utility column grids | `{state, columns, rows: [{category, col_values...}]}` |
| **parse_key_value_state** | Simpler metric/value layouts | `{state, utility, data: [{metric, value}]}` |
| **detect_parser_type** | Auto-routes block to correct parser | Returns `"matrix"`, `"simple_matrix"`, `"key_value"`, or `"unknown"` |

### Supporting / Orchestration Components

| Component | Role |
|-----------|------|
| **Parameter Registry (`PARAMETER_CONFIG`)** | Maps parameter name → `{parser, start_page, end_page}` |
| **`extract_parameter()`** | Generic orchestrator: raw extract → route to narrative or numeric parser |
| **`extract_parameter_family()`** | Earlier universal engine with inline narrative parsing stages |
| **`inspect_parameter_schema()`** | Pre-parser discovery tool: shape, column density, sample rows |
| **Query Engine (`run_query` / `answer_query`)** | Natural-language retrieval over structured state blocks |

---

## 6. Every Reusable Utility Mentioned

| Utility | Purpose |
|---------|---------|
| **`clean_text()` / `clean_pdf_text()`** | Strip whitespace, handle nulls, remove `(cid:###)` OCR artifacts |
| **`extract_english()`** | Extract English tokens from bilingual Hindi/English cells |
| **`extract_state_name()`** | Parse state from bilingual cell text; apply manual alias rules |
| **`normalize_state_name()`** | Normalize state string for matching |
| **`canonicalize_state()`** | Map aliases (Orissa→Odisha, JandK→J&K, etc.) to canonical form |
| **`canonical_states` (set/registry)** | Authoritative list of valid Indian states/UTs for parent detection |
| **`clean_state_text()`** | Banking-specific state cleanup with replacement dictionary |
| **`is_header_row()` / `is_numeric_header_row()`** | Keyword-pattern header detection (≥2 matches) |
| **`extract_raw_table()`** | Page-range extraction with largest-table selection |
| **`detect_tables()` / TABLE_REGEX** | Regex detection of `TABLE-N(X): Title` patterns in page text |
| **`normalize_table()`** | Remove empty columns and blank rows (geometry cleanup) |
| **`compress_row()`** | Strip empty cells from a row |
| **`find_state_name()` / `detect_state()`** | Identify state block starters via year regex + "/" bilingual split |
| **`get_section()` / `find_relevant_pages()`** | Compute page range from table-title anchor to next anchor |
| **`retrieve_state()`** | Lookup state block via state catalog |
| **`extract_keywords()` / `score_text()` / `normalize_text()`** | Query engine keyword extraction and ranking |
| **`inspect_parameter_schema()`** | Universal schema discovery before parser authoring |

### Intermediate Storage Formats

| Artifact | Role |
|----------|------|
| `parameter_catalog.json` | TOC-derived parameter → start page |
| `parameter_ranges.json` | Parameter → `{start_page, end_page}` |
| `page_index.csv` / `pdf_index.db` | Full PDF page index with FTS5 |
| `phase4_tables.json` / `phase4_normalized.json` | Raw and cleaned extracted tables |
| `state_blocks.json` / `state_blocks_v2.json` | State-segmented table blocks |
| `state_catalog.csv` | State name → block ID mapping |
| `Regulatory_Parameter_Warehouse.xlsx` | Final Excel warehouse |

---

## 7. Reasoning Behind Page Indexing Before Extraction

The documentation treats page indexing as a **prerequisite**, not an optimization. Key reasons:

1. **PDFs are not databases.** A 294-page PDF is an opaque container. Without an index, every extraction requires manually scanning pages.

2. **Table titles are anchors.** Patterns like `Table-5(a): Cross Subsidy Surcharge` uniquely identify section boundaries. Multiple titles can appear on one page (page 50 has both Cross Subsidy Surcharge and Open Access Charges).

3. **Section boundaries are inherited.** The Open Access family (Table-5 and sub-tables 5a–5e) spans pages 50–75. Indexing reveals this family structure and enables automatic page-range computation via anchor-to-anchor logic.

4. **Printed page ≠ PDF page index.** The TOC reports page 63 for Banking Charges, but the actual table starts at PDF page 64. Indexing plus phrase-search calibration prevents extracting wrong pages.

5. **Searchability.** FTS5 over the index turns the PDF into a queryable object — "cross subsidy surcharge" → pages 50–56, "banking charges" → pages 64–75.

6. **Debugging and validation.** Page previews (Phase 1C) catch TOC parsing errors (e.g. spurious match `DOMESTIC-3KW` at page 500).

7. **Routing without parsing.** The query layer can resolve "Extract Wheeling Charge" to `{section_start: 59, section_end: 61}` before any table extraction runs.

> Core principle (from cross-subsidy doc): *Do not parse the table blindly. First discover where the table is, what its title is, how its pages are distributed, and what structure it actually has.*

---

## 8. Why OCR Is Not the Primary Extraction Method

OCR was explored (OpenCV grid detection on rendered PDF pages at 200 DPI) but explicitly demoted to **fallback**:

| OCR Problems | Text/Table Path Advantages |
|--------------|---------------------------|
| Broken glyphs and wrong characters | Preserves embedded PDF text when available |
| Weak table boundaries, row misalignment | `pdfplumber` uses PDF vector structure |
| Merged-cell confusion | Table titles and page metadata remain accurate |
| Noise compounds across Hindi/English mix | Regex anchors and FTS5 search stay reliable |
| Hard to debug | Index + intermediate JSON/CSV artifacts are inspectable |

OCR remains appropriate only when:
- Text is embedded as images
- `extract_text()` / `extract_tables()` fails
- Pages are scanned rather than born-digital

The "post-OCR" terminology in the cross-subsidy doc refers to the pipeline path **after OCR experimentation was rejected** — i.e. the text-and-table route, not a pipeline that runs OCR first.

---

## 9. How Parameter Discovery Works

Parameter discovery operates through **two complementary mechanisms**:

### Mechanism 1 — TOC Parsing (Phases 1A–1B)

1. Extract text from first ~15 pages
2. Apply regex: `TABLE[- ]?\d+(?:\([A-Z]\))?\s*:\s*(.*?)\s+(\d+)`
3. Build catalog: `{parameter_name: {start_page: N}}`
4. Sort by start page; compute end page = next parameter's start − 1
5. Persist as `parameter_catalog.json` and `parameter_ranges.json`

Example discovered parameters include: Banking Charges (63 TOC / 64 PDF), Transmission (61/62), Wheeling (58/59), Additional Surcharge (56/57), Cross Subsidy Surcharge (49/50), plus ~25 others (RoE, Reliability, TOD, etc.).

### Mechanism 2 — Full-PDF Page Index (table_fetch)

1. Iterate every page; store `{page_number, page_text, table_titles, contains_table, text_length}`
2. Detect table titles via `TABLE[- ]?\d+(?:\([A-Z]\))?\s*:\s*[^\n]+`
3. Insert into SQLite with FTS5 virtual table
4. Build anchor list from pages with table titles
5. `get_section(start_page)` → pages from anchor until next anchor − 1
6. `find_relevant_pages(query)` → keyword match in catalog → section pages

### Calibration Layer

- Phase 1C previews discovered pages to verify content matches expected parameter
- Page offset investigation searches for unique uppercase phrases across all pages
- Reveals ~+1 offset between TOC printed numbers and PDF indices for the open-access block

### Schema Discovery (Phase 9A)

Before writing a parser, `inspect_parameter_schema()` extracts the largest merged table, reports shape, column density, and first 20 rows — enforcing the rule: *never parse before inspecting the schema*.

---

## 10. How User Interaction Should Work

The documentation implies the following interaction model (inferred from Phase 2.3 tests, query engine, and discovery phases):

```
Step 1: PDF Input
        User provides the regulatory PDF

Step 2: Automatic Indexing (background)
        System builds page index + TOC catalog
        No user action required

Step 3: TOC / Parameter Presentation
        User sees discovered parameters with page ranges
        Example: 30 parameters sorted by page

Step 4: Parameter Selection
        User selects one or more parameters to extract
        OR enters natural-language query:
          "Extract Cross Subsidy Surcharge"
          "Extract Banking Charges"

Step 5: Page Range Resolution & Confirmation
        System resolves section pages via index/search
        Returns: {matched_table, section_start, section_end, pages[]}
        User may preview page content (Phase 1C style) and confirm/adjust

Step 6: Extraction & Parsing
        System extracts, normalizes, and routes to correct parser family
        Progress/summary shown (record counts per parameter)

Step 7: Excel Output
        Multi-sheet workbook generated
        Optional: query within extracted data (cross-subsidy track)
```

For the cross-subsidy / open-access track, an additional retrieval mode exists:
- User queries: "Andhra Pradesh Railway Traction", "Delhi Non Domestic", "Goa HT Level"
- System detects state → extracts keywords → scores rows → returns ranked matches

---

## 11. Generic vs Parameter-Specific Components

### Generic and Reusable Across Future PDFs

| Component | Why Reusable |
|-----------|-------------|
| Full-page indexing + FTS5 search | Works on any PDF with searchable text |
| TOC regex discovery | Standard CERC table naming convention |
| Page range computation (anchor logic) | Generic section-boundary algorithm |
| Page offset calibration | Phrase search is PDF-agnostic |
| `extract_raw_table()` + largest-table heuristic | Universal pdfplumber extraction |
| Multi-page merge + header stripping | Common regulatory PDF pattern |
| `normalize_table()` (empty row/col removal) | Geometry cleanup, schema-agnostic |
| OCR/text utilities (`clean_text`, `extract_english`) | Any bilingual PDF with cid artifacts |
| Canonical state registry + `canonicalize_state()` | Stable across all Indian regulatory tables |
| State propagation / block segmentation | Common hierarchy pattern |
| `inspect_parameter_schema()` | Pre-parser discovery for any new parameter |
| Parameter Registry pattern | Configuration-driven routing |
| `List[Dictionary]` output contract | Uniform warehouse interface |
| Excel export + formatting (Phases 11–12) | Any parameter set with DataFrames |
| Query engine framework (state detect, keyword score) | Reusable with different vocabularies |

### Parameter-Specific (Configuration + Parser Logic)

| Component | Varies By Parameter |
|-----------|---------------------|
| Page ranges in `PARAMETER_CONFIG` | Each parameter occupies different pages |
| Parser family assignment | Narrative vs numeric vs wheeling vs surcharge vs matrix |
| Column index mappings | e.g. Wheeling `WHEELING_COLS` voltage → column positions |
| Header keyword patterns | Banking headers ≠ transmission headers |
| Row classification rules | Master/child/continuation vs state/utility vs category/section |
| Wide → long expansion rules | Wheeling voltages; potentially other wide tables |
| Output schema / Excel sheet columns | Each parameter has distinct fields |
| Block-level parser type detection | Cross-subsidy matrices need matrix/simple_matrix/key_value routing |
| Query vocabulary / stop words | Domain-specific (HT, LT, Railway Traction, etc.) |

---

## 12. Ambiguities, Missing Requirements, and Design Decisions to Clarify

### Architectural Divergence

1. **Two parallel tracks exist.** `table_scraping.ipynb` uses a Parameter Registry with narrative/numeric parsers and Excel export. `table_fetch (1).ipynb` uses state-block segmentation with matrix/simple_matrix/key_value parsers and a query engine. **Decision needed:** Are these merged into one pipeline, or does cross-subsidy remain a separate sub-pipeline?

2. **Cross Subsidy Surcharge parser mismatch.** It is registered as `"numeric"` in `PARAMETER_CONFIG` but the table_fetch track treats it as a complex matrix requiring block-level parsers. It is also **absent from the Phase 11 Excel export** (only Banking, Transmission, Additional Surcharge, Wheeling are exported). **Decision needed:** Which parser family and output schema apply to CSS?

### Page Numbering

3. **TOC page vs PDF index vs printed page.** Three numbering systems appear (TOC says 63, PDF index is 64, Phase 1C preview at "page 49" shows Table-3/4 cross-subsidy trend content). **Decision needed:** Canonical page reference throughout the pipeline and automatic offset correction strategy.

4. **Section end boundaries.** `get_section()` uses next table-title anchor; TOC uses next parameter start. These can disagree (e.g. Banking ends at 75 by anchor logic but may include continuation pages). **Decision needed:** Which boundary rule is authoritative?

### Scope

5. **Which parameters are in v1?** TOC discovers ~30 parameters; only ~5 are fully parsed and 4 exported. **Decision needed:** Priority list for production v1 (Open Access family only? All 30?).

6. **Query engine scope.** The query engine is built and tested for cross-subsidy state blocks but is not connected to the Excel warehouse path. **Decision needed:** Is post-export querying in scope, or is Excel the sole deliverable?

### Parser Design

7. **Fixed column indices vs dynamic discovery.** Production parsers hardcode column positions (e.g. `LONG_COL = 6`, `WHEELING_COLS`). Schema inspection exists but is manual. **Decision needed:** Auto-detect columns from header rows, or maintain per-parameter column maps in config?

8. **Header row skip counts.** Banking skips first 4 rows; numeric skips 5; wheeling skips 7. These are magic numbers from exploration. **Decision needed:** Replace with keyword-based header detection everywhere (as Phase 7A/8A started)?

9. **Utility vs state disambiguation.** Additional Surcharge V2 shows Delhi utilities (BRPL, BYPL, TPDDL) parsed as states when canonical matching fails. **Decision needed:** Explicit utility registry separate from state registry?

### Data Quality

10. **OCR fallback trigger.** No specification defines when to switch from pdfplumber to OCR/image path. **Decision needed:** Failure criteria and fallback orchestration.

11. **Validation / audit requirements.** Documentation mentions "validate outputs continuously with audits and previews" but no acceptance criteria (expected record counts, state coverage, null rates). **Decision needed:** Validation rules per parameter.

12. **Multi-PDF support.** All notebooks hardcode one PDF path. **Decision needed:** Is the pipeline single-document or must it generalize to future regulatory PDF editions?

### User Interface

13. **UI modality unspecified.** Notebooks imply CLI/JSON interaction; no web UI, CLI spec, or API contract is defined. **Decision needed:** Interaction surface for production (CLI, web app, notebook, API).

14. **Page selection override.** Phase 1C is manual verification in a notebook. **Decision needed:** Should users always confirm page ranges, or trust automatic discovery?

### Storage

15. **Intermediate artifact lifecycle.** Multiple JSON/CSV/SQLite files accumulate. **Decision needed:** Which artifacts are persisted vs ephemeral; caching strategy when re-running on same PDF.

---

## Summary

The intended production pipeline is a **modular, configuration-driven ETL system** that indexes the PDF before touching table data, routes each regulatory parameter to an appropriate parser family based on structural patterns, normalizes implicit hierarchies and OCR artifacts, and exports a multi-sheet Excel warehouse. The cross-subsidy work adds a deeper matrix-parsing and query-retrieval layer for the most complex open-access tables.

The documentation is rich in exploratory evolution and working prototypes but leaves key consolidation decisions — especially around cross-subsidy parsing, page numbering, v1 scope, and the two parallel architectural tracks — to be resolved before implementation begins.
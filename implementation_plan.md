# Production Quality Roadmap — Regulatory PDF Table Extraction Pipeline

## Executive Summary

The pipeline infrastructure is solid — discovery, extraction, normalization, classification, parsing, and export all function correctly as an end-to-end system. The **architecture, data contracts, and module separation are well-designed**.

However, the **generated Excel output is severely degraded** compared to the source PDF. The root cause is not a single bug but a **systemic failure at the semantic parsing layer**: the `state_block_matrix` parser does not understand the multi-level header structure of these tables, and the block segmentation treats consumer categories as states. Every downstream output inherits this confusion.

This review covers **every stage**, identifies **every issue** with root cause analysis, and provides a **minimal implementation roadmap** to achieve production-grade output.

---

## Current Output Quality Assessment

| Parameter | Records | Expected | Verdict | Severity |
|-----------|---------|----------|---------|----------|
| Cross Subsidy Surcharge | 516 | ~500+ | Quantity OK, **semantics catastrophically wrong** | 🔴 CRITICAL |
| Additional Surcharge | **0** | ~40+ | **Complete failure — zero records** | 🔴 CRITICAL |
| Transmission Charge | **0** | ~28+ | **Complete failure — zero records** | 🔴 CRITICAL |
| Wheeling Charge | 37 | ~200+ | **95% data loss**, wrong columns | 🔴 CRITICAL |
| Banking Charges | **1** | ~35+ | **99% data loss** | 🔴 CRITICAL |

> [!CAUTION]
> 4 of 5 parameters produce zero or near-zero records. The one parameter with records (Cross Subsidy Surcharge) has **every semantic field wrong** — states contain consumer categories, utilities are column indices, consumer_category is 99.6% empty, year is 98% empty.

---

## Detailed Issue Catalog

### STAGE 1: Discovery

Discovery works correctly. No issues found.

- ✅ TOC extraction correct
- ✅ Page offset calibration works (`delta = -13`)
- ✅ Page ranges correctly resolved
- ✅ 5 parameters discovered and cataloged

---

### STAGE 2: Extraction

Extraction is functional but has edge issues.

- ✅ Tables extracted from correct pages
- ✅ Multi-page merge works
- ⚠️ Header stripping may be incomplete for some parameters

---

### STAGE 3: Normalization (Geometry + Text Cleanup)

| # | Issue | Root Cause | Impact | Severity |
|---|-------|-----------|--------|----------|
| N1 | Cross Subsidy table has 20 columns but only ~10 contain data; ~10 are empty | pdfplumber splits merged cells into multiple columns; geometry normalization does not collapse columns that share merged header spans | Inflated column count confuses parser column-index mapping; utility names become "Col 3", "Col 6", "Col 9" | 🟠 HIGH |
| N2 | Only 1 header row detected for CSS despite the PDF having 3+ header rows (State, Year, Utility sub-headers) | `hierarchy.py` defaults `header_rows_count = 1`; no config override is used | Parser cannot determine which columns belong to which utility (APSPDCL, APEPDCL, APCPDCL) | 🔴 CRITICAL |
| N3 | State names like "HT I(B) Townships" are treated as states | Block segmentation uses `state_col = 0` which holds consumer categories in some tables; the actual state row structure ("Andhra Pradesh" as a spanning header row) is not recognized | Consumer categories become `state`, actual state is lost | 🔴 CRITICAL |

**Files affected:** [hierarchy.py](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/src/table_scraper/normalization/hierarchy.py), [block_segmentation.py](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/src/table_scraper/normalization/block_segmentation.py)

---

### STAGE 4: Block Segmentation

| # | Issue | Root Cause | Impact | Severity |
|---|-------|-----------|--------|----------|
| B1 | CSS produces **277 blocks** when it should produce **~25 state blocks** | Segmentation splits on every row where `state_col` (col 0) changes value; since col 0 contains consumer categories (HT-I, HT-II, etc.), every category row starts a new "block" | Each consumer category becomes a 1-row "state block" with wrong state name | 🔴 CRITICAL |
| B2 | No multi-row state detection | The segmentation doesn't understand that "Andhra Pradesh" spans as a section header followed by "Category" row, then data rows; it only looks at `state_col = 0` | State hierarchy is lost | 🔴 CRITICAL |
| B3 | Year detection misses table-level years | `year_label` is `null` for 508/516 CSS records because the year ("2026-27") appears in header rows, not in data rows within blocks | Year field almost entirely empty | 🟠 HIGH |
| B4 | `utility_columns` always empty for CSS | No utility names found in data rows because utilities are in header rows; catalog matching fails | No utility identification | 🟠 HIGH |

**Files affected:** [block_segmentation.py](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/src/table_scraper/normalization/block_segmentation.py)

---

### STAGE 5: Pattern Classification

| # | Issue | Root Cause | Impact | Severity |
|---|-------|-----------|--------|----------|
| P1 | All 5 parameters routed to `state_block_matrix` parser | Classifier correctly identifies state-block features; however the **registry config assigns wrong parsers** and the classifier overrides are not used for parameters that need different families | Transmission and Additional Surcharge need `numeric_matrix`; Banking needs `narrative`; but all get `state_block_matrix` at runtime | 🔴 CRITICAL |
| P2 | Config says `banking_charges → narrative_v1`, `transmission → numeric_matrix_v1` but actual records show `parser_id: state_block_matrix_v1` | The classifier auto-routes to `state_block_matrix` overriding registry config because `routing_source: classifier` takes precedence | Parameters with registry-assigned parsers still get auto-classified to wrong family | 🔴 CRITICAL |

**Root cause detail:** In [router.py](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/src/table_scraper/parsing/router.py), the classifier result takes precedence over the registry config for all parameters except `cross_subsidy_surcharge` (which has `force_pattern` in its YAML). The other 4 parameters don't have `force_pattern`, so the classifier wins.

**Files affected:** [router.py](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/src/table_scraper/parsing/router.py), [registry.yaml](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/config/parsers/registry.yaml), parameter YAML files

---

### STAGE 6: Parsing (State Block Matrix Parser)

| # | Issue | Root Cause | Impact | Severity |
|---|-------|-----------|--------|----------|
| PA1 | **state field contains consumer categories**, not states | Parser reads `b.state` from blocks which are segmented on consumer categories, not states | Every record's state is wrong (e.g., "HT I(B) Townships" instead of "Andhra Pradesh") | 🔴 CRITICAL |
| PA2 | **utility field shows "Col 3", "Col 6", "Col 9"** | Parser falls back to `f"Col {col_idx}"` because `headers` are reconstructed from only 1 header row, which is empty for most columns | No utility identification; APSPDCL, APEPDCL become "Col N" | 🔴 CRITICAL |
| PA3 | **consumer_category is 99.6% empty** | Parser reads `row[1]` as category, but since blocks are 1-row each and col 1 is usually empty in data rows, nothing populates | Complete loss of category semantics | 🔴 CRITICAL |
| PA4 | **year_label is 98% empty** | Year comes from `b.year_label` which block segmentation failed to detect (years in header rows) | Missing temporal dimension | 🔴 CRITICAL |
| PA5 | `charge_unit` hardcoded to "Rs/kWh" | No unit detection from headers; parser assumes Rs/kWh for everything | Wrong for parameters using paise/kWh, %, or Rs/MW/day | 🟠 HIGH |
| PA6 | Utility name matching fails silently | `try/except` swallows all errors in catalog utility lookup; even when it works, matching "Col 3" against utility catalog finds nothing | Graceful degradation that hides failures | 🟡 MEDIUM |
| PA7 | `confidence` always 1.0 | No actual confidence assessment; even records with "Col 3" as utility get confidence 1.0 | Misleading quality signal | 🟡 MEDIUM |
| PA8 | Transmission & Additional Surcharge emit 0 records | State block parser finds blocks but `parse_float` returns `None` for every cell because the entity recognizer classifies numeric values as years/voltages/states | Complete data loss for 2 parameters | 🔴 CRITICAL |
| PA9 | Banking Charges emits 1 record from 67 rows and 36 blocks | Narrative-style text data doesn't match numeric parsing; only 1 numeric cell in Karnataka block passes `parse_float` | 97% data loss | 🔴 CRITICAL |
| PA10 | `parse_float` uses stack frame inspection (`inspect.stack()`) to find row/col indices | Extremely fragile; depends on local variable names in calling code; breaks if refactored | Unreliable value extraction | 🟠 HIGH |
| PA11 | Wheeling: 37 records from 80 blocks and 131 rows | Most states missing; only Haryana, Jharkhand, Karnataka, MP survive | ~85% data loss | 🔴 CRITICAL |
| PA12 | Year "2026-27" appears as a utility value | The year string appears in a utility column and is picked up as a utility name instead of being filtered | Wrong field assignment | 🟠 HIGH |
| PA13 | Voltage level detection only checks consumer category text | If category doesn't contain "HT"/"LT"/"EHT", voltage defaults to "all"; actual voltage levels from headers (11kV, 33kV, etc.) are ignored | Incomplete voltage classification | 🟡 MEDIUM |

**Files affected:** [state_block_matrix.py](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/src/table_scraper/parsing/families/state_block_matrix.py), [base.py](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/src/table_scraper/parsing/base.py)

---

### STAGE 7: Validation

| # | Issue | Root Cause | Impact | Severity |
|---|-------|-----------|--------|----------|
| V1 | Validation passes even when 0 records emitted | No `min_records` check enforced at runtime (only in YAML, not in `runner.py`) | Empty sheets exported without warning | 🔴 CRITICAL |
| V2 | State validation warns but doesn't block | 193 unique "states" in CSS (most are consumer categories) pass validation because severity is WARNING not ERROR | Invalid data exported | 🟠 HIGH |
| V3 | No column completeness check | Validation doesn't check if critical columns like `utility`, `year`, `consumer_category` are populated | 99% null rate on critical fields passes validation | 🟠 HIGH |
| V4 | No `export_allowed = false` path exercised | `export_allowed` is set to `passed` which only checks ERROR-severity failures; since most rules are WARNINGS, export always proceeds | No quality gate | 🟠 HIGH |

**Files affected:** [runner.py](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/src/table_scraper/validation/runner.py)

---

### STAGE 8: Excel Export

| # | Issue | Root Cause | Impact | Severity |
|---|-------|-----------|--------|----------|
| E1 | **2 sheets are completely empty** (Additional Surcharge, Transmission) | 0 records → empty DataFrame → single-cell sheet with `None` | Analyst sees blank sheet | 🔴 CRITICAL |
| E2 | Banking Charges has 1 row of data | Near-zero extraction | Useless for analysis | 🔴 CRITICAL |
| E3 | Column names are generic parser field names, not analyst-friendly | `charge_unit`, `charge_value`, `consumer_subcategory`, `effective_date` — not descriptive; no human-readable headers | Poor readability | 🟡 MEDIUM |
| E4 | Column ordering doesn't match schema config | Schema says `[state, category, utility, value]` but actual columns are `[charge_unit, charge_value, consumer_category, ...]` | Schema ignored in practice | 🟡 MEDIUM |
| E5 | `record_id`, `parameter_id` columns exported | Internal audit columns in analyst-facing workbook | Unnecessary clutter | 🟡 MEDIUM |
| E6 | No summary sheet | No overview of what's in the workbook, quality metrics, source info | Missing context | 🟡 MEDIUM |
| E7 | No conditional formatting for confidence | All values show confidence 1.0 anyway, but even if they didn't, no visual highlighting | Missing quality signals | 🟡 MEDIUM |
| E8 | No autofilters enabled | Excel autofilters not applied on header row | Reduced usability | 🟡 MEDIUM |
| E9 | Sheet names are `parameter_id` (snake_case), not display names | "cross_subsidy_surcharge" instead of "Cross Subsidy Surcharge" | Poor presentation | 🟡 MEDIUM |
| E10 | No `source_pages` column exported | Source PDF page reference lost in export | Missing traceability | 🟡 MEDIUM |
| E11 | No Cross_Subsidy_By_State.xlsx workbook generated | Feature not implemented | Missing analyst deliverable | 🟠 HIGH |
| E12 | `year_label` column present for some parameters but not others | Inconsistent record fields across parameters | Column inconsistency | 🟡 MEDIUM |

**Files affected:** [excel_exporter.py](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/src/table_scraper/export/excel_exporter.py), [dataframe_builder.py](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/src/table_scraper/export/dataframe_builder.py), [formatter.py](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/src/table_scraper/export/formatter.py), [export_stage.py](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/src/table_scraper/pipeline/stages/export_stage.py)

---

### CROSS-CUTTING: Generalization Issues

| # | Issue | Root Cause | Impact | Severity |
|---|-------|-----------|--------|----------|
| G1 | `header_rows_count` defaults to 1; no per-parameter configuration is used | `hierarchy.py` reads from config but no parameter YAML specifies `header_rows` | All multi-row headers treated as single-row | 🟠 HIGH |
| G2 | `state_column` defaults to 0; not configurable per parameter | Same default for all parameters regardless of actual table structure | Wrong column used for state detection in some tables | 🟠 HIGH |
| G3 | `charge_unit` hardcoded as "Rs/kWh" in parser | No config-driven unit extraction | Wrong units for some parameters | 🟠 HIGH |
| G4 | Parser routing doesn't honor `registry.yaml` `parser_id` mappings | Classifier output overrides registry; only `force_pattern` prevents this | Configuration-driven routing broken | 🔴 CRITICAL |
| G5 | No per-table header-to-column mapping | Parser guesses column semantics from position; no YAML-driven column index map | Fragile when table structure changes | 🟠 HIGH |

---

## Root Cause Synthesis

The **five systemic root causes** behind all issues:

1. **Multi-row header blindness**: The pipeline treats all tables as having 1 header row. CSS has 3+ header rows (State + Year + Utility headers). This cascades into wrong column identification, wrong utility names, and wrong year extraction.

2. **Block segmentation misidentification**: Block segmentation uses `col[0]` as the state column universally. In CSS, col[0] contains consumer categories, not states. The actual states appear as spanning rows that the segmenter doesn't understand.

3. **Parser routing ignores config**: The classifier always overrides registry-assigned parsers. Transmission, Additional Surcharge, and Banking need their own parser families but get forced into `state_block_matrix`.

4. **Header-aware column semantics missing**: The `HeaderAnalyzer` and `MetadataAnnotator` exist in the `understanding/` module but are **not wired into the parse stage**. The parser reconstructs headers on its own, badly.

5. **Validation is toothless**: No min-record check enforced, no column completeness check, WARNING severity never blocks export. Empty and garbage sheets are exported.

---

## Implementation Roadmap

### Phase 1: Core Semantic Engine (CRITICAL)

**Purpose:** Fix the fundamental semantic extraction failures that cause 99%+ of data quality issues.

**Capabilities added:**
- Multi-row header detection and column semantic mapping
- State-section aware block segmentation (spanning header rows)
- Header-driven utility identification (no more "Col N")
- Year extraction from header rows
- Parser routing respects config before classifier

**Files affected:**
- [block_segmentation.py](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/src/table_scraper/normalization/block_segmentation.py) — Complete rewrite for state-section awareness
- [hierarchy.py](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/src/table_scraper/normalization/hierarchy.py) — Multi-row header support from config
- [state_block_matrix.py](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/src/table_scraper/parsing/families/state_block_matrix.py) — Use header tree for utility/year/unit resolution
- [router.py](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/src/table_scraper/parsing/router.py) — Config `parser_id` takes precedence over classifier
- [base.py](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/src/table_scraper/parsing/base.py) — Remove `inspect.stack()` hack from `parse_float`
- [parse_stage.py](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/src/table_scraper/pipeline/stages/parse_stage.py) — Wire header analyzer into parse flow
- Parameter YAML files — Add `header_rows`, `state_column`, `data_start_row`, `column_map` per parameter
- [cross_subsidy_surcharge.yaml](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/config/parsers/parameters/cross_subsidy_surcharge.yaml) — Full column mapping
- [transmission_charge.yaml](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/config/parsers/parameters/transmission_charge.yaml) — `force_pattern: numeric_matrix`
- [banking_charges.yaml](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/config/parsers/parameters/banking_charges.yaml) — `force_pattern: narrative`
- [additional_surcharge.yaml](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/config/parsers/parameters/additional_surcharge.yaml) — `force_pattern: numeric_matrix`
- [wheeling_charge.yaml](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/config/parsers/parameters/wheeling_charge.yaml) — `force_pattern: wide_to_long`

**Dependencies:** None  
**Estimated complexity:** HIGH  
**Risk level:** HIGH (foundational change)  
**Expected improvements:**
- All 5 parameters produce correct records
- States, utilities, categories, voltages, years correctly identified
- Record count moves from 517 total → 1000+ correct records

---

### Phase 2: Parameter-Specific Parser Tuning (HIGH)

**Purpose:** Ensure each parser family actually works for its assigned parameter with correct column mappings and value extraction.

**Capabilities added:**
- Narrative parser for Banking Charges (text policy descriptions → structured records)
- Numeric matrix parser for Transmission Charge (state × year matrix → long-form records)
- Numeric matrix parser for Additional Surcharge (state × year × utility matrix)
- Wide-to-long parser for Wheeling Charge (voltage level as pivot dimension)
- Dynamic unit extraction from headers (Rs/kWh, paise/kWh, Rs/MW/day, %, etc.)

**Files affected:**
- [narrative.py](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/src/table_scraper/parsing/families/narrative.py) — Tune for banking charges text patterns
- [numeric_matrix.py](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/src/table_scraper/parsing/families/numeric_matrix.py) — State-header-aware matrix parsing
- [wide_to_long.py](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/src/table_scraper/parsing/families/wide_to_long.py) — Voltage-dimension pivot
- [simple_matrix.py](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/src/table_scraper/parsing/families/simple_matrix.py) — Optional fallback parser
- [key_value.py](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/src/table_scraper/parsing/families/key_value.py) — Optional fallback parser

**Dependencies:** Phase 1 (header semantics must work first)  
**Estimated complexity:** HIGH  
**Risk level:** MEDIUM  
**Expected improvements:**
- Banking Charges: 35+ structured records with policy text
- Transmission Charge: 28+ records with long/medium/short-term charges
- Additional Surcharge: 40+ records with per-state values
- Wheeling Charge: 200+ records with voltage-level breakdown

---

### Phase 3: Validation & Quality Gate (MEDIUM)

**Purpose:** Ensure no garbage data reaches the Excel output.

**Capabilities added:**
- Enforced `min_records` check (ERROR severity, blocks export)
- Column completeness validation (state, utility, year must be populated)
- Per-column null rate thresholds
- State coverage validation (minimum 20+ canonical states)
- Confidence recalibration (not always 1.0)

**Files affected:**
- [runner.py](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/src/table_scraper/validation/runner.py) — Add min_records, column completeness, state coverage rules
- [base.py](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/src/table_scraper/validation/rules/base.py) — New validation rule implementations
- Parameter YAML files — Add validation thresholds per parameter

**Dependencies:** Phase 1  
**Estimated complexity:** MEDIUM  
**Risk level:** LOW  
**Expected improvements:**
- Empty/garbage sheets blocked from export
- Quality metrics reported per parameter
- Confidence values reflect actual extraction quality

---

### Phase 4: Excel Presentation & Cross_Subsidy_By_State Workbook (HIGH)

**Purpose:** Produce analyst-friendly, publication-ready Excel output.

**Capabilities added:**
- Human-readable column names (configured per parameter YAML)
- Schema-driven column ordering
- Hide internal columns (record_id, parameter_id)
- Summary sheet with quality dashboard
- Conditional formatting for confidence
- Autofilters on all data sheets
- Source pages column
- Display-name sheet names
- **New `Cross_Subsidy_By_State.xlsx` workbook** with one sheet per state
- Cross-subsidy state sheets: Utility → Category → Voltage → Charge → Unit → Year → Notes → Confidence → Source Pages

**Files affected:**
- [dataframe_builder.py](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/src/table_scraper/export/dataframe_builder.py) — Column renaming, ordering, metadata column control
- [excel_exporter.py](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/src/table_scraper/export/excel_exporter.py) — Summary sheet, multi-workbook export
- [formatter.py](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/src/table_scraper/export/formatter.py) — Autofilters, conditional formatting, number formatting
- [export_stage.py](file:///c:/Users/hp/OneDrive/Desktop/TLG/table_scraper/src/table_scraper/pipeline/stages/export_stage.py) — Cross_Subsidy_By_State export flow
- Parameter YAML files — Column display names, export column lists

**Dependencies:** Phase 1 + Phase 2 (need correct data to export)  
**Estimated complexity:** MEDIUM  
**Risk level:** LOW  
**Expected improvements:**
- Publication-ready Excel workbooks
- Cross Subsidy data organized per-state for regulatory analysts
- Quality dashboard at a glance

---

## TODO Checklist

### Phase 1: Core Semantic Engine

- [ ] **1.1** Add `force_pattern` to all 5 parameter YAML files, matching their registry `parser_id` assignments
  - `transmission_charge.yaml` → `force_pattern: numeric_matrix`
  - `banking_charges.yaml` → `force_pattern: narrative` (or keep state_block but with different handling)
  - `additional_surcharge.yaml` → `force_pattern: numeric_matrix`
  - `wheeling_charge.yaml` → `force_pattern: wide_to_long`

- [ ] **1.2** Fix `router.py` to use config `parser_id` / `force_pattern` as first priority, classifier as fallback only when no config override exists

- [ ] **1.3** Extend all parameter YAML files with structural metadata:
  ```yaml
  table_structure:
    header_rows: 3          # Number of header rows
    state_column: 1         # Column index containing state names
    state_row_type: spanning # "spanning" (CSS) or "column" (default)
    data_start_row: 3       # First data row after headers
    category_column: 0      # Column containing consumer categories
  ```

- [ ] **1.4** Rewrite `block_segmentation.py` to support two segmentation modes:
  - **Column-based** (default): current behavior for simple state-per-row tables
  - **Spanning-header**: detect state names that appear as full-width rows, followed by sub-header rows and data rows; all rows between two state headers belong to that state's block

- [ ] **1.5** Update `hierarchy.py` to use `header_rows` from parameter config instead of defaulting to 1

- [ ] **1.6** Wire `HeaderAnalyzer` from `understanding/header_analyzer.py` into `parse_stage.py`:
  - After normalization, run `HeaderAnalyzer.detect_header_depth()`, `build_header_tree()`, and `resolve_column_semantics()`
  - Pass the resulting `ColumnDescriptor` list and `HeaderTree` into the parser

- [ ] **1.7** Rewrite `state_block_matrix.py` to use `ColumnDescriptor` for:
  - Utility names from header tree (not "Col N")
  - Year from header tree (not only block-level search)
  - Unit from column descriptors (not hardcoded "Rs/kWh")
  - Category from the correct column (not `row[1]` blindly)
  - State from block `state` field (which now correctly comes from spanning headers)

- [ ] **1.8** Remove `inspect.stack()` hack from `parse_float` in `base.py`; replace with explicit column descriptor context passed as argument

- [ ] **1.9** Fix `parse_float` to accept a `ColumnDescriptor` or `CellAnnotation` object instead of relying on global state (`_active_annotated_table`)

- [ ] **1.10** Re-run pipeline for cross_subsidy_surcharge and verify:
  - States are actual Indian states (Andhra Pradesh, Gujarat, etc.)
  - Utilities are actual DISCOM names (APSPDCL, APEPDCL, etc.)
  - Consumer categories populated (HT-I, HT-II, etc.)
  - Year populated ("2026-27")
  - Charge values correct

### Phase 2: Parameter-Specific Parser Tuning

- [ ] **2.1** Tune `numeric_matrix.py` for Transmission Charge:
  - Read state from state-column (col 0 or 1)
  - Read utility from sub-header row
  - Read year columns from header tree
  - Extract long-term/medium-term and short-term charge pairs

- [ ] **2.2** Tune `numeric_matrix.py` for Additional Surcharge:
  - State-per-row layout
  - Multiple year columns
  - Extract per-utility surcharge values

- [ ] **2.3** Decide on Banking Charges parser approach:
  - Option A: Use `narrative.py` to extract text-based policy descriptions
  - Option B: Use `state_block_matrix.py` with proper column mapping for the mixed text+numeric layout
  - Implement chosen approach

- [ ] **2.4** Tune `wide_to_long.py` for Wheeling Charge:
  - Voltage level as the pivot dimension
  - Multiple year columns
  - Per-utility charge extraction

- [ ] **2.5** Add proper unit extraction from header text:
  - Parse "Rs/kWh", "paise/kWh", "Rs/kW/Month", "%" from column headers
  - Store in `charge_unit` field per record

- [ ] **2.6** Verify all 5 parameters produce correct record counts by re-running full pipeline

### Phase 3: Validation & Quality Gate

- [ ] **3.1** Add `min_records` rule with ERROR severity to `runner.py`; read threshold from parameter YAML

- [ ] **3.2** Add per-column null rate check:
  - `state` must be non-null in >95% of records
  - `utility` must be non-null in >90% of records
  - `charge_value` must be non-null in >80% of records

- [ ] **3.3** Add state coverage check:
  - At least 20 canonical states should appear in CSS records
  - At least 10 states for other parameters

- [ ] **3.4** Implement confidence recalibration:
  - Records with "Col N" as utility → confidence 0.3
  - Records with non-canonical state → confidence 0.5
  - Records with all fields populated → confidence 0.95
  - Use column descriptor match quality

- [ ] **3.5** Make `export_allowed = false` when any ERROR-severity check fails AND when warning count exceeds configurable threshold

### Phase 4: Excel Presentation & Cross_Subsidy_By_State Workbook

- [ ] **4.1** Add `column_display_names` to each parameter YAML:
  ```yaml
  export:
    column_display_names:
      state: "State/UT"
      utility: "Distribution Utility"
      consumer_category: "Consumer Category"
      charge_value: "Cross Subsidy Surcharge (Rs/kWh)"
      voltage_level: "Voltage Level"
      year_label: "Financial Year"
    exclude_columns: [record_id, parameter_id, consumer_subcategory, effective_date]
  ```

- [ ] **4.2** Update `dataframe_builder.py` to:
  - Rename columns using display name map
  - Exclude internal columns
  - Add `source_pages` column
  - Sort by State → Utility → Category

- [ ] **4.3** Update `excel_exporter.py` to use `sheet_name` from parameter YAML (display name, not parameter_id)

- [ ] **4.4** Add summary sheet generation:
  - Source PDF filename
  - Extraction timestamp
  - Per-parameter: record count, state coverage, validation status
  - Quality dashboard

- [ ] **4.5** Update `formatter.py`:
  - Add autofilter on header row
  - Add conditional formatting: green (confidence ≥ 0.9), yellow (0.7-0.9), red (<0.7)
  - Number formatting for charge values (2 decimal places)
  - Date formatting for effective_date

- [ ] **4.6** Implement `Cross_Subsidy_By_State.xlsx` export:
  - Create new export function in `excel_exporter.py`
  - One worksheet per state (sheet name = state name)
  - Within each sheet, columns: Utility | Consumer Category | Voltage Level | Charge (Rs/kWh) | Year | Notes | Confidence | Source Pages
  - Sort within sheet by Utility → Category
  - Apply same formatting as warehouse workbook

- [ ] **4.7** Wire new cross-subsidy export into `export_stage.py`:
  - After warehouse workbook export, generate state-level workbook
  - Save to `export/Cross_Subsidy_By_State.xlsx`

- [ ] **4.8** Final verification:
  - Open both workbooks in Excel
  - Spot-check 10 records against source PDF
  - Verify all states present
  - Verify column names are analyst-friendly
  - Verify autofilters, freeze panes, formatting

---

## Verification Plan

### Automated Tests
- `python -m pytest tests/` — existing test suite
- Add golden file comparison: compare `records.json` against expected output for each parameter
- Add record count assertions per parameter

### Manual Verification
- Open `Regulatory_Parameter_Warehouse.xlsx` — verify all 5 sheets have data
- Open `Cross_Subsidy_By_State.xlsx` — verify state sheets
- Cross-reference 20 random records against source PDF pages
- Verify every Indian state appears in cross-subsidy output

---

> [!IMPORTANT]
> **Phase 1 is the critical path.** Without fixing the multi-row header detection and block segmentation, nothing downstream can produce correct results. Phases 2-4 depend on Phase 1. However, Phase 3 and Phase 4 can be executed in parallel once Phase 2 is underway.

# Engineering Issue Log — Regulatory PDF Table Extraction Pipeline

> **Review Date:** 2026-07-10  
> **Workspace:** `b362c51a89b67ff4`  
> **Source PDF:** `co-ursi-key-regultry-parmtrs-pwr-utiltis-dt180526.pdf`  
> **Source of Truth:** PDF → `software_architecture_design.md` → `data_contracts.md`  
> **Review Scope:** Full pipeline — PDF, Discovery, Extraction, Normalization, Document Understanding, Pattern Classification, Parsing, Validation, Excel Export

---

## Executive Summary

The pipeline is broadly functional — all five parameters complete extraction and export without crashes. However, a systematic review against the source PDF and the architecture/data-contract specifications reveals **26 distinct engineering issues** across every pipeline stage. The issues range from critical data-correctness defects (wrong voltage column mapping, hardcoded column indices, CID-contaminated headers producing noise column names) to structural deviations from the design specification (an undocumented `understanding/` module that bypasses the contract boundary, a `page_count` recorded as 1 in the workspace manifest, and parser logic embedded inside supposedly reusable parser families).

The single highest-priority cluster is the **Wheeling Charges voltage-column reconstruction** problem. The PDF contains 6 discrete voltage levels (`Below 11 kV`, `11 kV`, `33 kV`, `66 kV`, `132 kV`, `200 kV & Above`) as multi-cell merged headers. The pipeline collapses this 3-row header into a flat view and then applies **hardcoded column index constants** (5, 8, 11, 14, 17, 19) rather than dynamically resolving voltage labels from the cleaned header tree. The result is that:

- **Column 19** is mislabelled `220 kV & Above` in records but the source PDF header reads `200 kV` / `200 kV & Above`.
- **Columns 6, 7, 9, 10, 12, 13, 15, 16, 18, 20, 21, 22** (inter-voltage sub-columns) are silently skipped, losing information.
- The header tree captures `200` as the leaf label rather than `200 kV & Above`, and the parser overrides this with `220 kV & Above` from a hardcoded fallback map — a value that does **not exist** in the source PDF.

Every issue below includes traceable evidence from intermediate artifacts.

---

## 1. Functional Issues

---

### F-01 — Wheeling Charge: `200 kV & Above` mislabelled as `220 kV & Above`

**Description**  
The source PDF header for the highest voltage tier reads `200 kV` / `200 kV & Above`. The pipeline emits `220 kV & Above` for every record in that tier.

**Evidence**
- `extraction/wheeling_charge/header_tree.json` line 74: leaf label is `200` (Hindi + English).
- `extraction/wheeling_charge/column_descriptors.json` lines 287-301: column 19 named `Wheeling Charges - 200`, `entity_type: charge` (not `voltage`), `semantic_role: value`.
- `parsing/wheeling_charge/records.json` lines 183-204: every record at column index 19 carries `voltage_level: 220 kV & Above` — not present in the PDF.
- `wide_to_long.py` line 158: `fallback_map = { ..., 19: "220 kV & Above" }` — hardcoded, incorrect.

**Root Cause**  
The `fallback_map` in `WideToLongParser.parse()` was set to `220 kV & Above` for index 19 without cross-checking the source PDF. The header extractor preserves only the numeric `200` leaf, stripping the `kV & Above` suffix during CID cleanup.

**Impact**  
Every row for the highest voltage tier carries a fabricated voltage label. An analyst querying `200 kV & Above` records will find zero rows; querying `220 kV & Above` will find rows that should not exist under that label.

**Priority:** CRITICAL  
**Affected Files:** `src/table_scraper/parsing/families/wide_to_long.py`  
**Affected Functions:** `WideToLongParser.parse()` — `fallback_map` dict, lines 152-159

---

### F-02 — Wheeling Charge: Hardcoded Column Indices Break on Any PDF Variant

**Description**  
The entire voltage column mapping (`label_to_value = {5: 5, 8: 8, 11: 11, 14: 14, 17: 17, 19: 18}`) is hardcoded for this exact PDF layout. The column descriptors and header tree expose the actual column positions and voltage labels, yet this information is not used.

**Evidence**
- `wide_to_long.py` lines 151-159: `label_to_value` and `fallback_map` are literal Python constants, not derived from `column_descriptors.json`.
- `column_descriptors.json` accurately identifies columns 5, 8, 11, 14, 17 as `entity_type: voltage` — information the parser completely ignores.

**Root Cause**  
The `WideToLongParser` specialisation was implemented by hardcoding PDF column positions rather than reading the output of `understanding/header_analyzer.py` already persisted as `column_descriptors.json`.

**Impact**  
A different PDF edition will silently produce wrong voltage assignments. The architecture design calls for a configurable column dimension map in the YAML (architecture Section 9), but this config does not exist in `wheeling_charge.yaml`.

**Priority:** HIGH  
**Affected Files:** `src/table_scraper/parsing/families/wide_to_long.py`, `config/parsers/parameters/wheeling_charge.yaml`  
**Affected Functions:** `WideToLongParser.parse()` — `label_to_value`, `fallback_map`, lines 151-159

---

### F-03 — Wheeling Charge: CID Noise Prefixes in Voltage Labels Not Cleaned from Header Tree

**Description**  
Raw merged table header rows contain Devanagari Unicode characters and CID artifacts that survive into `header_tree.json`. Tree leaf labels read `11 Below 11 kV`, `11 11 kV`, `33 33 kV` etc. — each prefixed by the kV number from the Hindi portion of the bilingual cell.

**Evidence**
- `raw_merged.json` line 90: `11 keVi se\n nIche\n Below\n 11 kV` — Hindi numeral `11` precedes the English text.
- `header_tree.json` lines 60-77: leaf labels include `11 Below 11 kV`, `11 11 kV`, `33 33 kV`, `66 66 kV`, `132 132 kV`, `200`.
- `column_descriptors.json` lines 78-91: `display_name = "Wheeling Charges - 11 Below 11 kV"` — numeric prefix embedded in the display name.

**Root Cause**  
`extract_english()` in `text_cleanup.py` strips Devanagari characters but leaves the leading numeric token originally part of the Hindi word. `build_header_tree()` in `header_analyzer.py` does not run a post-cleanup normalisation pass.

**Impact**  
Column display names in `column_descriptors.json` are noisy. Column 19 (`200`) is not identified as a voltage column because the suffix is missing.

**Priority:** HIGH  
**Affected Files:** `src/table_scraper/normalization/text_cleanup.py`, `src/table_scraper/understanding/header_analyzer.py`  
**Affected Functions:** `extract_english()`, `HeaderAnalyzer.resolve_column_semantics()` lines 150-156

---

### F-04 — Wheeling Charge: Inter-Voltage Sub-Columns (Unit/Year) Silently Lost

**Description**  
The PDF wide header contains 3 sub-columns per voltage tier. The parser only reads 1 sub-column per tier (at the hardcoded label index) and skips the adjacent sub-columns entirely.

**Evidence**
- `raw_merged.json` column count: 24 (23 after geometry normalisation).
- `column_descriptors.json`: columns 6, 7, 9, 10, 12, 13, 15, 16, 18, 20, 21, 22 all have `display_name: Wheeling Charges` and `entity_type: charge` — effectively unnamed sub-columns.
- `wide_to_long.py`: `label_to_value` covers only 6 of 23 columns.

**Root Cause**  
Header reconstruction fails to propagate the voltage label horizontally across all 3 sub-columns of each voltage group.

**Priority:** HIGH  
**Affected Files:** `src/table_scraper/understanding/header_analyzer.py`, `src/table_scraper/parsing/families/wide_to_long.py`

---

### F-05 — Wheeling Charge: Pattern Classifier Returns `unknown` at 0.0 Confidence

**Description**  
Pattern classification for `wheeling_charge` shows `pattern: unknown`, `confidence: 0.0`, `requires_user_confirmation: true`. Despite this, the pipeline continues to parse it using `wide_to_long_v1` without any user intervention.

**Evidence**
- `parsing/wheeling_charge/records.json` lines 3-35: `classification.pattern = unknown`, `confidence = 0.0`, `routing_source = classifier`.
- Line 47: `parser_id: wide_to_long_v1` — the parse succeeded anyway.

**Root Cause**  
`wheeling_charge.yaml` does not set `force_pattern`. Without an override, the classifier scores the table as `unknown`. The router then falls through to the YAML-declared `parser_id`, bypassing the `requires_user_confirmation` gate.

**Priority:** HIGH  
**Affected Files:** `config/parsers/parameters/wheeling_charge.yaml`, `src/table_scraper/parsing/router.py`

---

### F-06 — Additional Surcharge: `N/A` States Exported as Records with Empty `additional_surcharge`

**Description**  
States in the "Not Available" section emit records with `additional_surcharge: ""`. An analyst cannot distinguish "no data collected" from "zero charge" from "N/A".

**Evidence**
- `parsing/additional_surcharge/records.json` lines 677-750: 12 consecutive records with `additional_surcharge: ""` and `additional_surcharge_text: N/A`.

**Root Cause**  
`parse_additional_surcharge_value()` returns `None` for `N/A`, and the downstream handler sets `val = ""` before emitting the record. There is no dedicated `not_available` sentinel.

**Priority:** MEDIUM  
**Affected Files:** `src/table_scraper/parsing/families/numeric_matrix.py`

---

### F-07 — Additional Surcharge: Multi-Period Rows Lose the Secondary Period Value

**Description**  
Rows like `Apr-Sep25 - 1.13 (Partial OA) 1.53 (Full OA)` (Punjab) are parsed by extracting only the first decimal number (`1.13`). The second value (`1.53`) and qualifier text are silently discarded.

**Evidence**
- `parsing/additional_surcharge/records.json` lines 293-315: `additional_surcharge = 1.13`, `additional_surcharge_text = "Apr-Sep25 - 1.13 (Partial OA) 1.53 (Full OA)"`.
- `numeric_matrix.py` lines 44-46: `return float(decimal_matches[0])` — only first match used.

**Priority:** HIGH  
**Affected Files:** `src/table_scraper/parsing/families/numeric_matrix.py`  
**Affected Functions:** `parse_additional_surcharge_value()` lines 44-46

---

### F-08 — Additional Surcharge: Section Detection Requires Exact `<=` Symbol Survival through OCR Cleanup

**Description**  
Section headers are detected by checking for substrings `<=`, `>`, `level`, or `not available`. Detection will fail if the `<=` symbol is CID-encoded in a different PDF version.

**Evidence**
- `hierarchy.py` lines 90-94: `has_threshold_pattern = any(x in col1_lower for x in ("<=",...))`.

**Root Cause**  
Section header detection logic is mixed into `hierarchy.py` instead of being a configurable rule in the parameter YAML.

**Priority:** MEDIUM  
**Affected Files:** `src/table_scraper/normalization/hierarchy.py`

---

### F-09 — Transmission Charge: Identical `state_level` Row Duplicates Every Utility Record

**Description**  
Every state in the Transmission Charge table generates two records: one with `utility: state_level` and one with a named utility. Both records carry identical charge values.

**Evidence**
- `parsing/transmission_charge/records.json` lines 29-80: Andhra Pradesh row 5 -> `utility: state_level`, charge `201.8`. Row 6 -> `utility: APTRANSCO`, same charge `201.8`.

**Root Cause**  
The state-header row (which contains the charge values) is emitted before checking whether it is a true data row or just a state label row.

**Impact**  
Record count approximately doubled. Downstream analysis aggregating by utility will double-count state-level entries.

**Priority:** HIGH  
**Affected Files:** `src/table_scraper/parsing/families/numeric_matrix.py`

---

### F-10 — Transmission Charge: Unit Parsing May Produce `Rs/kVA/month` When PDF Shows `Rs/MW/month`

**Description**  
For Andhra Pradesh, the pipeline emits `long_medium_unit: Rs/kVA/month` and `short_term_unit: Rs/kVA/month`. The unit column indices may be wrong.

**Evidence**
- `parsing/transmission_charge/records.json` lines 31-40: `long_medium_unit = Rs/kVA/month`.
- `extract_unit_from_text()` matches `rs/kva/month` ahead of `rs/mw/month` in its if-chain, so if a cell contains both substrings, `kVA` wins.

**Root Cause**  
Unit column indices in `transmission_charge.yaml` (`long_medium_unit: 6`, `short_term_unit: 10`) may point to wrong columns. This is a potential off-by-one or wrong-column-index issue.

**Priority:** HIGH  
**Affected Files:** `src/table_scraper/parsing/families/numeric_matrix.py`, `config/parsers/parameters/transmission_charge.yaml`

---

## 2. Data Quality Issues

---

### D-01 — Wheeling Charge: 83.78% Value Null Rate Passes at 95% Threshold

**Description**  
377 of 450 records have empty `wheeling_charge` value. The 95% threshold is too permissive and provides no meaningful signal. The pipeline cannot distinguish empty-because-inapplicable from empty-because-extraction-failed.

**Evidence**  
- `parsing/wheeling_charge/validation.json` lines 77-86: `null_count: 377`, `null_rate: 0.8378`, `passed: true`.

**Priority:** MEDIUM  
**Affected Files:** `config/parsers/parameters/wheeling_charge.yaml`, `src/table_scraper/validation/runner.py`

---

### D-02 — Wheeling Charge: `States/UTs` Header Label Appears in `utilities_covered` List

**Description**  
The validation summary includes `States/UTs` in `utilities_covered`. This is a table header label, not a utility name.

**Evidence**  
- `parsing/wheeling_charge/validation.json` line 261: `States/UTs` listed alongside legitimate DISCOMs.

**Root Cause**  
The utility resolution logic falls through to `utility = row[0].strip()` on a row where the state column carries the bilingual header text `States/UTs`.

**Priority:** MEDIUM  
**Affected Files:** `src/table_scraper/parsing/families/wide_to_long.py`

---

### D-03 — Workspace Manifest: `page_count` Records as 1 for a Multi-Page PDF

**Description**  
The workspace manifest records `page_count: 1`. The wheeling charge table alone spans pages 59-61.

**Evidence**  
- `manifest.json` line 273: `page_count: 1`.

**Root Cause**  
The PDF reader is not correctly reading or passing the page count into the manifest at workspace open time.

**Priority:** HIGH  
**Affected Files:** `src/table_scraper/storage/workspace.py`, `src/table_scraper/adapters/pdf_reader.py`

---

### D-04 — Manifest: `extract` Stage Lists Artifacts from the Wrong Parameter

**Description**  
`stages.extract.artifact_paths` contains artifacts from `cross_subsidy_surcharge`. Each parameter's own record also mixes stale cross-parameter paths.

**Evidence**  
- `manifest.json` lines 307-313: paths point to `extraction\cross_subsidy_surcharge\`.
- `manifest.json` lines 22-31: `additional_surcharge` extract paths mix old and new parameter paths.

**Root Cause**  
The manifest update logic appends (rather than replaces) artifact paths to the global `stages.extract` record after each parameter extraction.

**Priority:** HIGH  
**Affected Files:** `src/table_scraper/storage/workspace.py`, `src/table_scraper/pipeline/stages/extract_stage.py`

---

### D-05 — `source_pages` Always Set to `[1]` in All Parsed Records

**Description**  
Every parsed record across all five parameters shows `source_pages: [1]` regardless of which PDF page the data actually came from.

**Evidence**  
- `parsing/wheeling_charge/records.json` lines 68-73: `source_pages: [1]` for data sourced from pages 59-61.
- `parsing/transmission_charge/records.json` lines 47-52: `source_pages: [1]` for data sourced from pages 62-63.

**Root Cause**  
All three parsers initialise `pages = [1]` as default. The `config.page_range` attribute is not correctly resolved at parse time — likely because `config` at parse time is the `ParameterConfig` object, not the `AppSettings` or `PipelineSession` that holds the confirmed page range.

**Impact**  
Source provenance is completely wrong. An analyst cannot locate the source page for any data value.

**Priority:** HIGH  
**Affected Files:** `src/table_scraper/parsing/families/wide_to_long.py`, `src/table_scraper/parsing/families/numeric_matrix.py`, `src/table_scraper/parsing/families/narrative.py`

---

## 3. Parsing Issues

---

### P-01 — Parser Families Contain Hardcoded Parameter-Specific Branches

**Description**  
Both `numeric_matrix.py` and `wide_to_long.py` contain large `if table.parameter_id == ...` branches — essentially separate parameter-specific parsers embedded inside shared parser classes. The architecture specifies parameter-specific logic should live in YAML files, not parser family implementations.

**Evidence**  
- `numeric_matrix.py` lines 131-330: three distinct if/elif/else branches for three parameters.
- `wide_to_long.py` lines 141-311: large `if table.parameter_id == "wheeling_charge"` branch.

**Impact**  
The architecture's extensibility goal ("Adding parameter #31 = new YAML file, not a new pipeline") is broken. Files approach 400+ lines, exceeding the 150-line guideline.

**Priority:** MEDIUM  
**Affected Files:** `src/table_scraper/parsing/families/numeric_matrix.py`, `src/table_scraper/parsing/families/wide_to_long.py`

---

### P-02 — `NarrativeParser`: Garbled Hindi Numeric Prefix Survives in `policy` Field

**Description**  
The `policy` field in Banking Charges records contains a leading ASCII numeric fragment from the bilingual cell structure (e.g., `(30%) 30% ...`).

**Evidence**  
- `parsing/banking_charges/records.json` lines 60-61: `policy: "(30%) 30% , , , , () () The Green Energy Open Access..."`.

**Root Cause**  
`extract_english()` removes Devanagari block characters but `(30%)` is ASCII and is not removed, even though it is the Hindi-language numeric reference.

**Priority:** LOW  
**Affected Files:** `src/table_scraper/normalization/text_cleanup.py`, `src/table_scraper/parsing/families/narrative.py`

---

### P-03 — Wheeling Charge: `Applicable Period (FY)` Column (Index 2) Identified But Never Consumed

**Description**  
Column 2 (`Applicable Period (FY)`) is correctly identified in `column_descriptors.json`. However, the `WideToLongParser` does not read from this column; year is instead extracted by a regex scan across all cells.

**Evidence**  
- `column_descriptors.json` lines 32-46: column 2 = `Wheeling Charges - Applicable Period (FY)`, `semantic_role: value`.
- `wide_to_long.py` lines 243-250: year extracted with regex fallback. Column 2 is never referenced by index.

**Priority:** MEDIUM  
**Affected Files:** `src/table_scraper/parsing/families/wide_to_long.py`

---

### P-04 — Cross-Subsidy Surcharge Records Not Reviewed in This Session

**Description**  
Cross-subsidy surcharge records were not deeply reviewed. Further investigation required.

**Evidence**  
- Manifest confirms `parsing/cross_subsidy_surcharge/pattern.json` = `state_block_matrix`.

**Priority:** LOW (pending dedicated review)

---

## 4. Normalization Issues

---

### N-01 — `understanding/` Module Not Defined in Architecture or Data Contracts

**Description**  
The implementation includes `src/table_scraper/understanding/` (`header_analyzer.py`, `metadata_annotator.py`, `models.py`) that is not described in `software_architecture_design.md` or `data_contracts.md`.

**Evidence**  
- `src/table_scraper/understanding/` directory with 3 source files present.
- Architecture Section 2: no `understanding/` package in the folder structure.
- `data_contracts.md`: no `AnnotatedTable`, `ColumnDescriptor`, `HeaderTree`, or `CellAnnotation` contracts defined.

**Impact**  
- Hidden pipeline stage and hidden data contracts that are not auditable.
- `AnnotatedTable` / `ColumnDescriptor` output is generated but **not consumed by any parser** — parsers implement their own inline column-resolution logic instead.
- The architecture's dependency rule "Normalization is pre-semantic" may be violated.
- Future engineers have no specification for this stage.

**Priority:** HIGH  
**Affected Files:** `src/table_scraper/understanding/` (entire package), `software_architecture_design.md`, `data_contracts.md`

---

### N-02 — `hierarchy.py` Section Header Detection Hardcoded to `additional_surcharge`

**Description**  
The section header detection block in `propagate_hierarchy()` contains `if table.parameter_id == "additional_surcharge"` — parameter-specific logic inside a generic normalization module.

**Evidence**  
- `hierarchy.py` line 86: `if table.parameter_id == "additional_surcharge" and idx >= header_rows_count:`.

**Priority:** MEDIUM  
**Affected Files:** `src/table_scraper/normalization/hierarchy.py`

---

### N-03 — Header Row Count Resolution Creates a Brittle Two-Step Dependency

**Description**  
The header row count is resolved from `row_labels` (set in `hierarchy.py` using the YAML value) rather than directly from the YAML config in the parser. A mismatch in either step causes wrong header detection without any error.

**Priority:** LOW  
**Affected Files:** `src/table_scraper/normalization/hierarchy.py`, `src/table_scraper/parsing/families/numeric_matrix.py`

---

## 5. Entity Recognition Issues

---

### E-01 — State Casing Inconsistency: `Jammu And Kashmir` vs `Jammu and Kashmir`

**Description**  
The validation summary lists `Jammu And Kashmir` (title-case `And`) while the standard canonical form is `Jammu and Kashmir` (lowercase `and`). Similar inconsistencies exist for `Dadra & Nagar Haveli And Daman & Diu`.

**Evidence**  
- `parsing/wheeling_charge/validation.json` line 130: `Jammu And Kashmir`.
- `parsing/additional_surcharge/records.json` line 803: `Jammu and Kashmir`.

**Root Cause**  
`resolve_canonical_state()` uses `.title()` on the alias target when the state is not in `states_map`. Python `.title()` capitalises every word including conjunctions.

**Impact**  
Cross-parameter queries by state name will miss rows due to casing mismatches.

**Priority:** MEDIUM  
**Affected Files:** `src/table_scraper/normalization/text_cleanup.py`

---

### E-02 — `Arunachal PD` Appears as Utility Name for Arunachal Pradesh

**Description**  
Transmission charge records show `utility: Arunachal PD` — not a recognised DISCOM name, but an abbreviation extracted from the bilingual cell text.

**Evidence**  
- `parsing/transmission_charge/records.json` line 115: `utility: Arunachal PD`.

**Root Cause**  
When the parser cannot find the utility from the DISCOM catalog, it falls back to `row[0].strip()` as the utility name.

**Priority:** MEDIUM  
**Affected Files:** `src/table_scraper/parsing/families/numeric_matrix.py`, `config/catalogs/utilities.yaml`

---

## 6. Validation Issues

---

### V-01 — Validation Does Not Check `voltage_level` Against a Known Vocabulary

**Description**  
The `wheeling_charge` validation does not verify that `voltage_level` values are from a known vocabulary. The fabricated value `220 kV & Above` passes all validation checks.

**Evidence**  
- `parsing/wheeling_charge/validation.json`: no `voltage_level_check` or vocabulary check present.

**Priority:** HIGH  
**Affected Files:** `src/table_scraper/validation/runner.py`, `config/parsers/parameters/wheeling_charge.yaml`

---

### V-02 — `state_blocks_used` Count vs Record Count Mismatch Not Validated

**Description**  
37 `state_blocks_used` blocks but 43 records for additional surcharge. The validation report does not confirm all expected states were successfully parsed.

**Priority:** LOW  
**Affected Files:** `src/table_scraper/validation/runner.py`

---

## 7. Export and Formatting Issues

---

### X-01 — Wheeling Charge Excel Column Header Hardcodes the Unit as `Rs/kWh`

**Description**  
The Excel column display name is `Wheeling Charge (Rs/kWh)`, embedding the unit assumption in the header. The table has a separate `charge_unit` column that can vary.

**Evidence**  
- `wheeling_charge.yaml` line 39: `wheeling_charge: "Wheeling Charge (Rs/kWh)"`.

**Priority:** LOW  
**Affected Files:** `config/parsers/parameters/wheeling_charge.yaml`

---

### X-02 — `state_level` Sentinel Converted to Empty String — Loses Semantic Meaning

**Description**  
`dataframe_builder.py` converts `state_level` to `""` for the `utility` column. An analyst cannot distinguish a state-level aggregate from a row where the DISCOM was not extracted.

**Evidence**  
- `dataframe_builder.py` lines 52-55: `if row_dict.get(key) == "state_level": row_dict[key] = ""`.

**Priority:** MEDIUM  
**Affected Files:** `src/table_scraper/export/dataframe_builder.py`

---

### X-03 — Summary Sheet Metrics Concatenated as Narrative String, Not Structured Columns

**Description**  
The `Summary` sheet contains rows like `450 records | 34 states | N/A | Export: Yes` as a single concatenated string — not machine-readable.

**Evidence**  
- `excel_exporter.py` line 93: metrics assembled into a single pipe-delimited string.

**Priority:** LOW  
**Affected Files:** `src/table_scraper/export/excel_exporter.py`

---

### X-04 — State Sheet Names May Collide for Long State Names in Cross_Subsidy_By_State.xlsx

**Description**  
State names are truncated to 31 characters for Excel limits. No collision check is performed after truncation.

**Priority:** LOW  
**Affected Files:** `src/table_scraper/export/excel_exporter.py`

---

## 8. Performance Issues

---

### PR-01 — Config Loader Called Repeatedly Inside Parser and Normalization Calls

**Description**  
`WideToLongParser.parse()`, `NumericMatrixParser.parse()`, and `propagate_hierarchy()` all call `get_config_loader()` and `loader.load_catalogs()` at the top of each invocation with no caching.

**Evidence**  
- `wide_to_long.py` lines 119-128; `numeric_matrix.py` lines 113-122; `hierarchy.py` lines 29-38: identical pattern in all three.

**Priority:** LOW  
**Affected Files:** `src/table_scraper/config/loader.py` and all three files above.

---

### PR-02 — `annotated_table.json` Is 20x Larger Than Normalized Table and Never Consumed

**Description**  
For wheeling charge, `annotated_table.json` is 776 KB vs `normalized.json` at 38 KB. No parser reads this artifact.

**Evidence**  
- `extraction/wheeling_charge/annotated_table.json`: 776,100 bytes.
- `extraction/wheeling_charge/normalized.json`: 37,689 bytes.

**Priority:** LOW  
**Affected Files:** `src/table_scraper/understanding/metadata_annotator.py`

---

## 9. Maintainability Issues

---

### M-01 — `extract_unit_from_text()` Duplicated in Two Parser Files

**Description**  
An identical `extract_unit_from_text()` function appears in both `numeric_matrix.py` (lines 14-34) and `wide_to_long.py` (lines 70-90). Any fix must be applied in both places.

**Priority:** MEDIUM  
**Affected Files:** `src/table_scraper/parsing/families/numeric_matrix.py`, `src/table_scraper/parsing/families/wide_to_long.py`

---

### M-02 — Workspace Manifest `version` Counter Has Reached 1031

**Description**  
The workspace manifest `version` counter is 1031. `manifest.save()` is being called far more frequently than intended (possibly inside per-row or per-record loops).

**Evidence**  
- `manifest.json` line 443: `version: 1031`.

**Priority:** LOW  
**Affected Files:** `src/table_scraper/storage/workspace.py`

---

### M-03 — No Cross-Validation between YAML `header_rows` Declaration and Normalization Output

**Description**  
There is no automated assertion that verifies the number of rows labelled `HEADER` after normalization equals the YAML-declared `header_rows`. Discrepancies would be silent.

**Priority:** LOW  
**Affected Files:** `src/table_scraper/normalization/hierarchy.py`, `src/table_scraper/validation/runner.py`

---

## 10. Future Generalization Issues

---

### G-01 — `wheeling_charge.yaml` Missing `column_dimension_map` Specified in Architecture Section 9

**Description**  
`software_architecture_design.md` Section 9 specifies `Wide-to-long dimension map: wheeling: {Below 11 kV: 5, ...}` as a configurable YAML item. This map does not exist in `wheeling_charge.yaml` — it is hardcoded in `wide_to_long.py`.

**Priority:** HIGH  
**Affected Files:** `config/parsers/parameters/wheeling_charge.yaml`, `src/table_scraper/parsing/families/wide_to_long.py`

---

### G-02 — No Golden Tests Exist for Any Parser Family

**Description**  
The architecture design specifies "Golden tests — one fixture PDF snippet per parser family; compare `records.json` to golden file." No golden tests are in place, as evidenced by defects in F-01 and F-05 going undetected through all validation checks.

**Priority:** HIGH  
**Affected Files:** `tests/fixtures/golden/` (missing files), all parser family modules

---

## TODO Checklist

| # | File / Location | Task | Issue | Priority |
|---|----------------|------|-------|----------|
| TODO-01 | `wide_to_long.py` — `fallback_map` | Replace `fallback_map[19]` value from `220 kV & Above` to `200 kV & Above`. Verify all six entries against the PDF. | F-01 | CRITICAL |
| TODO-02 | `wide_to_long.py` — `WideToLongParser.parse()` | Remove hardcoded `label_to_value` and `fallback_map` dicts. Derive voltage column positions and canonical labels dynamically from `column_descriptors.json` or the new `voltage_column_map` YAML key. | F-02, G-01 | HIGH |
| TODO-03 | `wheeling_charge.yaml` | Add a `voltage_column_map` section mapping canonical voltage names to expected column indices. Canonical names: `Below 11 kV`, `11 kV`, `33 kV`, `66 kV`, `132 kV`, `200 kV & Above`. | F-02, G-01 | HIGH |
| TODO-04 | `text_cleanup.py` — `extract_english()` | After removing Devanagari characters, strip leading standalone numeric tokens that were originally part of the Hindi label (e.g., `11 Below 11 kV` -> `Below 11 kV`). Apply a leading digit strip pattern after Hindi removal. | F-03 | HIGH |
| TODO-05 | `header_analyzer.py` — `resolve_column_semantics()` | Verify that bare numeric leaf labels (`200`) are reconstructed as `{n} kV` when the column semantic role is identified as voltage. Ensure column 19 is correctly identified as a voltage column. | F-03 | HIGH |
| TODO-06 | `wide_to_long.py` — voltage column iteration | Investigate the 3 sub-columns per voltage tier. Determine which contains the charge value vs year vs unit. Decide whether to skip or parse inter-voltage sub-columns. | F-04 | HIGH |
| TODO-07 | `wheeling_charge.yaml` | Add `force_pattern: wide_table` to ensure the pattern classifier override path is used and `requires_user_confirmation` is not silently bypassed. | F-05 | HIGH |
| TODO-08 | `router.py` — `route_and_parse()` | Review the fallback path when `confidence == 0.0` and `requires_user_confirmation == true`. Add an explicit guard that warns or raises when confidence is below threshold and no `force_pattern` is set. | F-05 | HIGH |
| TODO-09 | `numeric_matrix.py` — `parse_additional_surcharge_value()` | For multi-value cells (e.g., `1.13 (Partial OA) 1.53 (Full OA)`), determine whether to emit two records with an `oa_type` field, or store all numeric matches without data loss. | F-07 | HIGH |
| TODO-10 | `hierarchy.py` — `propagate_hierarchy()` | Remove `if table.parameter_id == "additional_surcharge"` block. Move section header detection into a configurable rule read from `section_header_patterns` in the parameter YAML. | N-02 | MEDIUM |
| TODO-11 | `numeric_matrix.py` — `transmission_charge` branch | Review whether the state-header row should be emitted as `state_level` or suppressed. If the state row is purely a section header in the PDF, suppress it. If it carries a state aggregate value, mark `utility` as `State Aggregate`. | F-09 | HIGH |
| TODO-12 | `numeric_matrix.py` + `transmission_charge.yaml` | Verify actual column content at indices 6 and 10 (unit columns) against the raw merged table for Andhra Pradesh. Confirm whether the unit is `Rs/kVA/month` or `Rs/MW/month`. Fix the column index or the `extract_unit_from_text()` priority ordering. | F-10 | HIGH |
| TODO-13 | `workspace.py` + `pdf_reader.py` | Identify where `page_count: 1` is set. Ensure the PDF reader correctly reads the actual page count and passes it to `PDFDocument` at workspace open time. | D-03 | HIGH |
| TODO-14 | `workspace.py` + `extract_stage.py` | Fix manifest artifact path management so each parameter's `parameter_status.{param}.extract.artifact_paths` contains only its own artifacts, not stale cross-parameter paths. | D-04 | HIGH |
| TODO-15 | All three parser files — `pages` resolution | Trace how `config` is passed from the pipeline stage to the parser. Identify the correct attribute or dict key that carries the confirmed `PageRange`. Fix all three parsers to correctly read the page range and populate `source_pages` in each `ParsedRecord`. | D-05 | HIGH |
| TODO-16 | `text_cleanup.py` — `resolve_canonical_state()` | Replace `.title()` fallback with a lookup that preserves the canonical casing from `states.yaml`. Return the alias-target value from the catalog without applying `.title()`. | E-01 | MEDIUM |
| TODO-17 | `utilities.yaml` | Add `Arunachal PD`, `AEGCL`, and other abbreviated or informal utility names found in the PDF to the utilities catalog with canonical full names and abbreviation aliases. | E-02 | MEDIUM |
| TODO-18 | `validation/runner.py` + `wheeling_charge.yaml` | Add an `allowed_voltage_levels` validation rule for `wheeling_charge`. Define the vocabulary in `wheeling_charge.yaml`. Any record with a value outside this vocabulary should generate an error. | V-01 | HIGH |
| TODO-19 | `dataframe_builder.py` — `records_to_dataframe()` | Convert `state_level` to a human-readable value such as `State Aggregate` or `(State Level)` instead of `""`. | X-02 | MEDIUM |
| TODO-20 | `numeric_matrix.py` + `wide_to_long.py` | Consolidate the duplicate `extract_unit_from_text()` into a single shared module (e.g., `src/table_scraper/parsing/unit_utils.py`). Both parser families import from this shared module. | M-01 | MEDIUM |
| TODO-21 | `understanding/` package + architecture + data contracts | Decide whether `understanding/` is a permanent pipeline stage. If yes: add it to the architecture spec and data contracts, and ensure parsers consume `ColumnDescriptor` output. If no: remove it and move relevant logic into normalisation or parsing. | N-01 | HIGH |
| TODO-22 | `numeric_matrix.py` — `NumericMatrixParser.parse()` | Separate the three parameter-specific branches into configuration-driven behaviour. Move each branch's specific logic (column maps, year detection, section detection) into corresponding YAML keys. | P-01 | MEDIUM |
| TODO-23 | `tests/fixtures/golden/` | Create golden `records.json` fixtures for each parser family. Write regression tests. Start with `wheeling_charge` (highest defect density) and `additional_surcharge`. | G-02 | HIGH |
| TODO-24 | `numeric_matrix.py` + `additional_surcharge.yaml` | Define a clear semantic contract for N/A states. Introduce a `data_not_available` sentinel or dedicated boolean `is_available` field rather than using `""` for the numeric field and `N/A` for the text field. | F-06 | MEDIUM |
| TODO-25 | `wide_to_long.py` — utility scanning | Add a guard preventing header-cell values (e.g., `States/UTs`) from being assigned as utility names. Check against known header-cell strings or the row_labels before assigning utility from `row[0]`. | D-02 | MEDIUM |
| TODO-26 | `workspace.py` — `WorkspaceManifest.save()` | Review how frequently `manifest.save()` is called. Move the save call to stage-level checkpoints only (once per stage completion, not once per record). Cap the `version` counter increment to stage-level operations. | M-02 | LOW |

---

*End of issue log. Total issues identified: 26. Total TODOs: 26.*

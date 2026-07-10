# Engineering Issue Log & Implementation Backlog
## Regulatory PDF Table Extraction Pipeline

> **Review Date:** 2026-07-09
> **Pipeline Version Under Review:** Workspace `b362c51a89b67ff4` (PDF: `co-ursi-key-regultry-parmtrs-pwr-utiltis-dt180526.pdf`)
> **Source of Truth:** `software_architecture_design.md`, `data_contracts.md`, PDF source document
> **Artifacts Reviewed:** `records.json`, `normalized.json`, `state_blocks.json`, `column_descriptors.json`, `header_tree.json`, `validation.json`, `manifest.json`, all parser source files, all config catalogs, all parser families

---

# Executive Summary

The pipeline successfully extracts and exports regulatory data for five parameters and is architecturally sound at the module boundary level. However, a significant number of data quality, parsing accuracy, entity recognition, and architectural conformance issues exist that collectively degrade the reliability and analyst usability of the final Excel workbooks.

**Most critical issues:**

1. **Manifest path contamination** — Every parameter's `artifact_paths` in `manifest.json` contains paths from a *different* parameter (e.g. `additional_surcharge` lists `cross_subsidy_surcharge` paths). Systemic bug in manifest accumulation.

2. **Additional Surcharge — section loss** — Three logical sections (Low ≤ Rs 1.50 / Medium > Rs 1.50 to Rs 2.00 / Not Available) are in the normalized table but completely absent from every parsed record. No `section` field anywhere.

3. **Additional Surcharge — 16 states missing** — All states in the "Not Available" section are skipped because `parse_additional_surcharge_value()` returns `None` for `"N/A"`. 16 out of 36 states/UTs emit zero records.

4. **Additional Surcharge — textual charge values truncated** — Period-qualified values (`"1st Apr'25 - 30th Sep'25: 0.82"`, `"Apr-Sep'25 - 1.13 (Partial OA) 1.53 (Full OA)"`) are reduced to the first decimal only. The period qualifier and alternate values are discarded.

5. **Wheeling Charge — corrupted voltage labels** — Header reconstruction produces `"11 Below 11 kV"`, `"11 11 kV"`, `"33 33 kV"`, `"66 66 kV"`, `"132 132 kV"`, `"200"` instead of `"<11 kV"`, `"11 kV"`, `"33 kV"`, `"66 kV"`, `"132 kV"`, `"220 kV & Above"`.

6. **Wheeling Charge — incomplete voltage coverage** — Many DISCOM rows emit values for only a subset of voltage columns. The column-to-voltage mapping is broken for interspersed non-voltage columns.

7. **Wheeling Charge — duplicate records** — Himachal Pradesh (rows 45–46) produces exact semantic duplicates across all voltage levels.

8. **Transmission Charge — hardcoded column indices** — Parser reads `row[4]`, `row[6]`, `row[8]`, `row[10]` as magic positional indices. Any schema variation in the PDF silently produces wrong values.

9. **Transmission Charge — unit silently dropped** — When `long_medium_charge` is absent, `long_medium_unit` is also discarded even though the unit is still known.

10. **State catalog inconsistency** — `states.yaml` uses `"Jammu and Kashmir"` (lowercase `and`); `.title()` produces `"Jammu And Kashmir"`. The utility catalog key `"Jammu and Kashmir"` does not match the record value. Same issue for `"Dadra & Nagar Haveli and Daman & Diu"`.

11. **`page_count: 1` and `source_pages: [1]`** — All records report page 1 for a 20 MB multi-page PDF. Source page provenance is broken.

12. **Architecture deviations** — `understanding/` and `entity_recognition/` modules are undocumented, and their artifacts are written to the wrong workspace folder (`parsing/{param}/` instead of `extraction/{param}/`).

---

# Category: Functional Issues

---

## F-01 — Additional Surcharge: Logical Section Context Lost

**Description**
The Additional Surcharge table has three logical sections: Low (≤ Rs 1.50), Medium (> Rs 1.50 to Rs 2.00), and Not Available. These section headers appear in the normalized table (rows 2–3 for Low, 21–22 for Medium, 33 for Not Available). Zero parsed records carry a `section` field or provenance key to identify which section they belong to. All 31 emitted records are structurally indistinguishable by section.

**Evidence**
- `extraction/additional_surcharge/normalized.json` rows 2–3: `": ≤ 1.50"`, `"Low Additional Surcharge Level: ≤ Rs 1.50"`
- `extraction/additional_surcharge/normalized.json` rows 21–22: `": > 1.50 2.00"`, `"Medium Additional Surcharge Level: > Rs 1.50 to Rs. 2.00"`
- `parsing/additional_surcharge/records.json`: zero records contain a `section` field

**Root Cause**
`numeric_matrix.py → NumericMatrixParser.parse()` (additional_surcharge branch) iterates row-by-row with no state machine tracking section-header rows. Section headers are neither detected nor stored.

**Impact:** Analysts cannot filter Low vs Medium vs Not Available data without re-reading the source PDF.
**Priority:** Critical
**Affected Files:** `src/table_scraper/parsing/families/numeric_matrix.py`
**Affected Functions:** `NumericMatrixParser.parse()` (additional_surcharge branch, lines ~220–288)

---

## F-02 — Additional Surcharge: Period-Qualified Textual Values Truncated

**Description**
Several states report period-qualified charges in their value cell:
- Gujarat: `"1st Apr'25 - 30th Sep'25: 0.82"`
- Haryana: `"Apr-Sep'25 - 1.21"`
- Punjab: `"Apr-Sep'25 - 1.13 (Partial OA) 1.53 (Full OA)"`
- Tamil Nadu: `"Apr-Sep'25 - 0.10"`
- Telangana: `"Apr-Sep'26 - 0.13"`
- Uttarakhand: `"Apr-Sep'25 - 1.14"`
- Delhi (multiple DISCOMs): `"(Oct-Apr): 1.33-1.90"`, `"(May-Sep): 0.66-0.95"`

All are reduced to a single float from the first `re.findall(r"\b\d+\.\d+\b", ...)` match. Period qualifier text and alternate values are discarded.

**Evidence**
- `extraction/additional_surcharge/normalized.json` row 7: `"1st Apr'25 - 30th Sep'25: 0.82"`
- `parsing/additional_surcharge/records.json` Gujarat record: `"additional_surcharge": 0.82` — no period qualifier preserved
- `extraction/additional_surcharge/normalized.json` row 15: `"Apr-Sep'25 - 1.13 (Partial OA) 1.53 (Full OA)"`
- `parsing/additional_surcharge/records.json` Punjab record: `"additional_surcharge": 1.13` — value `1.53 (Full OA)` completely lost

**Root Cause**
`parse_additional_surcharge_value()` returns only `decimal_matches[0]` — the first decimal number found in the string.

**Impact:** Seasonal/partial-OA rate structures are silently replaced by a single value. Analysts are unaware of the period qualification and alternate charge tiers.
**Priority:** Critical
**Affected Files:** `src/table_scraper/parsing/families/numeric_matrix.py`
**Affected Functions:** `parse_additional_surcharge_value()` (lines ~37–55), `NumericMatrixParser.parse()` additional_surcharge branch (lines ~246–260)

---

## F-03 — Additional Surcharge: 16 States with "N/A" Produce Zero Records

**Description**
The source table's "Not Available" section lists 16 states/UTs: Andaman & Nicobar Islands, Arunachal Pradesh, Assam, Bihar, Chhattisgarh, J&K, Ladakh, Jharkhand, Lakshadweep, Manipur, Mizoram, Nagaland, Sikkim, Tripura, Uttar Pradesh, West Bengal. All have `"N/A"` in the charge column. `parse_additional_surcharge_value()` returns `None` for `"N/A"`, so all are skipped. Zero records are emitted for these 16 states.

**Evidence**
- `extraction/additional_surcharge/normalized.json` rows 35–50: states with `"N/A"`
- `parsing/additional_surcharge/records.json`: none of these 16 states appear in any record
- `parsing/additional_surcharge/validation.json` states_covered: lists only 20 states, not 36
- States missing from export: 16 (44% of all states/UTs)

**Root Cause**
`parse_additional_surcharge_value()` line ~41: `if val_clean in ("n/a", "na", "not applicable", "not available", "--"): return None`. The design treats "N/A" as a skip condition, but the data contract requires a record for every state in the source table.

**Impact:** 44% of states are completely absent from the Additional Surcharge export. Data completeness is fundamentally compromised.
**Priority:** Critical
**Affected Files:** `src/table_scraper/parsing/families/numeric_matrix.py`
**Affected Functions:** `parse_additional_surcharge_value()` (lines ~37–55), `NumericMatrixParser.parse()` additional_surcharge branch

---

## F-04 — Additional Surcharge: DISCOM Rows for Delhi Not Differentiated

**Description**
Delhi rows are split into DISCOM-level rows (BRPL, BYPL, TPDDL) in the normalized table. Parsing assigns `state: "Delhi"` to all three without capturing the DISCOM identity. The DISCOM name is lost.

**Evidence**
- `extraction/additional_surcharge/state_blocks.json`: blocks `additional_surcharge_brpl_25_25`, `additional_surcharge_bypl_27_27`, `additional_surcharge_tpddl_29_29`
- `parsing/additional_surcharge/records.json`: BRPL/BYPL/TPDDL rows all show `state: "Delhi"` with no DISCOM sub-field

**Root Cause**
`block_segmentation.py` incorrectly classifies BRPL/BYPL/TPDDL as state-level blocks (via fallback detection), and the parser uses the forward-filled `current_state` ("Delhi") rather than recognizing the DISCOM context.

**Impact:** Delhi's per-DISCOM Additional Surcharge differentiation is lost. All three DISCOMs appear identical.
**Priority:** High
**Affected Files:** `src/table_scraper/normalization/block_segmentation.py`, `src/table_scraper/parsing/families/numeric_matrix.py`
**Affected Functions:** `_create_block()`, `NumericMatrixParser.parse()` additional_surcharge branch

---

## F-05 — Wheeling Charge: Voltage Label Corruption in Header Reconstruction

**Description**
The header tree and column descriptors show corrupted voltage-level labels: `"11 Below 11 kV"`, `"11 11 kV"`, `"33 33 kV"`, `"66 66 kV"`, `"132 132 kV"`, `"200"`. These should be `"<11 kV"` (or `"Below 11 kV"`), `"11 kV"`, `"33 kV"`, `"66 kV"`, `"132 kV"`, `"220 kV & Above"`.

**Evidence**
- `parsing/wheeling_charge/header_tree.json`: `"11 Below 11 kV"`, `"11 11 kV"`, `"33 33 kV"`, `"66 66 kV"`, `"132 132 kV"`, `"200"`
- `parsing/wheeling_charge/column_descriptors.json` indices 5, 8, 11, 14, 17, 19: all corrupted
- `extraction/wheeling_charge/normalized.json` row 2 (3rd header row): same corrupted labels
- The wide_to_long parser avoids the error by coincidence — it uses an independent keyword dictionary (`voltage_keywords`) for its own mapping, bypassing the corrupted header labels

**Root Cause**
The header reconstruction logic (in `understanding/header_analyzer.py` or equivalent) concatenates cells from multiple header rows without recognizing that numeric values in intermediate merged-cell rows (`"11"`, `"33"`, `"66"`, `"132"`) are row-separator artifacts, not part of the voltage label text.

**Impact:** `column_descriptors.json` and `header_tree.json` carry malformed labels. Any consumer of these artifacts will receive wrong voltage names. The parse result is only accidentally correct.
**Priority:** High
**Affected Files:** `src/table_scraper/understanding/header_analyzer.py`, `src/table_scraper/understanding/metadata_annotator.py`

---

## F-06 — Wheeling Charge: Incomplete Voltage Column Coverage Per Row

**Description**
Many DISCOM rows emit records for only a subset of voltage levels. For example, DHBVN (Haryana) emits `Below 11 kV` and `33 kV` but not `11 kV`, `66 kV`, or `132 kV`. The `11 kV` tier value for Haryana is incorrectly credited to `utility: "Haryana"` (state row) rather than to DHBVN and UHBVN.

**Evidence**
- `parsing/wheeling_charge/records.json` rows 42–44:
  - Row 42 (`utility: "Haryana"`): `voltage_level: "11 kV"`, `col_index: 9`
  - Row 43 (DHBVN): only `Below 11 kV` (col 7) and `33 kV` (col 10) — col 9 missing
  - Row 44 (UHBVN): same pattern
- The Wheeling Charge table has 3 columns per voltage tier: charge value + unit + (sometimes) supplemental value. The proximity heuristic (`c_idx ± 1`) collapses when multiple value columns exist between two label columns.

**Root Cause**
`wide_to_long.py` maps only label columns to voltage names. For value cells, it checks `c_idx`, `c_idx - 1`, `c_idx + 1` to find a voltage label. When the table has 3-column-wide tiers, this heuristic assigns the wrong voltage to many cells.

**Impact:** Significant data loss — multiple states/DISCOMs have missing voltage-tier records. Data appears complete (no null flags) but is semantically wrong.
**Priority:** Critical
**Affected Files:** `src/table_scraper/parsing/families/wide_to_long.py`
**Affected Functions:** `WideToLongParser.parse()` wheeling_charge branch (lines ~138–296)

---

## F-07 — Wheeling Charge: Semantic Duplicate Records (Himachal Pradesh)

**Description**
Himachal Pradesh generates exact semantic duplicate records from two consecutive rows (45 and 46) in the normalized table — same `state`, `utility`, `year`, `voltage_level`, and `wheeling_charge` for all voltage tiers.

**Evidence**
- `parsing/wheeling_charge/records.json` record `bd4bea3e58b4f48a` (row 45, col 9) and `63d0f5a7dcefc7b4` (row 46, col 9): identical fields `state: "Himachal Pradesh"`, `utility: "Himachal Pradesh"`, `voltage_level: "11 kV"`, `wheeling_charge: 1.75`, `year: "2026-27"`
- Same duplication for `33 kV`, `66 kV`, `132 kV` tiers

**Root Cause**
Two consecutive rows in the normalized table carry the same values for Himachal Pradesh (likely a multi-row merged cell in the source PDF). The parser emits a record for every numeric value in every row with no semantic deduplication.

**Impact:** Inflated record counts, misleading duplicate values. Validation did not catch this (no composite-key deduplication rule).
**Priority:** High
**Affected Files:** `src/table_scraper/parsing/families/wide_to_long.py`
**Affected Functions:** `WideToLongParser.parse()` wheeling_charge branch

---

## F-08 — Wheeling Charge: Non-State Entity Block IDs in State Blocks

**Description**
The `state_blocks_used` list for wheeling_charge contains entries such as `wheeling_charge_states/uts_36_36`, `wheeling_charge_lpdd_52_52`, `wheeling_charge_brpl_25_25`, `wheeling_charge_bypl_26_26`, `wheeling_charge_tpddl_27_27`, `wheeling_charge_kpdcl_50_50`, `wheeling_charge_mspdcl_85_85`, `wheeling_charge_pavvnl_125_125`. These are header strings, truncated abbreviations, or DISCOMs — not canonical states.

**Evidence**
- `parsing/wheeling_charge/records.json` `state_blocks_used` list (lines 2695–2759)
- `wheeling_charge_states/uts_36_36`, `wheeling_charge_lpdd_52_52`, `wheeling_charge_pavvnl_125_125`

**Root Cause**
`block_segmentation.py → detect_state_in_row()` falls back to `row[1].strip() or row[0].strip()` for MASTER-labeled rows when no canonical state is detected. This assigns raw cell text as the block's `state` without catalog validation.

**Impact:** Phantom blocks; block IDs are unpredictable; any block-based parser will create incorrectly attributed records for these.
**Priority:** High
**Affected Files:** `src/table_scraper/normalization/block_segmentation.py`
**Affected Functions:** `segment_state_blocks()` (lines ~246–297), `detect_state_in_row()` (lines ~205–244)

---

## F-09 — Transmission Charge: Hardcoded Column Indices

**Description**
The transmission charge parser reads values from fixed positional indices: `row[4]` for long/medium charge, `row[6]` for long/medium unit, `row[8]` for short-term charge, `row[10]` for short-term unit. Any schema change in the source PDF will silently produce wrong values.

**Evidence**
- `src/table_scraper/parsing/families/numeric_matrix.py` lines 179–182:
  ```python
  long_medium_charge = parse_float(row[4], r_idx, 4) if len(row) > 4 else None
  long_medium_unit = row[6].strip() if len(row) > 6 else ""
  short_term_charge = parse_float(row[8], r_idx, 8) if len(row) > 8 else None
  short_term_unit = row[10].strip() if len(row) > 10 else ""
  ```
- Architecture spec: column indices must be declared in `config/parsers/parameters/transmission_charge.yaml`

**Root Cause**
Architectural requirement to drive column maps from YAML config was not followed.

**Impact:** Fragile against PDF schema changes; violates the "no hardcoded magic numbers" principle.
**Priority:** High
**Affected Files:** `src/table_scraper/parsing/families/numeric_matrix.py`, `config/parsers/parameters/transmission_charge.yaml` (missing or incomplete)
**Affected Functions:** `NumericMatrixParser.parse()` transmission_charge branch (lines ~134–215)

---

## F-10 — Transmission Charge: Unit Silently Discarded When Charge Is Absent

**Description**
When `long_medium_charge` is `None`, `long_medium_unit` is also set to `""`. This applies even though the unit is still readable from the source table. States with only one charge tier (e.g. Assam has only short-term, Delhi has only long/medium) permanently lose the applicable unit for the absent tier.

**Evidence**
- `parsing/transmission_charge/records.json` rows 9–10 (Assam): `"long_medium_charge": ""`, `"long_medium_unit": ""`
- `parsing/transmission_charge/records.json` rows 18–19 (Delhi): `"short_term_charge": ""`, `"short_term_unit": ""`
- `parsing/transmission_charge/validation.json`: `"long_medium_unit": 8` missing fields, `"short_term_unit": 9` missing

**Root Cause**
`numeric_matrix.py` line ~192: `"long_medium_unit": extract_unit_from_text(...) if (long_medium_unit and long_medium_charge is not None) else ""` — the unit is suppressed when the charge is absent.

**Impact:** Partial records are misleading — analysts cannot determine the applicable unit for future data fills.
**Priority:** Medium
**Affected Files:** `src/table_scraper/parsing/families/numeric_matrix.py`
**Affected Functions:** `NumericMatrixParser.parse()` transmission_charge branch (lines ~192–194)

---

## F-11 — Manifest: Cross-Parameter Artifact Path Contamination

**Description**
In `manifest.json`, every parameter's `artifact_paths` for each stage includes paths from a *different* parameter. For example, `additional_surcharge.classify.artifact_paths = ["parsing\\cross_subsidy_surcharge\\pattern.json", "parsing/additional_surcharge/pattern.json"]`. This is systemic across all five parameters.

**Evidence**
- `manifest.json` lines 8–11: `additional_surcharge.classify.artifact_paths` contains `cross_subsidy_surcharge` path
- Same pattern for `banking_charges`, `cross_subsidy_surcharge`, `transmission_charge`, `wheeling_charge`
- The top-level `stages` section also has incorrect paths

**Root Cause**
The stage manifest update function appends to a shared artifact path list rather than resetting to a parameter-scoped list before each parameter is processed.

**Impact:** Manifest cannot be trusted for idempotency checks or cache invalidation. Re-runs may skip stages for wrong parameters.
**Priority:** Critical
**Affected Files:** `src/table_scraper/storage/workspace.py`, `src/table_scraper/pipeline/stages/` (all stage files)

---

# Category: Data Quality Issues

---

## DQ-01 — `page_count: 1` and `source_pages: [1]` for All Records

**Description**
The manifest reports `page_count: 1` for a 20 MB PDF. Every parsed record across all five parameters has `source_pages: [1]`. Source page provenance is completely broken.

**Evidence**
- `manifest.json` line 258: `"page_count": 1`
- Every record in all five `records.json` files: `"source_pages": [1]`

**Root Cause**
The `pages = [1]` fallback in each parser is triggered because `config.page_range` is not passed through correctly from the pipeline. Likely the PDF is also only being indexed on one page.

**Impact:** Source page traceability is useless. The `source_pages` field in `ParsedRecord` is meaningless.
**Priority:** Critical
**Affected Files:** All parser families (numeric_matrix.py, wide_to_long.py, narrative.py, state_block_matrix.py)
**Affected Functions:** All `parse()` methods — page resolution fallback block

---

## DQ-02 — Additional Surcharge: `"State Level"` Pseudo-State in Records

**Description**
Two records have `state: "State Level"`. These correspond to section-header rows (rows 2–3: `": ≤ 1.50"` and `"Low Additional Surcharge Level: ≤ Rs 1.50"`). The parser is treating section-header rows as data rows.

**Evidence**
- `parsing/additional_surcharge/validation.json`: `invalid_states: ["State Level"]`, `passed: false` for state_validation rule
- Two records in `parsing/additional_surcharge/records.json` with `state: "State Level"`, `additional_surcharge: 1.5`

**Root Cause**
At the time section header rows are processed, no `current_state` has been established, so the parser falls back to `"State Level"`. The `"1.50"` decimal in `": ≤ 1.50"` matches the regex and generates a spurious value.

**Impact:** Spurious records pollute the output. Validation flags them only as a warning.
**Priority:** High
**Affected Files:** `src/table_scraper/parsing/families/numeric_matrix.py`
**Affected Functions:** `NumericMatrixParser.parse()` additional_surcharge branch

---

## DQ-03 — State Catalog: `"Jammu and Kashmir"` vs `"Jammu And Kashmir"` Inconsistency

**Description**
`config/catalogs/states.yaml` lists `"Jammu and Kashmir"` (lowercase `and`). All parsers call `.title()` on the detected state, producing `"Jammu And Kashmir"`. The utility catalog uses `"Jammu and Kashmir"` as its key. Joins between records and catalog will fail silently. Same issue for `"Dadra & Nagar Haveli and Daman & Diu"` vs `"Dadra & Nagar Haveli And Daman & Diu"`.

**Evidence**
- `config/catalogs/states.yaml` line 32: `"Jammu and Kashmir"`
- `config/catalogs/utilities.yaml` lines 35–37: key `"Jammu and Kashmir"`
- `parsing/wheeling_charge/validation.json` states_covered: `"Jammu And Kashmir"` (title-cased)

**Root Cause**
Python `.title()` capitalizes every word including conjunctions. Catalog uses lowercase conjunctions per Indian government naming convention.

**Impact:** All joins on state names between records and the catalog will silently fail for the affected states.
**Priority:** High
**Affected Files:** `src/table_scraper/parsing/families/numeric_matrix.py`, `wide_to_long.py`, `narrative.py`, `normalization/hierarchy.py`, `normalization/block_segmentation.py`, `config/catalogs/states.yaml`
**Affected Functions:** `clean_state_candidate()` in all parsers and normalizers

---

## DQ-04 — Wheeling Charge: `utility` Set to State Name Instead of `"state_level"` Sentinel

**Description**
Records where no DISCOM is identified show `utility: "Haryana"`, `utility: "Himachal Pradesh"`, `utility: "Jharkhand"`, etc. — the state name is incorrectly used as the utility value. The contract specifies `"state_level"` as the sentinel for state-aggregate rows.

**Evidence**
- `parsing/wheeling_charge/records.json`: `state: "Haryana"`, `utility: "Haryana"`, `voltage_level: "11 kV"`
- `parsing/wheeling_charge/records.json`: `state: "Himachal Pradesh"`, `utility: "Himachal Pradesh"`

**Root Cause**
`wide_to_long.py` line ~241–242: when `utility == "state_level"` and `row[0]` is not a recognized state, sets `utility = row[0].strip()`. For rows where col 0 holds the state name, the state name becomes the utility.

**Impact:** Inconsistent utility sentinel; misleads any downstream join on `utility == "state_level"`.
**Priority:** Medium
**Affected Files:** `src/table_scraper/parsing/families/wide_to_long.py`
**Affected Functions:** `WideToLongParser.parse()` wheeling_charge branch (lines ~239–242)

---

## DQ-05 — Transmission Charge: Truncated Utility Name `"Arunachal PD"`

**Description**
Arunachal Pradesh's utility is exported as `"Arunachal PD"` while the canonical name in `utilities.yaml` is `"DoP Arunachal"`. These are different strings for the same entity.

**Evidence**
- `parsing/transmission_charge/records.json`: `utility: "Arunachal PD"`
- `config/catalogs/utilities.yaml` line 8: `DoP Arunachal`

**Root Cause**
Raw PDF text for this utility is `"Arunachal PD"` (abbreviated). No alias resolution is performed for values in the utility column of the transmission table.

**Impact:** Inconsistent naming; catalog joins fail for Arunachal Pradesh.
**Priority:** Low
**Affected Files:** `src/table_scraper/parsing/families/numeric_matrix.py`, `config/catalogs/utilities.yaml`

---

# Category: Parsing Issues

---

## P-01 — Parameter-Specific Logic Embedded in Generic Parser Classes

**Description**
`NumericMatrixParser.parse()` contains three parameter-specific `if/elif` branches (transmission_charge, additional_surcharge, else fallback). `WideToLongParser.parse()` has a wheeling_charge branch vs fallback. `NarrativeParser.parse()` has a banking_charges branch vs fallback. This violates the plugin architecture principle that parsers are generic and parameter-specific behavior is config-driven.

**Evidence**
- `numeric_matrix.py` lines ~133–345: `if table.parameter_id == "transmission_charge": ... elif table.parameter_id == "additional_surcharge": ...`
- `wide_to_long.py` lines ~138–296: `if table.parameter_id == "wheeling_charge": ...`
- `narrative.py` lines ~66–end: `if table.parameter_id == "banking_charges": ...`

**Root Cause**
Parameter-specific behavior was implemented directly in parser classes instead of being driven by YAML config.

**Impact:** Parser grows unboundedly as parameters are added; violates "add parameter = add YAML only" contract; inhibits testing and isolation.
**Priority:** High
**Affected Files:** All three parser families
**Affected Functions:** All three `parse()` methods

---

## P-02 — `extract_unit_from_text()` Duplicated Across Two Parser Files

**Description**
`extract_unit_from_text()` is defined identically in `numeric_matrix.py` (module-level, lines ~14–34) and `wide_to_long.py` (inner function, lines ~70–90).

**Root Cause:** No shared utility module. Architecture forbids cross-family imports but shared helpers belong in `parsing/base.py`.
**Impact:** Maintenance issue; divergence risk.
**Priority:** Low
**Affected Files:** `numeric_matrix.py`, `wide_to_long.py`, `parsing/base.py` (should host)

---

## P-03 — `clean_state_candidate()` Defined in Five Separate Files

**Description**
`clean_state_candidate()` (CID removal, slash/asterisk strip, lowercase) is duplicated identically in: `numeric_matrix.py`, `wide_to_long.py`, `narrative.py`, `hierarchy.py`, `block_segmentation.py`.

**Root Cause:** No shared text-cleaning utility extracted from these modules.
**Impact:** Maintenance/divergence risk across five files.
**Priority:** Low
**Affected Files:** All five files; `normalization/text_cleanup.py` (should host)

---

## P-04 — Year Fallback `"2026-27"` Hardcoded in Parsers

**Description**
Both `numeric_matrix.py` and `wide_to_long.py` fall back to `year = "2026-27"` when no year pattern is found. This is hardcoded and will produce incorrect data for any other PDF edition.

**Evidence**
- `numeric_matrix.py` lines ~176, ~252: `year = "2026-27"`
- `wide_to_long.py` line ~237: `year = "2026-27"`

**Root Cause:** Default year is not read from `config/pdf_profiles/cerc_ursi_v1.yaml` or parameter YAML.
**Impact:** Incorrect year tags for all year-undetected rows when processing other PDF editions.
**Priority:** High
**Affected Files:** `numeric_matrix.py`, `wide_to_long.py`, `config/pdf_profiles/cerc_ursi_v1.yaml`

---

## P-05 — Catalog Loaded from Disk Inside Every `parse()` Call

**Description**
All three parser families and `block_segmentation.py` call `get_config_loader()` and `load_catalogs()` inside their hot paths — catalog is deserialized from YAML on every invocation.

**Evidence**
- `numeric_matrix.py` lines ~112–128, `wide_to_long.py` lines ~114–128, `narrative.py` lines ~72–81, `block_segmentation.py` lines ~75–113 and ~189–195

**Root Cause:** Catalog is not cached or passed through the pipeline session config.
**Impact:** Performance overhead for batch processing.
**Priority:** Medium
**Affected Files:** All three parser families, `block_segmentation.py`, `config/loader.py`

---

# Category: Normalization Issues

---

## N-01 — Section Header Rows Not Distinguished from Data Rows

**Description**
`hierarchy.py → propagate_hierarchy()` assigns `RowLabel.DATA` to section-label rows in the Additional Surcharge table (e.g. `": ≤ 1.50"`, `"Low Additional Surcharge Level: ≤ Rs 1.50"`, `"Not Available for these states"`). There is no `RowLabel.SECTION_HEADER` type.

**Root Cause:** `domain/enums.py` does not define `SECTION_HEADER`. The hierarchy propagation has no section detection logic.
**Impact:** Section headers are parsed as data rows, producing spurious records (DQ-02).
**Priority:** High
**Affected Files:** `normalization/hierarchy.py`, `domain/enums.py`
**Affected Functions:** `propagate_hierarchy()`

---

## N-02 — State Forward-Fill Crosses Section Boundaries

**Description**
In Additional Surcharge, the state `"Uttarakhand"` (last state of the Low section) is forward-filled into the Medium section header rows (rows 21–22), making them appear as data rows for Uttarakhand.

**Evidence**
- `extraction/additional_surcharge/normalized.json` rows 21–22: `["Uttarakhand", ": > 1.50 2.00", ...]`

**Root Cause:** `propagate_hierarchy()` applies forward-fill unconditionally across all non-state rows with no section-boundary reset.
**Impact:** Wrong records created for Uttarakhand from section header rows; section context is corrupted.
**Priority:** High
**Affected Files:** `normalization/hierarchy.py`
**Affected Functions:** `propagate_hierarchy()`

---

## N-03 — DISCOM Aliases Hardcoded in `block_segmentation.py`

**Description**
`_create_block()` contains a hardcoded `aliases_map` dictionary with 40+ DISCOM mappings (lines ~80–99) instead of reading from `config/catalogs/utilities.yaml`.

**Root Cause:** Convenience; not driven by config system.
**Impact:** Any new DISCOM requires Python source modification rather than YAML update; violates extensibility principle.
**Priority:** Medium
**Affected Files:** `normalization/block_segmentation.py`, `config/catalogs/utilities.yaml`
**Affected Functions:** `_create_block()` (lines ~79–113)

---

# Category: Entity Recognition Issues

---

## ER-01 — `entity_recognition/` Module Undocumented and Architecturally Unplaced

**Description**
`src/table_scraper/entity_recognition/` (with `recognizer.py`, `matchers/`, `models.py`, `utils.py`) exists but is entirely absent from the architecture specification. Its role, inputs, outputs, and stage placement are undefined.

**Root Cause:** Module added during implementation without updating architecture documents.
**Impact:** Maintenance confusion; unclear ownership in stage graph; no data contracts defined.
**Priority:** Medium
**Affected Files:** `src/table_scraper/entity_recognition/` (all files), `software_architecture_design.md`, `data_contracts.md`

---

## ER-02 — `understanding/` Module Artifacts Written to Wrong Workspace Folder

**Description**
`src/table_scraper/understanding/` produces `header_tree.json`, `column_descriptors.json`, `annotated_table.json` but writes them to `parsing/{param}/` — wrong stage folder. Per the persistence matrix, `parsing/{param}/` should contain only `pattern.json`, `records.json`, `validation.json`.

**Evidence**
- `manifest.json` normalize stage artifact paths include `"parsing/cross_subsidy_surcharge/header_tree.json"`, `"parsing/cross_subsidy_surcharge/column_descriptors.json"`, `"parsing/cross_subsidy_surcharge/annotated_table.json"`
- Data contract persistence matrix: `parsing/{param}/` = `pattern.json` + `records.json` + `validation.json` only

**Root Cause:** Module outputs placed in wrong workspace path during implementation.
**Impact:** Workspace folder semantics violated; workspace validation tooling will not find or correctly interpret these artifacts.
**Priority:** Medium
**Affected Files:** `src/table_scraper/understanding/`, `src/table_scraper/pipeline/stages/`, `software_architecture_design.md`, `data_contracts.md`

---

## ER-03 — TGNPDCL / TGSPDCL vs TSNPDCL / TSSPDCL Alias Inconsistency

**Description**
Records emit `"TGNPDCL"` and `"TGSPDCL"` for Telangana utilities while `utilities.yaml` lists `"TSNPDCL"` and `"TSSPDCL"`.

**Evidence**
- `parsing/wheeling_charge/validation.json` utilities_covered: `"TGNPDCL"`, `"TGSPDCL"`
- `config/catalogs/utilities.yaml` lines 82–83: `TSSPDCL`, `TSNPDCL`

**Root Cause:** The PDF uses different abbreviations from the catalog; alias resolution is inconsistently applied.
**Impact:** Catalog joins fail for Telangana utilities.
**Priority:** Low
**Affected Files:** `config/catalogs/utilities.yaml`, `normalization/block_segmentation.py`

---

# Category: Validation Issues

---

## V-01 — `required_fields` Severity: Warning — Missing Fields Do Not Block Export

**Description**
The `required_fields` validation rule has `severity: "warning"` for all parameters. Records with missing required fields pass validation and are exported. Per the data contract, missing required fields must be a blocking error.

**Evidence**
- `parsing/transmission_charge/validation.json`: `required_fields` `passed: false`, `severity: "warning"`, `export_allowed: true`
- 8 records missing `long_medium_charge`, 9 missing `short_term_charge` — all exported

**Root Cause:** Severity misconfiguration in validation YAML or rule defaults.
**Impact:** Incomplete records reach the export layer unblocked; analysts receive knowingly deficient data.
**Priority:** High
**Affected Files:** `config/parsers/parameters/*.yaml`, `src/table_scraper/validation/runner.py`, `src/table_scraper/validation/rules/`

---

## V-02 — `state_validation` Severity: Warning — Invalid States Do Not Block Export

**Description**
`state_validation` rule has `severity: "warning"`. Invalid state names (e.g. `"State Level"`) do not block export.

**Evidence**
- `parsing/additional_surcharge/validation.json`: `state_validation` `passed: false`, `severity: "warning"`, `export_allowed: true`

**Root Cause:** Same as V-01.
**Impact:** Invalid entities reach the export layer.
**Priority:** Medium
**Affected Files:** Same as V-01

---

## V-03 — No Composite Key Deduplication Validation Rule

**Description**
The `duplicate_records` rule checks only `record_id` uniqueness, not semantic composite key uniqueness (`state + utility + year + voltage_level`). Himachal Pradesh duplicates pass validation with zero warnings.

**Evidence**
- `parsing/wheeling_charge/validation.json`: `duplicate_records` `passed: true`, `duplicate_ids: []`
- Semantic duplicates exist in records (F-07)

**Root Cause:** Composite key deduplication rule not implemented.
**Impact:** Silent duplicate records in export; inflated counts.
**Priority:** Medium
**Affected Files:** `src/table_scraper/validation/rules/`, `src/table_scraper/validation/runner.py`

---

## V-04 — Numeric Range Check Too Permissive for Additional Surcharge

**Description**
All parameters share `numeric_range: [0.0, 1000.0]`. For Additional Surcharge, values above ~5 Rs/kWh would be anomalous. The shared limit will not catch data errors specific to Additional Surcharge.

**Root Cause:** Per-parameter range configuration not implemented.
**Impact:** Parameter-specific anomaly detection is absent.
**Priority:** Low
**Affected Files:** `config/parsers/parameters/*.yaml`, `src/table_scraper/validation/rules/`

---

# Category: Export & Formatting Issues

---

## E-01 — Understanding Artifacts Written to `parsing/` Workspace Folder

**Description**
(See ER-02 above.) `annotated_table.json`, `column_descriptors.json`, `header_tree.json` are in `parsing/{param}/` — wrong folder per persistence matrix.

**Priority:** Low — Already documented under ER-02.

---

## E-02 — `"state_level"` Sentinel Appears in Exported Workbook

**Description**
Records with `utility: "state_level"` are exported to Excel as-is. This internal sentinel is not an analyst-facing term.

**Evidence**
- `parsing/transmission_charge/validation.json` utilities_covered: `"state_level"` listed as a utility
- Workbook will show `"state_level"` in Utility column

**Root Cause:** No display-name mapping in the exporter.
**Impact:** Non-standard internal string in analyst workbooks.
**Priority:** Low
**Affected Files:** `src/table_scraper/export/dataframe_builder.py`

---

## E-03 — Second Workbook `Cross_Subsidy_By_State.xlsx` Not Tracked in Manifest

**Description**
The export folder contains both `Regulatory_Parameter_Warehouse.xlsx` (51 KB) and `Cross_Subsidy_By_State.xlsx` (47 KB). Only the first is tracked in `manifest.json`. The second workbook is invisible to the manifest and workspace validation.

**Evidence**
- `manifest.json` stages.export.artifact_paths: `["Regulatory_Parameter_Warehouse.xlsx"]` only

**Root Cause:** The export stage produces a secondary workbook but does not register it in the manifest.
**Impact:** Incomplete manifest; second workbook cannot be audited by workspace tooling.
**Priority:** Medium
**Affected Files:** `src/table_scraper/export/excel_exporter.py`, `src/table_scraper/storage/workspace.py`

---

# Category: Maintainability Issues

---

## M-01 — `detect_state_in_row()` Duplicated in `hierarchy.py` and `block_segmentation.py`

**Description**
The function `detect_state_in_row()` with its exclusion set, fuzzy matching, and alias handling is defined identically in both files.

**Root Cause:** No shared state detection utility extracted from the two normalization modules.
**Impact:** Divergence risk; bug fixes must be applied in two places.
**Priority:** Medium
**Affected Files:** `normalization/hierarchy.py` (lines ~68–106), `normalization/block_segmentation.py` (lines ~205–244)

---

## M-02 — Manifest `version: 179` — Idempotency Not Working

**Description**
The workspace manifest shows `version: 179`, indicating the manifest was mutated 179 times. The pipeline is not correctly detecting completed stages and is re-running stages repeatedly.

**Evidence**
- `manifest.json` line 347: `"version": 179`

**Root Cause:** Stage-skip idempotency checks in `pipeline/runner.py` or `storage/workspace.py` are not working correctly.
**Impact:** Wasteful re-execution; idempotency is a stated architectural requirement.
**Priority:** Medium
**Affected Files:** `src/table_scraper/pipeline/runner.py`, `src/table_scraper/storage/workspace.py`

---

## M-03 — `user_selection: null` Despite Complete Pipeline Run

**Description**
`manifest.json` has `user_selection: null` even though all parameters have been fully processed through export. The `WorkspaceManifest.user_selection` field is not populated.

**Evidence**
- `manifest.json` line 346: `"user_selection": null`
- `stages.select.artifact_paths` references `discovery/user_selection.json` — not embedded

**Root Cause:** The select stage updates `stages.select` but does not populate `manifest.user_selection`.
**Impact:** Incomplete manifest; workspace validation cannot verify selection state.
**Priority:** Low
**Affected Files:** `src/table_scraper/storage/workspace.py`, select stage

---

# Category: Generalization Issues

---

## G-01 — No Parameter YAML Config for Column Maps (Transmission, Additional Surcharge)

**Description**
Architecture requires `config/parsers/parameters/*.yaml` to declare column maps, skip rules, and section patterns. Parsers for transmission_charge and additional_surcharge do not load column indices or structural rules from YAML — they use hardcoded logic.

**Root Cause:** Parameter YAML files were not completed or not integrated into parser logic.
**Impact:** Adding a new PDF edition or parameter requires Python code changes instead of YAML-only extension.
**Priority:** High
**Affected Files:** `config/parsers/parameters/transmission_charge.yaml` (missing/incomplete), `config/parsers/parameters/additional_surcharge.yaml` (missing/incomplete), `numeric_matrix.py`

---

## G-02 — No Golden File Regression Tests

**Description**
Architecture spec Section 12D specifies golden tests for each parser family. No golden `records.json` snapshots exist. Parser changes are unverifiable without running the full pipeline.

**Root Cause:** Tests not yet implemented.
**Impact:** No regression safety net; parser changes can silently break extraction.
**Priority:** High
**Affected Files:** `tests/fixtures/golden/` (missing), `tests/unit/`, `tests/integration/`

---

---

# Implementation TODO Checklist

Each item is keyed to a specific file and function.

---

### CRITICAL

- `[ ]` **TODO-01** — `numeric_matrix.py → NumericMatrixParser.parse()` additional_surcharge branch: Add `current_section` state machine. Detect section-header rows; include `section` in every emitted record's `fields` and `provenance`.

- `[ ]` **TODO-02** — `numeric_matrix.py → parse_additional_surcharge_value()`: Preserve period-qualified text in `additional_surcharge_text` field alongside extracted numeric. Capture all values for multi-value cells (e.g. `1.13 (Partial OA) / 1.53 (Full OA)`).

- `[ ]` **TODO-03** — `numeric_matrix.py → NumericMatrixParser.parse()` additional_surcharge branch: Emit records for "Not Available" states with `additional_surcharge: null` (or `"N/A"`) rather than skipping them. All 36 states/UTs must have a record.

- `[ ]` **TODO-04** — `wide_to_long.py → WideToLongParser.parse()` wheeling_charge branch: Rebuild the voltage-to-column mapping to correctly handle 3-column-wide voltage tiers. Map each voltage tier's label column to its value column(s) explicitly; remove the `c_idx ± 1` proximity heuristic.

- `[ ]` **TODO-05** — `storage/workspace.py` + pipeline stage files: Fix cross-parameter manifest path contamination. Reset artifact path list per-parameter before each stage run. Ensure `manifest.json` correctly scopes all `artifact_paths` to the current parameter.

- `[ ]` **TODO-06** — All parser `parse()` methods + pipeline stage config: Ensure `config.page_range` carries the actual PDF page range. Populate `source_pages` in records with real page numbers. Remove or convert the `pages = [1]` default fallback to an explicit error.

---

### HIGH

- `[ ]` **TODO-07** — `normalization/hierarchy.py → propagate_hierarchy()` + `domain/enums.py → RowLabel`: Add `SECTION_HEADER` enum value. Detect section-label rows (all data columns empty, col 0–1 contains threshold pattern or "Not Available" text). Assign `SECTION_HEADER` label and reset `current_state` at each section boundary.

- `[ ]` **TODO-08** — `normalization/block_segmentation.py → segment_state_blocks()` + `detect_state_in_row()`: Validate detected block `state` against canonical states catalog before creating a block. If the value is a known DISCOM, create a DISCOM-level block with parent state from context. Reject non-state, non-DISCOM values.

- `[ ]` **TODO-09** — `understanding/header_analyzer.py`: Fix multi-row merged-cell header reconstruction for wheeling charge. Strip numeric-only cell artifacts (`"11"`, `"33"`, `"66"`, `"132"`) from intermediate header rows before concatenating into column labels.

- `[ ]` **TODO-10** — `numeric_matrix.py → NumericMatrixParser.parse()` transmission_charge branch (lines 179–182): Replace hardcoded column index literals with values loaded from `config/parsers/parameters/transmission_charge.yaml`. Create the YAML file with `column_map` section.

- `[ ]` **TODO-11** — `numeric_matrix.py → NumericMatrixParser.parse()` transmission_charge branch (lines ~192–194): Preserve unit strings even when the associated charge value is absent. Emit unit alongside a null/empty charge, not suppress both.

- `[ ]` **TODO-12** — `numeric_matrix.py` + `wide_to_long.py` — year fallback block: Replace `year = "2026-27"` literal with value from `config/pdf_profiles/cerc_ursi_v1.yaml → default_year`.

- `[ ]` **TODO-13** — `normalization/hierarchy.py → propagate_hierarchy()`: Prevent state forward-fill from crossing section boundaries. When `current_section` changes (after TODO-07), reset `current_state`.

- `[ ]` **TODO-14** — `validation/rules/` + `config/parsers/parameters/*.yaml`: Change `required_fields` and `state_validation` rule severity from `"warning"` to `"error"`. Set `export_allowed: false` when these rules fail.

- `[ ]` **TODO-15** — `wide_to_long.py → WideToLongParser.parse()` wheeling_charge branch: Add semantic deduplication before appending a record. Check if an identical-field record already exists; log a warning and skip if duplicate.

- `[ ]` **TODO-16** — `wide_to_long.py → WideToLongParser.parse()` wheeling_charge branch (lines ~239–242): When `utility == "state_level"` and `row[0]` matches a canonical state name, keep `utility` as `"state_level"`. Only override with `row[0]` if it is a known DISCOM.

- `[ ]` **TODO-17** — `config/catalogs/states.yaml` + all parsers/normalizers: Standardize canonical state names. Either update catalog to use `.title()` forms (`"Jammu And Kashmir"`) or replace `.title()` with an exact catalog lookup. All record `state` values must exactly match catalog.

- `[ ]` **TODO-18** — `numeric_matrix.py → NumericMatrixParser.parse()` additional_surcharge branch: Add explicit skip logic for section-label rows before they can produce spurious records. A section-label row is identifiable by: state propagated in col 0, section text in col 1, no valid numeric charge in the data column.

- `[ ]` **TODO-19** — `config/parsers/parameters/additional_surcharge.yaml` + `config/parsers/parameters/transmission_charge.yaml`: Create or complete these files with `column_map`, `section_patterns`, `header_rows`, `state_column`, `state_location`, validation rule severity overrides, and `min_records`/`min_states`.

- `[ ]` **TODO-20** — `tests/fixtures/golden/` + `tests/unit/` + `tests/integration/`: Create golden `records.json` snapshots for each parser family. Implement pytest tests that run each parser against a fixture table and compare to the golden file.

---

### MEDIUM

- `[ ]` **TODO-21** — `numeric_matrix.py`, `wide_to_long.py`, `narrative.py` — parser `if/elif parameter_id` branches: Eliminate parameter-specific branches. Move all parameter-specific logic to YAML config. Parser reads config and behaves generically.

- `[ ]` **TODO-22** — `normalization/hierarchy.py` + `normalization/block_segmentation.py → detect_state_in_row()`: Extract the shared function to a single location (`normalization/text_cleanup.py` or `normalization/state_utils.py`). Both files import from the shared location.

- `[ ]` **TODO-23** — `validation/rules/`: Add composite key deduplication rule (checks `state + utility + year + voltage_level`). Register in all parameter YAML configs with `severity: "warning"`.

- `[ ]` **TODO-24** — `normalization/block_segmentation.py → _create_block()` (lines ~80–99): Remove hardcoded `aliases_map`. Load DISCOM aliases from `config/catalogs/utilities.yaml` (or a new `utility_aliases.yaml`).

- `[ ]` **TODO-25** — `config/loader.py → get_config_loader()` / `load_catalogs()`: Implement singleton caching. Load catalog once per process lifetime or pipeline session; pass catalog as parameter to all parsers and normalizers.

- `[ ]` **TODO-26** — `export/excel_exporter.py` + `storage/workspace.py`: Register all exported workbook paths in `manifest.json` including `Cross_Subsidy_By_State.xlsx`. Update manifest atomically after export completes.

- `[ ]` **TODO-27** — `software_architecture_design.md` + `data_contracts.md`: Document the `entity_recognition/` and `understanding/` modules. Define their stage placement, inputs/outputs, and data contracts for `header_tree.json`, `column_descriptors.json`, `annotated_table.json`. Update persistence matrix.

- `[ ]` **TODO-28** — `pipeline/stages/` (understanding stage): Move `header_tree.json`, `column_descriptors.json`, `annotated_table.json` artifacts to `extraction/{param}/` (or a new `understanding/{param}/` path). Update manifest to reflect correct paths.

- `[ ]` **TODO-29** — `storage/workspace.py` + select stage: Populate `manifest.user_selection` with the `UserSelection` object when select stage completes.

- `[ ]` **TODO-30** — `pipeline/runner.py` + `storage/workspace.py`: Investigate and fix stage-skip idempotency checks. Ensure completed stages are correctly detected and skipped. Manifest version count should grow only with actual stage re-runs.

---

### LOW

- `[ ]` **TODO-31** — `parsing/base.py`: Add `clean_state_candidate()` and `extract_unit_from_text()` as shared utilities. Remove the five and two duplicate definitions from parser/normalizer files respectively.

- `[ ]` **TODO-32** — `export/dataframe_builder.py`: Map `"state_level"` sentinel to analyst-facing display label (`"State Aggregate"` or empty) before writing to Excel.

- `[ ]` **TODO-33** — `config/catalogs/utilities.yaml`: Add `"Arunachal PD"` as alias for `"DoP Arunachal"`. Add `"TGNPDCL"` as alias for `"TSNPDCL"`, `"TGSPDCL"` as alias for `"TSSPDCL"`. Implement utility alias resolution parallel to state alias resolution.

- `[ ]` **TODO-34** — `normalization/block_segmentation.py → _create_block()`: Pass the already-loaded catalog from `segment_state_blocks()` as a parameter to `_create_block()` to avoid redundant catalog loading.

- `[ ]` **TODO-35** — `config/parsers/parameters/*.yaml` (all parameters): Add per-parameter `min_value` / `max_value` for the numeric range validation rule (e.g. Additional Surcharge max ~10 Rs/kWh vs Transmission Charge max ~500,000 Rs/MW/month).

---

*Total issues documented: 35 TODOs across 10 categories.*
*Critical: 6 | High: 14 | Medium: 10 | Low: 5*

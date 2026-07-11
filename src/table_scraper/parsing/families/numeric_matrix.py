"""Numeric matrix parser family — transmission and charge matrices."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from table_scraper.domain.enums import ParseStatus, ParserFamily, TablePattern, RowLabel
from table_scraper.domain.models import NormalizedTable, ParseResult, ParsedRecord, StateBlock
from table_scraper.parsing.base import BaseParser, parse_float, generate_record_id


from table_scraper.parsing.unit_utils import extract_unit_from_text


def parse_additional_surcharge_value(val_str: str) -> float | None:
    val_clean = val_str.strip().lower()
    if val_clean in ("nil", "zero", "0"):
        return 0.0
    if val_clean in ("n/a", "na", "not applicable", "not available", "--"):
        return None
        
    decimal_matches = re.findall(r"\b\d+\.\d+\b", val_str)
    if decimal_matches:
        return float(decimal_matches[0])
        
    cleaned = re.sub(r"[^\d\.]", "", val_str)
    if cleaned:
        try:
            return float(cleaned)
        except ValueError:
            pass
            
    return None


class NumericMatrixParser(BaseParser):
    """Parser for state/utility x year/charge numeric matrices."""

    @property
    def parser_id(self) -> str:
        return "numeric_matrix_v1"

    @property
    def pattern(self) -> TablePattern:
        return TablePattern.NUMERIC_MATRIX

    @property
    def parser_family(self) -> ParserFamily:
        return ParserFamily.NUMERIC_MATRIX

    def parse(
        self,
        table: NormalizedTable,
        blocks: list[StateBlock] | None,
        config: Any,
    ) -> ParseResult:
        """Parse numeric matrix grid structure into long-format records."""
        records: list[ParsedRecord] = []
        warnings: list[str] = []

        # Resolve header size
        header_rows_count = 1
        if table.row_labels:
            header_rows_count = sum(1 for label in table.row_labels if label == RowLabel.HEADER)
        header_rows_count = max(1, header_rows_count)

        # Parse and reconstruct column headers
        headers: list[str] = []
        num_cols = table.column_count
        for col_idx in range(num_cols):
            header_parts = []
            for r_idx in range(header_rows_count):
                if r_idx < len(table.rows) and col_idx < len(table.rows[r_idx]):
                    cell = table.rows[r_idx][col_idx].strip()
                    if cell:
                        header_parts.append(cell)
            headers.append(" - ".join(header_parts) if header_parts else f"Col {col_idx}")

        # Resolve page references
        pages = [1]
        if hasattr(config, "page_range") and config.page_range:
            start = getattr(config.page_range, "start_page", 1)
            end = getattr(config.page_range, "end_page", start)
            pages = list(range(start, end + 1))
        elif isinstance(config, dict) and "page_range" in config and config["page_range"]:
            pr = config["page_range"]
            start = pr.get("start_page", 1) if isinstance(pr, dict) else getattr(pr, "start_page", 1)
            end = pr.get("end_page", start) if isinstance(pr, dict) else getattr(pr, "end_page", start)
            pages = list(range(start, end + 1))

        # Load catalogs for matching states
        states_map = {}
        state_aliases = {}
        all_discoms = []
        try:
            from table_scraper.config.loader import get_config_loader
            loader = get_config_loader()
            catalogs = loader.load_catalogs()
            states_map = {s.lower(): s for s in catalogs.states.states}
            state_aliases = {k.lower(): v.lower() for k, v in catalogs.state_aliases.aliases.items()}
            for state_name, discom_list in catalogs.utilities.utilities.items():
                for discom in discom_list:
                    all_discoms.append(discom)
        except Exception:
            pass

        from table_scraper.normalization.text_cleanup import clean_state_candidate

        current_state = None

        # ----------------------------------------------------
        # Specialized Parser: Transmission Charge
        # ----------------------------------------------------
        if table.parameter_id == "transmission_charge":
            from table_scraper.config.loader import load_parameter_config
            param_cfg = load_parameter_config(table.parameter_id)
            col_map = {}
            if hasattr(param_cfg, "extras") and isinstance(param_cfg.extras, dict):
                col_map = param_cfg.extras.get("column_map", {})
            elif isinstance(param_cfg, dict) and "column_map" in param_cfg:
                col_map = param_cfg["column_map"]

            table_struct = param_cfg.extras.get("table_structure", {}) if hasattr(param_cfg, "extras") else {}
            default_year = table_struct.get("default_year", "2026-27") if isinstance(table_struct, dict) else "2026-27"

            # Parse rows
            raw_records = []
            for r_idx in range(header_rows_count, len(table.rows)):
                row = table.rows[r_idx]
                if not row or all(c.strip() == "" for c in row):
                    continue

                col0_clean = clean_state_candidate(row[0])
                col1_clean = clean_state_candidate(row[1]) if len(row) > 1 else ""

                state = None
                utility = "state_level"

                if col1_clean in states_map:
                    state = states_map[col1_clean]
                    utility = row[0].strip()
                elif col1_clean in state_aliases:
                    alias_target = state_aliases[col1_clean]
                    state = states_map.get(alias_target, alias_target.title())
                    utility = row[0].strip()
                elif col0_clean in states_map:
                    state = states_map[col0_clean]
                    utility = "state_level"
                elif col0_clean in state_aliases:
                    alias_target = state_aliases[col0_clean]
                    state = states_map.get(alias_target, alias_target.title())
                    utility = "state_level"

                if not state:
                    state = current_state if current_state else "State Level"
                    utility = row[0].strip()
                else:
                    current_state = state

                # Skip header repeating rows
                if "states" in row[0].lower() or "applicable" in row[0].lower():
                    continue

                # Parse year index and dynamic offsets
                y_idx = None
                for idx, cell in enumerate(row):
                    if re.match(r"\b20\d{2}-\d{2}\b", cell.strip()):
                        y_idx = idx
                        break

                if y_idx is None:
                    continue

                year = row[y_idx].strip()

                # Collect non-empty data cells after Year cell along with their original column indices
                data_cells = []
                for col_idx in range(y_idx + 1, len(row)):
                    cell = row[col_idx].strip()
                    if cell:
                        data_cells.append((cell, col_idx))
                # Pad to at least 4 items
                while len(data_cells) < 4:
                    data_cells.append(("", y_idx + 1))

                raw_lm_charge, lm_col = data_cells[0]
                raw_lm_unit, lm_unit_col = data_cells[1]
                raw_st_charge, st_col = data_cells[2]
                raw_st_unit, st_unit_col = data_cells[3]

                long_medium_charge = parse_float(raw_lm_charge, r_idx, lm_col)
                short_term_charge = parse_float(raw_st_charge, r_idx, st_col)

                if long_medium_charge is None and short_term_charge is None:
                    continue

                record_fields = {
                    "state": state,
                    "utility": utility,
                    "year": year,
                    "long_medium_charge": long_medium_charge if long_medium_charge is not None else "",
                    "long_medium_unit": extract_unit_from_text(raw_lm_unit, "Rs/MW/month") if raw_lm_unit else "",
                    "short_term_charge": short_term_charge if short_term_charge is not None else "",
                    "short_term_unit": extract_unit_from_text(raw_st_unit, "Rs/kWh") if raw_st_unit else "",
                }

                rec_id = generate_record_id(
                    table.parameter_id,
                    state,
                    utility,
                    f"{year}:{r_idx}",
                )

                record = ParsedRecord(
                    record_id=rec_id,
                    parameter_id=table.parameter_id,
                    fields=record_fields,
                    source_pages=pages,
                    source_rows=[r_idx],
                    parser_id=self.parser_id,
                    parser_version="1.0.0",
                    confidence=1.0,
                    provenance={"row_index": r_idx},
                )
                raw_records.append(record)

            # De-duplicate state_level duplicate rows when a named utility record is present
            from collections import defaultdict
            groups = defaultdict(list)
            for r in raw_records:
                key = (r.fields["state"], r.fields["year"])
                groups[key].append(r)

            for key, group in groups.items():
                has_named_utility = any(r.fields["utility"] != "state_level" for r in group)
                if has_named_utility:
                    for r in group:
                        if r.fields["utility"] == "state_level":
                            match = False
                            for other in group:
                                if other.fields["utility"] != "state_level":
                                    if (other.fields["long_medium_charge"] == r.fields["long_medium_charge"] and
                                        other.fields["short_term_charge"] == r.fields["short_term_charge"]):
                                        match = True
                                        break
                            if match:
                                continue
                        records.append(r)
                else:
                    records.extend(group)

        # ----------------------------------------------------
        # Specialized Parser: Additional Surcharge
        # ----------------------------------------------------
        elif table.parameter_id == "additional_surcharge":
            from table_scraper.config.loader import load_parameter_config
            param_cfg = load_parameter_config(table.parameter_id)
            table_struct = param_cfg.extras.get("table_structure", {}) if hasattr(param_cfg, "extras") else {}
            default_year = table_struct.get("default_year", "2026-27") if isinstance(table_struct, dict) else "2026-27"

            current_section = "Low"
            for r_idx in range(header_rows_count, len(table.rows)):
                row = table.rows[r_idx]
                if not row or all(c.strip() == "" for c in row):
                    continue

                # Skip header/section rows and update section
                if table.row_labels and table.row_labels[r_idx] == RowLabel.SECTION_HEADER:
                    col1_lower = row[1].lower() if len(row) > 1 else ""
                    if "low" in col1_lower:
                        current_section = "Low"
                    elif "medium" in col1_lower:
                        current_section = "Medium"
                    elif "not available" in col1_lower:
                        current_section = "Not Available"
                    continue

                state = None
                for col_idx in (0, 1):
                    if col_idx < len(row):
                        cleaned = clean_state_candidate(row[col_idx])
                        if cleaned in states_map:
                            state = states_map[cleaned]
                            break
                        if cleaned in state_aliases:
                            alias_target = state_aliases[cleaned]
                            state = states_map.get(alias_target, alias_target.title())
                            break

                if not state:
                    state = current_state if current_state else "State Level"
                else:
                    current_state = state

                # Skip header rows
                if "states" in row[0].lower() or "additional surcharge" in row[0].lower():
                    continue

                year = None
                for cell in row[1:4]:
                    if re.match(r"\b20\d{2}-\d{2}\b", cell):
                        year = cell.strip()
                        break
                if not year:
                    year = default_year

                val_text = ""
                for cell in reversed(row):
                    if cell.strip() and not re.match(r"\b20\d{2}-\d{2}\b", cell) and cell.strip().lower() not in states_map and cell.strip().lower() not in state_aliases:
                        val_text = cell.strip()
                        break

                # Check for multi-value split first (F-07)
                split_results = []
                matches = list(re.finditer(r"(\d+(?:\.\d+)?)\s*\(([^)]+)\)", val_text))
                if len(matches) > 1:
                    first_start = matches[0].start()
                    prefix = val_text[:first_start].strip()
                    for match in matches:
                        v_str = match.group(1)
                        qual = match.group(2)
                        sub_text = f"{prefix} {v_str} ({qual})" if prefix else f"{v_str} ({qual})"
                        sub_text = re.sub(r"\s+", " ", sub_text).strip()
                        try:
                            split_results.append((float(v_str), sub_text))
                        except ValueError:
                            pass

                if split_results:
                    for sub_val, sub_text in split_results:
                        record_fields = {
                            "state": state,
                            "year": year,
                            "additional_surcharge": sub_val,
                            "additional_surcharge_text": sub_text,
                            "section": current_section
                        }
                        rec_id = generate_record_id(
                            table.parameter_id,
                            state,
                            "state_level",
                            f"{year}:{current_section}:{sub_text}",
                        )
                        record = ParsedRecord(
                            record_id=rec_id,
                            parameter_id=table.parameter_id,
                            fields=record_fields,
                            source_pages=pages,
                            source_rows=[r_idx],
                            parser_id=self.parser_id,
                            parser_version="1.0.0",
                            confidence=1.0,
                            provenance={"row_index": r_idx},
                        )
                        records.append(record)
                    continue

                val = parse_additional_surcharge_value(val_text)
                
                # Handle NA state records (TODO-03) and multi-value/period qualified text (TODO-02)
                if val is None:
                    val_clean = val_text.strip().lower()
                    is_na = val_clean in ("n/a", "na", "not applicable", "not available", "--", "nil", "zero", "0")
                    if is_na and state and state != "State Level":
                        val = 0.0 if val_clean in ("nil", "zero", "0") else "N/A"
                    else:
                        continue

                record_fields = {
                    "state": state,
                    "year": year,
                    "additional_surcharge": val,
                    "additional_surcharge_text": val_text,
                    "section": current_section
                }

                rec_id = generate_record_id(
                    table.parameter_id,
                    state,
                    "state_level",
                    f"{year}:{current_section}:{r_idx}",
                )

                record = ParsedRecord(
                    record_id=rec_id,
                    parameter_id=table.parameter_id,
                    fields=record_fields,
                    source_pages=pages,
                    source_rows=[r_idx],
                    parser_id=self.parser_id,
                    parser_version="1.0.0",
                    confidence=1.0,
                    provenance={"row_index": r_idx},
                )
                records.append(record)

        # ----------------------------------------------------
        # Fallback Parser: Standard Numeric Matrix
        # ----------------------------------------------------
        else:
            for r_idx in range(header_rows_count, len(table.rows)):
                row = table.rows[r_idx]
                if not row:
                    continue

                state = row[0].strip() if row else "State Level"
                utility = "state_level"

                for discom_name in all_discoms:
                    if discom_name.lower() in state.lower():
                        utility = discom_name
                        break

                for c_idx in range(1, len(row)):
                    cell_val = row[c_idx]
                    val = parse_float(cell_val, r_idx, c_idx)
                    if val is None:
                        continue

                    col_header = headers[c_idx]
                    unit = extract_unit_from_text(col_header, "Rs/kWh")

                    record_fields = {
                        "state": state,
                        "utility": utility,
                        "consumer_category": col_header,
                        "consumer_subcategory": "",
                        "voltage_level": "all",
                        "charge_value": val,
                        "charge_unit": unit,
                        "effective_date": "",
                    }

                    rec_id = generate_record_id(
                        table.parameter_id,
                        state,
                        utility,
                        f"{col_header}:{r_idx}:{c_idx}",
                    )

                    record = ParsedRecord(
                        record_id=rec_id,
                        parameter_id=table.parameter_id,
                        fields=record_fields,
                        source_pages=pages,
                        source_rows=[r_idx],
                        parser_id=self.parser_id,
                        parser_version="1.0.0",
                        confidence=1.0,
                        provenance={"col_index": c_idx, "row_index": r_idx},
                    )
                    records.append(record)

        return ParseResult(
            parameter_id=table.parameter_id,
            records=records,
            record_count=len(records),
            parser_id=self.parser_id,
            pattern=self.pattern,
            parsed_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            status=ParseStatus.SUCCESS,
            parser_family=self.parser_family,
            parse_metadata={"rows_processed": len(table.rows), "records_emitted": len(records)},
            classification=None,
            input_table_hash=table.source_merged_table_hash,
            state_blocks_used=[],
            errors=[],
            warnings=warnings,
        )


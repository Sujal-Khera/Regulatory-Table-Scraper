"""Numeric matrix parser family — transmission and charge matrices."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from table_scraper.domain.enums import ParseStatus, ParserFamily, TablePattern, RowLabel
from table_scraper.domain.models import NormalizedTable, ParseResult, ParsedRecord, StateBlock
from table_scraper.parsing.base import BaseParser, parse_float, generate_record_id


def extract_unit_from_text(text: str, default: str = "Rs/kWh") -> str:
    text_lower = text.lower()
    if "paise/kwh" in text_lower or "p/kwh" in text_lower:
        return "paise/kWh"
    if "rs/kw/month" in text_lower or "rs/kw/m" in text_lower or "rs./kw/month" in text_lower:
        return "Rs/kW/month"
    if "rs/kva/month" in text_lower or "rs/kva/m" in text_lower:
        return "Rs/kVA/month"
    if "rs/mw/month" in text_lower or "rs/mw/m" in text_lower:
        return "Rs/MW/month"
    if "rs/mw/day" in text_lower or "rs/mw/d" in text_lower:
        return "Rs/MW/day"
    if "rs/mwh" in text_lower:
        return "Rs/MWh"
    if "%" in text_lower or "percent" in text_lower:
        return "%"
    if "rs cr" in text_lower or "rs. cr" in text_lower:
        return "Rs Cr."
    if "rs/kwh" in text_lower or "rs./kwh" in text_lower:
        return "Rs/kWh"
    return default


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

        # Load catalogs for matching states
        states = set()
        state_aliases = {}
        all_discoms = []
        try:
            from table_scraper.config.loader import get_config_loader
            loader = get_config_loader()
            catalogs = loader.load_catalogs()
            states = set(s.lower() for s in catalogs.states.states)
            state_aliases = {k.lower(): v.lower() for k, v in catalogs.state_aliases.aliases.items()}
            for state_name, discom_list in catalogs.utilities.utilities.items():
                for discom in discom_list:
                    all_discoms.append(discom)
        except Exception:
            pass

        def clean_state_candidate(val: str) -> str:
            val = re.sub(r"\(cid:\d+\)", "", val)
            val = val.replace("/", "").replace("*", "").strip()
            return val.lower()

        current_state = None

        # ----------------------------------------------------
        # Specialized Parser: Transmission Charge
        # ----------------------------------------------------
        if table.parameter_id == "transmission_charge":
            for r_idx in range(header_rows_count, len(table.rows)):
                row = table.rows[r_idx]
                if not row or all(c.strip() == "" for c in row):
                    continue

                col0_clean = clean_state_candidate(row[0])
                col1_clean = clean_state_candidate(row[1]) if len(row) > 1 else ""

                state = None
                utility = "state_level"

                if col1_clean in states:
                    state = col1_clean.title()
                    utility = row[0].strip()
                elif col1_clean in state_aliases:
                    state = state_aliases[col1_clean].title()
                    utility = row[0].strip()
                elif col0_clean in states:
                    state = col0_clean.title()
                    utility = "state_level"
                elif col0_clean in state_aliases:
                    state = state_aliases[col0_clean].title()
                    utility = "state_level"

                if not state:
                    state = current_state if current_state else "State Level"
                    utility = row[0].strip()
                else:
                    current_state = state

                # Skip header repeating rows
                if "states" in row[0].lower() or "applicable" in row[0].lower():
                    continue

                # Parse year
                year = None
                for cell in row[1:4]:
                    if re.match(r"\b20\d{2}-\d{2}\b", cell):
                        year = cell.strip()
                        break
                if not year:
                    year = "2026-27"

                # Parse values and units
                long_medium_charge = parse_float(row[4], r_idx, 4) if len(row) > 4 else None
                long_medium_unit = row[6].strip() if len(row) > 6 else ""
                short_term_charge = parse_float(row[8], r_idx, 8) if len(row) > 8 else None
                short_term_unit = row[10].strip() if len(row) > 10 else ""

                if long_medium_charge is None and short_term_charge is None:
                    continue

                record_fields = {
                    "state": state,
                    "utility": utility,
                    "year": year,
                    "long_medium_charge": long_medium_charge if long_medium_charge is not None else "",
                    "long_medium_unit": extract_unit_from_text(long_medium_unit, "Rs/MW/month") if (long_medium_unit and long_medium_charge is not None) else "",
                    "short_term_charge": short_term_charge if short_term_charge is not None else "",
                    "short_term_unit": extract_unit_from_text(short_term_unit, "Rs/kWh") if (short_term_unit and short_term_charge is not None) else "",
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
                records.append(record)

        # ----------------------------------------------------
        # Specialized Parser: Additional Surcharge
        # ----------------------------------------------------
        elif table.parameter_id == "additional_surcharge":
            for r_idx in range(header_rows_count, len(table.rows)):
                row = table.rows[r_idx]
                if not row or all(c.strip() == "" for c in row):
                    continue

                state = None
                for col_idx in (0, 1):
                    if col_idx < len(row):
                        cleaned = clean_state_candidate(row[col_idx])
                        if cleaned in states:
                            state = cleaned.title()
                            break
                        if cleaned in state_aliases:
                            state = state_aliases[cleaned].title()
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
                    year = "2026-27"

                val_text = ""
                for cell in reversed(row):
                    if cell.strip() and not re.match(r"\b20\d{2}-\d{2}\b", cell) and cell.strip().title() not in states and cell.strip().title() not in state_aliases.values():
                        val_text = cell.strip()
                        break

                val = parse_additional_surcharge_value(val_text)
                if val is None:
                    continue

                record_fields = {
                    "state": state,
                    "year": year,
                    "additional_surcharge": val,
                }

                rec_id = generate_record_id(
                    table.parameter_id,
                    state,
                    "state_level",
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


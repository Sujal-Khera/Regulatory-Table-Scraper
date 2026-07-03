"""Wide-to-long parser family — wheeling voltage columns."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from table_scraper.domain.enums import ParseStatus, ParserFamily, TablePattern, RowLabel
from table_scraper.domain.models import NormalizedTable, ParseResult, ParsedRecord, StateBlock
from table_scraper.parsing.base import BaseParser, parse_float, generate_record_id


class WideToLongParser(BaseParser):
    """Parser that expands wide voltage/category columns to long-format records."""

    @property
    def parser_id(self) -> str:
        return "wide_to_long_v1"

    @property
    def pattern(self) -> TablePattern:
        return TablePattern.WIDE_TABLE

    @property
    def parser_family(self) -> ParserFamily:
        return ParserFamily.WIDE_TO_LONG

    def parse(
        self,
        table: NormalizedTable,
        blocks: list[StateBlock] | None,
        config: Any,
    ) -> ParseResult:
        """Melt wide category/voltage columns into normalized long-format records."""
        records: list[ParsedRecord] = []
        warnings: list[str] = []

        # Resolve header size
        header_rows_count = 1
        if table.row_labels:
            header_rows_count = sum(1 for label in table.row_labels if label == RowLabel.HEADER)
        header_rows_count = max(1, header_rows_count)

        # Reconstruct column headers
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

        # Helper to extract unit
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

        # Helper to extract voltage level
        def _extract_voltage(header: str) -> str:
            hl = header.lower()
            if "eht" in hl or "extra high" in hl:
                return "EHT"
            if "lt" in hl or "low tension" in hl:
                return "LT"
            if "ht" in hl or "high tension" in hl:
                m = re.search(r"\b(\d+)\s*kv\b", hl)
                if m:
                    return f"HT - {m.group(1)} kV"
                return "HT"
            m = re.search(r"\b(\d+)\s*kv\b", hl)
            if m:
                return f"{m.group(1)} kV"
            return "all"

        # Helper to extract year label
        def _extract_year(header: str) -> str | None:
            m = re.search(r"\b(20\d{2}-\d{2})\b", header)
            return m.group(1) if m else None

        # Load catalogs
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

        # ----------------------------------------------------
        # Specialized Parser: Wheeling Charge
        # ----------------------------------------------------
        if table.parameter_id == "wheeling_charge":
            current_state = None
            current_utility = "state_level"
            
            # Step 1: Scan header rows to detect column positions of each voltage level
            voltage_columns = {}  # col_idx -> voltage_level_name
            voltage_keywords = {
                "below 11": "Below 11 kV",
                "lt": "Below 11 kV",
                "11 kv": "11 kV",
                "33 kv": "33 kV",
                "66 kv": "66 kV",
                "132 kv": "132 kV",
                "200 kv": "220 kV & Above",
                "220 kv": "220 kV & Above",
                "above": "220 kV & Above"
            }
            
            for r_idx in range(header_rows_count):
                if r_idx < len(table.rows):
                    for c_idx in range(len(table.rows[r_idx])):
                        cell = table.rows[r_idx][c_idx].strip().lower()
                        if not cell:
                            continue
                        for kw, v_name in voltage_keywords.items():
                            if kw in cell:
                                voltage_columns[c_idx] = v_name
                                break
                                
            # Default mapping fallback if header scan failed to detect any voltage levels
            if not voltage_columns:
                for i, v_name in enumerate(["Below 11 kV", "11 kV", "33 kV", "66 kV", "132 kV", "220 kV & Above"]):
                    voltage_columns[2 + i] = v_name

            for r_idx in range(header_rows_count, len(table.rows)):
                row = table.rows[r_idx]
                if not row or all(c.strip() == "" for c in row):
                    continue

                # Scan state updates
                state_found = None
                for col_idx in (0, 1):
                    if col_idx < len(row):
                        cleaned = clean_state_candidate(row[col_idx])
                        if cleaned in states:
                            state_found = cleaned.title()
                            break
                        if cleaned in state_aliases:
                            state_found = state_aliases[cleaned].title()
                            break
                if state_found:
                    if current_state != state_found:
                        current_state = state_found
                        current_utility = "state_level"

                # Scan utility updates in the row text
                for col_idx in (0, 1):
                    if col_idx < len(row):
                        cell_text = row[col_idx].strip()
                        for discom_name in all_discoms:
                            if discom_name.lower() in cell_text.lower():
                                current_utility = discom_name
                                break

                # Check if the row has any values matching our columns
                has_values = False
                for c_idx in range(2, len(row)):
                    cell = row[c_idx]
                    v_name = None
                    if c_idx in voltage_columns:
                        v_name = voltage_columns[c_idx]
                    elif (c_idx - 1) in voltage_columns:
                        v_name = voltage_columns[c_idx - 1]
                    elif (c_idx + 1) in voltage_columns:
                        v_name = voltage_columns[c_idx + 1]
                        
                    if v_name is not None and parse_float(cell, r_idx, c_idx) is not None:
                        has_values = True
                        break
                if not has_values:
                    continue

                year = ""
                category = "General"
                
                r1_clean = row[1].strip().lower() if len(row) > 1 else ""
                if r1_clean in ("ht", "lt") or "tension" in r1_clean:
                    year = row[2].strip() if len(row) > 2 else ""
                    category = r1_clean.upper()
                else:
                    year = row[1].strip() if len(row) > 1 else ""

                if not re.match(r"\b20\d{2}-\d{2}\b", year):
                    for cell in row:
                        m = re.search(r"\b(20\d{2}-\d{2})\b", cell)
                        if m:
                            year = m.group(1)
                            break
                    if not re.match(r"\b20\d{2}-\d{2}\b", year):
                        year = "2026-27"

                state = current_state if current_state else "State Level"
                utility = current_utility
                if utility == "state_level" and len(row) > 0 and row[0].strip() and row[0].strip().title() not in states:
                    utility = row[0].strip()

                # Parse and melt voltage columns
                for c_idx in range(2, len(row)):
                    cell_val = row[c_idx]
                    val = parse_float(cell_val, r_idx, c_idx)
                    if val is None:
                        continue

                    v_name = None
                    if c_idx in voltage_columns:
                        v_name = voltage_columns[c_idx]
                    elif (c_idx - 1) in voltage_columns:
                        v_name = voltage_columns[c_idx - 1]
                    elif (c_idx + 1) in voltage_columns:
                        v_name = voltage_columns[c_idx + 1]

                    if v_name is None:
                        continue

                    # Extract unit context
                    unit = "Rs/kWh"
                    for cell in row:
                        if "rs" in cell.lower() or "mw" in cell.lower():
                            unit = extract_unit_from_text(cell, "Rs/kWh")
                            break

                    record_fields = {
                        "state": state,
                        "utility": utility,
                        "year": year,
                        "voltage_level": v_name,
                        "wheeling_charge": val,
                        "charge_unit": unit,
                    }

                    rec_id = generate_record_id(
                        table.parameter_id,
                        state,
                        utility,
                        f"{category}:{v_name}:{year}:{r_idx}:{c_idx}",
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

        # ----------------------------------------------------
        # Fallback Parser: Melt wide columns into long format
        # ----------------------------------------------------
        else:
            # Determine start of data columns
            data_col_start = 1
            if num_cols > 2 and "category" in headers[1].lower():
                data_col_start = 2

            for r_idx in range(header_rows_count, len(table.rows)):
                row = table.rows[r_idx]
                if not row:
                    continue

                state = row[0].strip() if row else "State Level"
                utility = "state_level"

                category = row[0].strip()
                subcategory = row[1].strip() if data_col_start > 1 and len(row) > 1 else ""
                for discom_name in all_discoms:
                    if discom_name.lower() in category.lower():
                        utility = discom_name
                        break

                for c_idx in range(data_col_start, len(row)):
                    cell_val = row[c_idx]
                    val = parse_float(cell_val, r_idx, c_idx)
                    if val is None:
                        continue

                    col_header = headers[c_idx]
                    voltage = _extract_voltage(col_header)
                    year = _extract_year(col_header)
                    unit = extract_unit_from_text(col_header, "Rs/kWh")

                    record_fields = {
                        "state": state,
                        "utility": utility,
                        "consumer_category": category,
                        "consumer_subcategory": subcategory,
                        "voltage_level": voltage,
                        "charge_value": val,
                        "charge_unit": unit,
                        "effective_date": "",
                    }
                    if year:
                        record_fields["year_label"] = year

                    rec_id = generate_record_id(
                        table.parameter_id,
                        state,
                        utility,
                        f"{category}:{subcategory}:{voltage}:{year or ''}:{r_idx}:{c_idx}",
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



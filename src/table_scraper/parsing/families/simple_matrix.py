"""Simple matrix parser family — flat category x utility grids."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from table_scraper.domain.enums import ParseStatus, ParserFamily, TablePattern, RowLabel
from table_scraper.domain.models import NormalizedTable, ParseResult, ParsedRecord, StateBlock
from table_scraper.parsing.base import BaseParser, parse_float, generate_record_id


class SimpleMatrixParser(BaseParser):
    """Parser for flat category x utility column grids within a state block."""

    @property
    def parser_id(self) -> str:
        return "simple_matrix_v1"

    @property
    def pattern(self) -> TablePattern:
        return TablePattern.SIMPLE_MATRIX

    @property
    def parser_family(self) -> ParserFamily:
        return ParserFamily.SIMPLE_MATRIX

    def parse(
        self,
        table: NormalizedTable,
        blocks: list[StateBlock] | None,
        config: Any,
    ) -> ParseResult:
        """Parse flat category-utility matrices into normalized records.

        Resolves category labels, maps column headers to utility names, and
        emits canonical long-format records.
        """
        records: list[ParsedRecord] = []
        warnings: list[str] = []

        # Resolve header size
        header_rows_count = 1
        if table.row_labels:
            header_rows_count = sum(1 for label in table.row_labels if label == RowLabel.HEADER)
        header_rows_count = max(1, header_rows_count)

        # Reconstruct headers
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

        # Resolve target state from profile config
        state = "State Level"
        if hasattr(config, "profile") and config.profile:
            state = getattr(config.profile, "state_name", "State Level")
        elif isinstance(config, dict) and "profile" in config:
            profile = config["profile"]
            if isinstance(profile, dict):
                state = profile.get("state_name", "State Level")

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

        # Iterate rows
        for r_idx in range(header_rows_count, len(table.rows)):
            row = table.rows[r_idx]
            if not row:
                continue

            category = row[0].strip() if row else "General"
            utility = "state_level"

            for c_idx in range(1, len(row)):
                cell_val = row[c_idx]
                val = parse_float(cell_val, r_idx, c_idx)
                if val is None:
                    continue

                col_header = headers[c_idx]
                utility = col_header

                # Attempt canonical utility name mapping
                try:
                    from table_scraper.config.loader import get_config_loader
                    loader = get_config_loader()
                    catalogs = loader.load_catalogs()
                    for u in catalogs.utilities.utilities:
                        if u.name.lower() in col_header.lower():
                            utility = u.name
                            break
                    for u in catalogs.utilities.utilities:
                        if u.name.lower() in category.lower():
                            utility = u.name
                            break
                except Exception:
                    pass

                from .numeric_matrix import extract_unit_from_text
                record_fields = {
                    "state": state,
                    "utility": utility,
                    "consumer_category": category,
                    "consumer_subcategory": "",
                    "voltage_level": "all",
                    "charge_value": val,
                    "charge_unit": extract_unit_from_text(col_header, "Rs/kWh"),
                    "effective_date": "",
                }

                rec_id = generate_record_id(
                    table.parameter_id,
                    state,
                    utility,
                    f"{category}:{utility}:{r_idx}:{c_idx}",
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


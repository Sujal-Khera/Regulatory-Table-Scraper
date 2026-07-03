"""Key-value parser family — metric/value pair layouts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from table_scraper.domain.enums import ParseStatus, ParserFamily, TablePattern, RowLabel
from table_scraper.domain.models import NormalizedTable, ParseResult, ParsedRecord, StateBlock
from table_scraper.parsing.base import BaseParser, parse_float, generate_record_id


class KeyValueParser(BaseParser):
    """Parser for simple metric/value table layouts."""

    @property
    def parser_id(self) -> str:
        return "key_value_v1"

    @property
    def pattern(self) -> TablePattern:
        return TablePattern.KEY_VALUE

    @property
    def parser_family(self) -> ParserFamily:
        return ParserFamily.KEY_VALUE

    def parse(
        self,
        table: NormalizedTable,
        blocks: list[StateBlock] | None,
        config: Any,
    ) -> ParseResult:
        """Parse key-value pair structures into normalized metric records.

        Resolves metric key/value pairs, maps target states/utilities, and
        emits parsed results with provenance metadata.
        """
        records: list[ParsedRecord] = []
        warnings: list[str] = []

        # Resolve header size
        header_rows_count = 1
        if table.row_labels:
            header_rows_count = sum(1 for label in table.row_labels if label == RowLabel.HEADER)
        header_rows_count = max(1, header_rows_count)

        # Resolve target state from profile config
        state = "State Level"
        if hasattr(config, "profile") and config.profile:
            state = getattr(config.profile, "state_name", "State Level")
        elif isinstance(config, dict) and "profile" in config:
            profile = config["profile"]
            if isinstance(profile, dict):
                state = profile.get("state_name", "State Level")

        utility = "state_level"

        # Resolve page references
        pages = [1]
        if hasattr(config, "page_range") and config.page_range:
            start = getattr(config.page_range, "start_page", 1)
            end = getattr(config.page_range, "end_page", start)
            pages = list(range(start, end + 1))

        # Iterate rows from header boundary onwards
        for r_idx in range(header_rows_count, len(table.rows)):
            row = table.rows[r_idx]
            if not row or len(row) < 2:
                continue

            key = row[0].strip()
            val_str = row[1].strip()

            if not key:
                continue

            val = parse_float(val_str, r_idx, 1)
            if val is None:
                continue

            from .numeric_matrix import extract_unit_from_text
            unit = extract_unit_from_text(key, "Rs/kWh")

            record_fields = {
                "state": state,
                "utility": utility,
                "consumer_category": key,
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
                f"{key}:{r_idx}",
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


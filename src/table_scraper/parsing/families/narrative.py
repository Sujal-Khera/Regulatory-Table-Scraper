"""Narrative parser family — banking charges and policy tables."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from table_scraper.domain.enums import ParseStatus, ParserFamily, TablePattern, RowLabel
from table_scraper.domain.models import NormalizedTable, ParseResult, ParsedRecord, StateBlock
from table_scraper.parsing.base import BaseParser, parse_float, generate_record_id


class NarrativeParser(BaseParser):
    """Parser for hierarchical parent/child/continuation narrative tables."""

    @property
    def parser_id(self) -> str:
        return "narrative_v1"

    @property
    def pattern(self) -> TablePattern:
        return TablePattern.HIERARCHICAL_PARENT_CHILD

    @property
    def parser_family(self) -> ParserFamily:
        return ParserFamily.NARRATIVE

    def parse(
        self,
        table: NormalizedTable,
        blocks: list[StateBlock] | None,
        config: Any,
    ) -> ParseResult:
        """Parse hierarchical parent/child narrative rows.

        Tracks current state, category, and subcategory hierarchies to emit
        fully populated ParsedRecords with inherited metadata.
        """
        records: list[ParsedRecord] = []
        warnings: list[str] = []

        current_master = ""
        current_child = ""

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

        # Resolve header size
        header_rows_count = 1
        if table.row_labels:
            header_rows_count = sum(1 for label in table.row_labels if label == RowLabel.HEADER)
        header_rows_count = max(1, header_rows_count)

        # ----------------------------------------------------
        # Specialized Parser: Banking Charges
        # ----------------------------------------------------
        if table.parameter_id == "banking_charges":
            import re
            
            # Load catalogs for matching states
            states = set()
            state_aliases = {}
            utilities = []
            try:
                from table_scraper.config.loader import get_config_loader
                loader = get_config_loader()
                catalogs = loader.load_catalogs()
                states = set(s.lower() for s in catalogs.states.states)
                state_aliases = {k.lower(): v.lower() for k, v in catalogs.state_aliases.aliases.items()}
                utilities = catalogs.utilities.utilities
            except Exception:
                pass

            def clean_state_candidate(val: str) -> str:
                val = re.sub(r"\(cid:\d+\)", "", val)
                val = val.replace("/", "").replace("*", "").strip()
                return val.lower()

            current_state = None
            current_charge = ""
            current_period = ""
            current_policy = ""
            
            for r_idx in range(header_rows_count, len(table.rows)):
                row = table.rows[r_idx]
                if not row or all(c.strip() == "" for c in row):
                    continue
                    
                # Scan state candidate in row[0]
                state_candidate = clean_state_candidate(row[0])
                state = None
                if state_candidate in states:
                    state = state_candidate.title()
                elif state_candidate in state_aliases:
                    state = state_aliases[state_candidate].title()

                if state:
                    if current_state != state:
                        current_state = state
                        current_charge = ""
                        current_period = ""
                        current_policy = ""
                else:
                    state = current_state if current_state else "State Level"
                    
                # Skip header repeating rows
                if "state" in row[0].lower() or "discom" in row[0].lower() or "description" in row[0].lower():
                    continue
                    
                discom = row[1].strip() if len(row) > 1 else ""
                if not discom:
                    continue # Discom name is required for banking charges record
                    
                charge = row[2].strip() if len(row) > 2 else ""
                
                period = ""
                if len(row) > 3:
                    if row[3].strip() and not row[3].strip().startswith(":") and len(row[3].strip()) < 30:
                        period = row[3].strip()
                if not period and len(row) > 4:
                    if row[4].strip() and not row[4].strip().startswith(":") and len(row[4].strip()) < 30:
                        period = row[4].strip()
                        
                policy = ""
                if len(row) > 5 and row[5].strip():
                    policy = row[5].strip()
                else:
                    longest_cell = ""
                    for cell in row[2:]:
                        if len(cell.strip()) > len(longest_cell):
                            longest_cell = cell.strip()
                    if len(longest_cell) > 30:
                        policy = longest_cell
                        
                if policy.startswith(":") or policy.startswith(",") or policy.startswith("-"):
                    policy = policy[1:].strip()
                policy = re.sub(r"[\n\r\t]+", " ", policy).strip()
                
                # Forward-fill / inheritance
                if charge:
                    current_charge = charge
                else:
                    charge = current_charge
                    
                if period:
                    current_period = period
                else:
                    period = current_period
                    
                if policy:
                    current_policy = policy
                else:
                    policy = current_policy
                    
                if not charge and not policy:
                    continue
                    
                record_fields = {
                    "state": state,
                    "discom": discom,
                    "charge": charge,
                    "period": period,
                    "policy": policy,
                }
                
                rec_id = generate_record_id(
                    table.parameter_id,
                    state,
                    discom,
                    f"{charge}:{period}:{r_idx}",
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
                    provenance={"discom": discom, "row_index": r_idx},
                )
                records.append(record)

        # ----------------------------------------------------
        # Fallback Parser: Narrative Hierarchy Parent/Child
        # ----------------------------------------------------
        else:
            for idx, row in enumerate(table.rows):
                label = RowLabel.DATA
                if table.row_labels and idx < len(table.row_labels):
                    label = table.row_labels[idx]

                if label == RowLabel.HEADER:
                    continue

                state = row[0].strip() if row else "State Level"
                utility = "state_level"

                if label == RowLabel.MASTER:
                    current_master = row[1].strip() if len(row) > 1 else ""
                    current_child = ""
                elif label == RowLabel.CHILD:
                    current_child = row[1].strip() if len(row) > 1 else ""
                elif label == RowLabel.CONTINUATION:
                    pass

                category = current_master if current_master else (row[1].strip() if len(row) > 1 else "")
                subcategory = current_child if current_child else (row[2].strip() if len(row) > 2 else "")

                charge_value = None
                for cell_idx, cell in enumerate(reversed(row)):
                    c_idx = len(row) - 1 - cell_idx
                    val = parse_float(cell, idx, c_idx)
                    if val is not None:
                        charge_value = val
                        break

                if charge_value is None:
                    continue

                record_fields = {
                    "state": state,
                    "utility": utility,
                    "consumer_category": category if category else "General",
                    "consumer_subcategory": subcategory,
                    "voltage_level": "all",
                    "charge_value": charge_value,
                    "charge_unit": "Rs/kWh",
                    "effective_date": "",
                }

                rec_id = generate_record_id(
                    table.parameter_id,
                    state,
                    utility,
                    f"{category}:{subcategory}:{idx}",
                )

                record = ParsedRecord(
                    record_id=rec_id,
                    parameter_id=table.parameter_id,
                    fields=record_fields,
                    source_pages=pages,
                    source_rows=[idx],
                    parser_id=self.parser_id,
                    parser_version="1.0.0",
                    confidence=1.0,
                    provenance={"label": label.value, "row_index": idx},
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


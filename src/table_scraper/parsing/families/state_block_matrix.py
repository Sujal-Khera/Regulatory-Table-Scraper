"""State block matrix parser family — cross-subsidy open access matrices."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from table_scraper.domain.enums import ParseStatus, ParserFamily, TablePattern, RowLabel
from table_scraper.domain.models import NormalizedTable, ParseResult, ParsedRecord, StateBlock
from table_scraper.parsing.base import BaseParser, parse_float, generate_record_id


class StateBlockMatrixParser(BaseParser):
    """Parser for complex HT/LT section matrices within state blocks."""

    @property
    def parser_id(self) -> str:
        return "state_block_matrix_v1"

    @property
    def pattern(self) -> TablePattern:
        return TablePattern.STATE_BLOCK_MATRIX

    @property
    def parser_family(self) -> ParserFamily:
        return ParserFamily.STATE_BLOCK_MATRIX

    def parse(
        self,
        table: NormalizedTable,
        blocks: list[StateBlock] | None,
        config: Any,
    ) -> ParseResult:
        """Parse structured categories/utilities scoped within StateBlocks.

        Groups records by canonical state and utility targets, parsing units
        and voltage categories across the blocks.
        """
        records: list[ParsedRecord] = []
        warnings: list[str] = []

        if not blocks:
            warnings.append("StateBlockMatrixParser called with empty StateBlock list.")
            return ParseResult(
                parameter_id=table.parameter_id,
                records=[],
                record_count=0,
                parser_id=self.parser_id,
                pattern=self.pattern,
                parsed_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                status=ParseStatus.SUCCESS,
                parser_family=self.parser_family,
                parse_metadata={"rows_processed": len(table.rows), "records_emitted": 0},
                classification=None,
                input_table_hash=table.source_merged_table_hash,
                state_blocks_used=[],
                errors=[],
                warnings=warnings,
            )

        # 1. Resolve column descriptors from workspace
        from table_scraper.storage.artifact_store import ArtifactCodec
        from table_scraper.understanding.models import ColumnDescriptor

        column_descriptors = []
        try:
            workspace = None
            if hasattr(config, "workspace") and config.workspace is not None:
                workspace = config.workspace
            elif isinstance(config, dict) and "workspace" in config:
                workspace = config["workspace"]

            if workspace is not None:
                desc_path = workspace.root / "parsing" / table.parameter_id / "column_descriptors.json"
                if desc_path.is_file():
                    with open(desc_path, encoding="utf-8") as f:
                        payload = json.load(f)
                    column_descriptors = [
                        ArtifactCodec.decode_dataclass(ColumnDescriptor, item)
                        for item in payload
                    ]
        except Exception as e:
            warnings.append(f"Could not load column descriptors: {e}")

        # 2. Resolve Category & Value columns
        category_col = 0
        value_cols = []
        num_cols = table.column_count

        if column_descriptors:
            for desc in column_descriptors:
                if desc.index < num_cols:
                    role_str = desc.semantic_role.value if hasattr(desc.semantic_role, "value") else str(desc.semantic_role)
                    if role_str == "category" or role_str == "voltage":
                        # If a column was identified as category or voltage sub-header column
                        category_col = desc.index
                    elif role_str == "value":
                        value_cols.append(desc.index)

        # Fallbacks if descriptors are not available or didn't resolve value columns
        if not value_cols:
            state_location = "column"
            try:
                from table_scraper.config.loader import load_parameter_config
                param_cfg = load_parameter_config(table.parameter_id)
                ts = param_cfg.extras.get("table_structure", {}) if hasattr(param_cfg, "extras") else {}
                if isinstance(ts, dict):
                    state_location = ts.get("state_location", "column")
            except Exception:
                pass
            
            if state_location == "spanning":
                category_col = 0
                value_cols = list(range(1, num_cols))
            else:
                category_col = 1 if num_cols > 2 else 0
                start_val = 2 if num_cols > 2 else 1
                value_cols = list(range(start_val, num_cols))

        # Reconstruct standard headers for fallback utility naming
        headers: list[str] = []
        for col_idx in range(num_cols):
            header_parts = []
            for r_idx in range(min(3, len(table.rows))):
                if table.row_labels and table.row_labels[r_idx] == RowLabel.HEADER:
                    if col_idx < len(table.rows[r_idx]):
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

        # Loop through state blocks
        for b in blocks:
            state = b.state
            year = b.year_label

            # 1. Identify local block utility headers
            local_utilities = {}  # col_idx -> raw_utility_name
            for block_row in b.rows:
                # If any cell in the first few cells is exactly 'category'
                if any(cell.strip().lower() == "category" for cell in block_row[:4]):
                    for ci in range(len(block_row)):
                        cell = block_row[ci].strip()
                        if cell and cell.lower() not in ("category", "sub-category", "s.no", "sl.no", "sno", "state", "ut", "year", "value", "unit"):
                            local_utilities[ci] = cell
                    break

            current_voltage = "all"

            for row_idx, row in enumerate(b.rows):
                if not row:
                    continue

                category = row[category_col].strip() if category_col < len(row) else ""
                if not category:
                    continue

                # Skip repeating header rows that slipped through
                if category.lower() in ("category", "sub-category", "utility"):
                    continue

                # Check if this row is a voltage sub-header (no data values, category has voltage keyword)
                has_values = False
                for c_idx in value_cols:
                    if c_idx < len(row) and row[c_idx].strip() not in ("", "-", "nil"):
                        # Try parsing cell val as float to verify it's a value
                        if parse_float(row[c_idx], b.start_row + row_idx, c_idx) is not None:
                            has_values = True
                            break

                if not has_values:
                    voltage_match = re.search(
                        r"\b(11\s*kV|33\s*kV|132\s*kV|220\s*kV|66\s*kV|400\s*kV|LT\b|HT\b|EHT\b)",
                        category,
                        re.IGNORECASE
                    )
                    if voltage_match:
                        cleaned_v = voltage_match.group(1).strip()
                        if cleaned_v.lower() not in ("lt", "ht", "eht"):
                            current_voltage = cleaned_v
                        else:
                            current_voltage = cleaned_v.upper()
                        continue  # Skip to next row, as this is a sub-header row

                # Resolve subcategory (column after category, if not a value column)
                subcategory = ""
                sub_col = category_col + 1
                if sub_col < len(row) and sub_col not in value_cols:
                    subcategory = row[sub_col].strip()

                # Extract voltage level from category text as fallback
                voltage = current_voltage
                cat_lower = category.lower()
                if "ht" in cat_lower or "high tension" in cat_lower:
                    if voltage == "all":
                        voltage = "HT"
                elif "lt" in cat_lower or "low tension" in cat_lower:
                    if voltage == "all":
                        voltage = "LT"
                elif "eht" in cat_lower or "extra high tension" in cat_lower:
                    if voltage == "all":
                        voltage = "EHT"

                # Loop through utility columns
                for c_idx in value_cols:
                    if c_idx >= len(row):
                        continue
                    cell_val = row[c_idx]
                    global_row_idx = b.start_row + row_idx
                    val = parse_float(cell_val, global_row_idx, c_idx)
                    if val is None:
                        continue

                    # Determine utility, year, and unit
                    col_year = year
                    col_unit = "Rs/kWh"

                    if local_utilities:
                        closest_col = min(local_utilities.keys(), key=lambda k: abs(k - c_idx))
                        utility = local_utilities[closest_col]
                    else:
                        utility = headers[c_idx] if c_idx < len(headers) else f"Col {c_idx}"
                        if column_descriptors and c_idx < len(column_descriptors):
                            desc = column_descriptors[c_idx]
                            if desc.display_name:
                                utility = desc.display_name

                    if column_descriptors and c_idx < len(column_descriptors):
                        desc = column_descriptors[c_idx]
                        if desc.year:
                            col_year = desc.year
                        if desc.unit:
                            col_unit = desc.unit

                    # Attempt canonical utility name mapping
                    try:
                        from table_scraper.config.loader import get_config_loader
                        loader = get_config_loader()
                        catalogs = loader.load_catalogs()

                        # Pre-defined aliases map for common variations
                        aliases_map = {
                            "apcpdcl": "APCPDCL", "apepdcl": "APEPDCL", "apspdcl": "APSPDCL",
                            "apdcl": "APDCL", "uhbvn": "UHBVN", "uhbvnl": "UHBVN",
                            "dhbvn": "DHBVN", "dhbvnl": "DHBVN", "cspdcl": "CSPDCL",
                            "brpl": "BRPL", "bypl": "BYPL", "tpddl": "TPDDL", "ndmc": "NDMC",
                            "bescom": "BESCOM", "hescom": "HESCOM", "mescom": "MESCOM",
                            "gescom": "GESCOM", "cesc": "CESC", "ksebl": "KSEBL",
                            "msedcl": "MSEDCL", "tangedco": "TANGEDCO", "tgspdcl": "TSSPDCL",
                            "tsspdcl": "TSSPDCL", "tsnpdcl": "TSNPDCL", "tsecl": "TSECL",
                            "dvvnl": "DVVNL", "mvvnl": "MVVNL", "pvvnl": "PVVNL",
                            "puvvnl": "PuVVNL", "kesco": "KESCO", "npcl": "NPCL",
                            "wbsedcl": "WBSEDCL", "pd-sikkim": "DoP Sikkim", "goa ed": "Goa ED",
                            "edg": "Goa ED", "sbpdcl": "SBPDCL", "nbpdcl": "NBPDCL",
                            "jpdcl": "JPDCL", "kpdcl": "KPDCL", "jbvnl": "JBVNL",
                            "mepdcl": "MePDCL", "tpcodl": "TPCODL", "tpnodl": "TPNODL",
                            "tpsodl": "TPSODL", "tpwodl": "TPWODL", "pspcl": "PSPCL",
                            "avvnl": "AVVNL", "jdvvnl": "JdVVNL", "jvvnl": "JVVNL",
                            "upcl": "UPCL", "cpdl": "Chandigarh ED", "dnhpdcl": "DNHPDCL",
                            "dded": "DDED", "ed-a&ni": "A&N Electricity Department"
                        }

                        util_lower = utility.lower()
                        mapped = False
                        for k, v in aliases_map.items():
                            if k in util_lower:
                                utility = v
                                mapped = True
                                break

                        if not mapped:
                            if state:
                                state_utils = catalogs.utilities.utilities.get(state, ())
                                for u in state_utils:
                                    if u.lower() in util_lower:
                                        utility = u
                                        mapped = True
                                        break
                            if not mapped:
                                for s, utils in catalogs.utilities.utilities.items():
                                    for u in utils:
                                        if u.lower() in util_lower:
                                            utility = u
                                            mapped = True
                                            break
                                    if mapped:
                                        break
                    except Exception:
                        pass

                    # Strip year prefixes from utility name (e.g. "2026-27 - APSPDCL" -> "APSPDCL")
                    if " - " in utility:
                        parts = utility.split(" - ")
                        utility = " - ".join([p for p in parts if not re.match(r"\b20\d{2}-\d{2}\b", p)])

                    record_fields = {
                        "state": state,
                        "utility": utility,
                        "consumer_category": category,
                        "consumer_subcategory": subcategory,
                        "voltage_level": voltage,
                        "charge_value": val,
                        "charge_unit": col_unit,
                        "effective_date": "",
                    }
                    if col_year:
                        record_fields["year_label"] = col_year

                    global_row_idx = b.start_row + row_idx

                    rec_id = generate_record_id(
                        table.parameter_id,
                        state,
                        utility,
                        f"{category}:{subcategory}:{voltage}:{col_year or ''}:{global_row_idx}:{c_idx}",
                    )

                    record = ParsedRecord(
                        record_id=rec_id,
                        parameter_id=table.parameter_id,
                        fields=record_fields,
                        source_pages=pages,
                        source_rows=[global_row_idx],
                        parser_id=self.parser_id,
                        parser_version="1.0.0",
                        confidence=1.0,
                        provenance={"col_index": c_idx, "block_id": b.block_id},
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
            state_blocks_used=[b.block_id for b in blocks],
            errors=[],
            warnings=warnings,
        )

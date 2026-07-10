"""Split open-access matrices into per-state StateBlock segments."""

from __future__ import annotations

import re
from typing import Any

from table_scraper.domain.enums import BlockParserHint, RowLabel
from table_scraper.domain.models import NormalizedTable, StateBlock


def _resolve_state_col(config: Any) -> int:
    """Resolve the active state column index from config."""
    state_col = 0
    if isinstance(config, dict):
        state_col = int(config.get("state_column", 0))
    elif hasattr(config, "state_column") and getattr(config, "state_column") is not None:
        state_col = int(getattr(config, "state_column"))
    elif hasattr(config, "extras") and isinstance(config.extras, dict):
        state_col = int(config.extras.get("state_column", 0))
    return state_col


def _resolve_page_span(config: Any) -> tuple[int, int | None]:
    """Resolve start/end page span from config."""
    start_page = 1
    end_page = None
    if config is not None:
        if hasattr(config, "page_range") and config.page_range is not None:
            start_page = int(getattr(config.page_range, "start_page", 1))
            end_page = getattr(config.page_range, "end_page", start_page)
            if end_page is not None:
                end_page = int(end_page)
        elif isinstance(config, dict) and "page_range" in config and config["page_range"] is not None:
            pr = config["page_range"]
            if hasattr(pr, "start_page"):
                start_page = int(getattr(pr, "start_page", 1))
                end_page = getattr(pr, "end_page", start_page)
                if end_page is not None:
                    end_page = int(end_page)
            elif isinstance(pr, dict):
                start_page = int(pr.get("start_page", 1))
                end_page = pr.get("end_page", start_page)
                if end_page is not None:
                    end_page = int(end_page)
    return start_page, end_page


def _create_block(
    state: str,
    start_row: int,
    end_row: int,
    block_rows: list[list[str]],
    table: NormalizedTable,
    config: Any,
    catalogs: Any = None,
) -> StateBlock:
    """Build a single StateBlock object from clustered rows."""
    start_page, end_page = _resolve_page_span(config)

    # 1. Detect financial year label
    year_label = None
    year_pattern = re.compile(r"\b(20\d{2}-\d{2})\b")
    for row in block_rows:
        for cell in row:
            m = year_pattern.search(cell)
            if m:
                year_label = m.group(1)
                break
        if year_label:
            break

    # 2. Detect utility columns
    detected_utilities = set()
    try:
        if catalogs is None:
            from table_scraper.config.loader import get_config_loader
            loader = get_config_loader()
            catalogs = loader.load_catalogs()
        
        # Mapping variations for search
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
            "dded": "DDED", "ed-a&ni": "A&N Electricity Department",
            "arunachal pd": "DoP Arunachal", "tgnpdcl": "TSNPDCL"
        }
        
        for row in block_rows:
            for cell in row:
                cell_lower = cell.lower()
                for k, v in aliases_map.items():
                    if k in cell_lower:
                        detected_utilities.add(v)
                        
                for state_name, utils in catalogs.utilities.utilities.items():
                    for u in utils:
                        if u.lower() in cell_lower:
                            detected_utilities.add(u)
    except Exception:
        pass

    # If no catalog utility matches, search for discom/utility keyword context
    if not detected_utilities:
        for row in block_rows:
            for cell in row:
                if any(kw in cell.lower() for kw in ["discom", "utility", "licensee"]):
                    detected_utilities.add(cell.strip())

    # 3. Detect category sections (HT/LT/EHT)
    detected_sections = set()
    for row in block_rows:
        for cell in row:
            cell_lower = cell.lower()
            if "ht" in cell_lower or "high tension" in cell_lower:
                detected_sections.add("HT")
            if "lt" in cell_lower or "low tension" in cell_lower:
                detected_sections.add("LT")
            if "eht" in cell_lower or "extra high tension" in cell_lower:
                detected_sections.add("EHT")

    # Generate stable unique block ID
    sanitized_state = state.lower().replace(" ", "_")
    block_id = f"{table.parameter_id}_{sanitized_state}_{start_row}_{end_row}"

    return StateBlock(
        block_id=block_id,
        parameter_id=table.parameter_id,
        state=state,
        start_row=start_row,
        end_row=end_row,
        rows=block_rows,
        start_page=start_page,
        end_page=end_page,
        year_label=year_label,
        block_parser_hint=BlockParserHint.MATRIX,
        utility_columns=sorted(list(detected_utilities)),
        sections=sorted(list(detected_sections)),
        row_count=len(block_rows),
    )


def segment_state_blocks(table: NormalizedTable, config: Any) -> list[StateBlock]:
    """Segment normalized matrix into state-specific blocks.

    Clusters consecutive rows sharing the same state name (spanning header
    or column-based) and creates segmented block objects.

    Args:
        table: The NormalizedTable containing labeled hierarchy rows.
        config: Application configuration carrying pipeline options.

    Returns:
        List of constructed StateBlock instances.
    """
    if not table.rows:
        return []

    # 1. Load parameter configuration
    state_location = "column"
    state_col = 0
    try:
        from table_scraper.config.loader import load_parameter_config
        param_cfg = load_parameter_config(table.parameter_id)
        if param_cfg is not None:
            ts = param_cfg.extras.get("table_structure", {}) if hasattr(param_cfg, "extras") else {}
            if isinstance(ts, dict):
                state_location = ts.get("state_location", "column")
                state_col = int(ts.get("state_column", 0))
    except Exception:
        pass

    from table_scraper.normalization.text_cleanup import clean_state_candidate

    # Load catalogs for state and DISCOM name matching
    states_map = {}
    state_aliases = {}
    discom_to_state = {}
    catalogs = None
    try:
        from table_scraper.config.loader import get_config_loader
        loader = get_config_loader()
        catalogs = loader.load_catalogs()
        states_map = {s.lower(): s for s in catalogs.states.states}
        state_aliases = {k.lower(): v.lower() for k, v in catalogs.state_aliases.aliases.items()}
        for state_name, discom_list in catalogs.utilities.utilities.items():
            for discom in discom_list:
                discom_to_state[discom.lower()] = state_name
    except Exception:
        pass

    blocks: list[StateBlock] = []

    def resolve_state_from_text(text: str) -> str | None:
        cleaned = clean_state_candidate(text)
        if not cleaned:
            return None
        
        # 1. Exact state match
        if cleaned in states_map:
            return states_map[cleaned]
        if cleaned in state_aliases:
            alias_target = state_aliases[cleaned]
            return states_map.get(alias_target, alias_target.title())
            
        # 2. Exact DISCOM match
        if cleaned in discom_to_state:
            state_lower = discom_to_state[cleaned].lower()
            return states_map.get(state_lower, state_lower.title())
            
        # 3. Fuzzy match checks
        for state_lower, state_canon in states_map.items():
            if re.search(r"\b" + re.escape(state_lower) + r"\b", cleaned):
                return state_canon
        for alias, state_lower in state_aliases.items():
            if len(alias) <= 3:
                if alias in re.findall(r"\b\w+\b", cleaned):
                    return states_map.get(state_lower, state_lower.title())
            else:
                if re.search(r"\b" + re.escape(alias) + r"\b", cleaned):
                    return states_map.get(state_lower, state_lower.title())
                    
        # 4. Fuzzy DISCOM match check
        for discom, state_name in discom_to_state.items():
            if re.search(r"\b" + re.escape(discom) + r"\b", cleaned):
                state_lower = state_name.lower()
                return states_map.get(state_lower, state_lower.title())
                
        return None

    def detect_state_in_row(row: list[str]) -> tuple[str, int] | None:
        # Exclude category/charge descriptions to avoid false positives on state names
        excluded = {
            "ht", "lt", "eht", "category", "power", "surcharge", "charge",
            "voltage", "level", "kv", "utility", "discom", "tension",
            "industry", "industries", "supply", "domestic", "commercial",
            "traction", "irrigation", "general", "billing", "period", "policy",
            "residential", "apartment", "apartments", "township", "townships",
            "colony", "colonies", "villa", "villas", "station", "stations"
        }
        # Scan columns 0, 1, 2, 3 (states are usually at the beginning of spanning rows)
        for col_idx in range(min(4, len(row))):
            cell = row[col_idx]
            cleaned = clean_state_candidate(cell)
            if not cleaned:
                continue

            # Tokenize and check for excluded keywords
            words = re.findall(r"\b\w+\b", cleaned)
            if any(w in excluded for w in words):
                continue

            resolved = resolve_state_from_text(cell)
            if resolved:
                return resolved, col_idx
        return None

    if state_location == "spanning":
        # Spanning state rows (one block spans from one RowLabel.MASTER row to the next)
        current_state: str | None = None
        start_row_idx: int | None = None
        block_rows: list[list[str]] = []
        
        for idx, row in enumerate(table.rows):
            is_state = False
            state_name = None
            if table.row_labels and table.row_labels[idx] == RowLabel.MASTER:
                is_state = True
                res = detect_state_in_row(row)
                if res:
                    state_name = res[0]
                else:
                    is_state = False
            else:
                # Fallback check
                res = detect_state_in_row(row)
                if res:
                    is_state = True
                    state_name = res[0]
            
            if is_state and state_name:
                # Flush previous block
                if current_state is not None and block_rows:
                    blocks.append(
                        _create_block(
                            current_state,
                            start_row_idx,
                            idx - 1,
                            block_rows,
                            table,
                            config,
                            catalogs,
                        )
                    )
                current_state = state_name
                start_row_idx = idx
                block_rows = [row]
            else:
                if current_state is not None:
                    block_rows.append(row)

        # Flush final block
        if current_state is not None and block_rows:
            blocks.append(
                _create_block(
                    current_state,
                    start_row_idx,
                    len(table.rows) - 1,
                    block_rows,
                    table,
                    config,
                    catalogs,
                )
            )

    else:
        # Column-based state rows
        current_state = None
        start_row_idx = None
        block_rows = []

        for idx, row in enumerate(table.rows):
            # Skip top header rows
            if table.row_labels and table.row_labels[idx] == RowLabel.HEADER:
                continue

            state_cell = row[state_col].strip() if state_col < len(row) else ""

            if state_cell:
                resolved_state = resolve_state_from_text(state_cell)
                if not resolved_state:
                    if current_state is not None:
                        block_rows.append(row)
                    continue

                if current_state != resolved_state:
                    # Flush previous state block
                    if current_state is not None:
                        blocks.append(
                            _create_block(
                                current_state,
                                start_row_idx,
                                idx - 1,
                                block_rows,
                                table,
                                config,
                                catalogs,
                            )
                        )
                    current_state = resolved_state
                    start_row_idx = idx
                    block_rows = [row]
                else:
                    block_rows.append(row)
            else:
                if current_state is not None:
                    block_rows.append(row)

        # Flush the final block
        if current_state is not None:
            blocks.append(
                _create_block(
                    current_state,
                    start_row_idx,
                    len(table.rows) - 1,
                    block_rows,
                    table,
                    config,
                    catalogs,
                )
            )

    return blocks

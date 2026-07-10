"""State forward-fill and master/child/continuation row classification."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from table_scraper.domain.enums import RowLabel
from table_scraper.domain.models import NormalizedTable


def propagate_hierarchy(table: NormalizedTable, rules: Any) -> NormalizedTable:
    """Forward-fill blank state cells and classify row types.

    Uses catalogs to match Indian state names/aliases, canonicalizes them,
    and assigns structural RowLabels (header, master, child, continuation, data)
    to enable semantic parser routing.

    Args:
        table: Cleaned NormalizedTable to process.
        rules: Configuration rules (e.g. AppSettings).

    Returns:
        A new NormalizedTable with row labels and propagated states.
    """
    # 1. Load states catalogs for name resolution
    states = set()
    state_aliases = {}
    try:
        from table_scraper.config.loader import get_config_loader
        loader = get_config_loader()
        catalogs = loader.load_catalogs()
        states = set(s.lower() for s in catalogs.states.states)
        state_aliases = {k.lower(): v.lower() for k, v in catalogs.state_aliases.aliases.items()}
    except Exception:
        pass

    # 2. Load parameter configuration
    state_location = "column"
    header_rows_count = 1
    state_col = 0
    header_keywords = ["category"]
    try:
        from table_scraper.config.loader import load_parameter_config
        param_cfg = load_parameter_config(table.parameter_id)
        if param_cfg is not None:
            ts = param_cfg.extras.get("table_structure", {}) if hasattr(param_cfg, "extras") else {}
            if isinstance(ts, dict):
                state_location = ts.get("state_location", "column")
                header_rows_count = int(ts.get("header_rows", 1))
                state_col = int(ts.get("state_column", 0))
                header_keywords = ts.get("header_keywords", header_keywords)
    except Exception:
        catalogs = None

    from table_scraper.normalization.text_cleanup import detect_state_in_row

    new_rows: list[list[str]] = []
    row_labels: list[RowLabel] = []
    current_state = None
    propagated_count = 0

    for idx, row in enumerate(table.rows):
        # A. Mark header rows based on count
        if idx < header_rows_count:
            row_labels.append(RowLabel.HEADER)
            new_rows.append(row)
            continue

        # B. Check for header-like keywords in the row
        is_keyword_header = False
        for cell in row[:3]:
            cell_clean = cell.strip().lower()
            if any(kw in cell_clean for kw in header_keywords):
                is_keyword_header = True
                break
        if is_keyword_header:
            row_labels.append(RowLabel.HEADER)
            new_rows.append(row)
            continue

        # Check for section header row
        is_section_header = False
        if table.parameter_id == "additional_surcharge" and idx >= header_rows_count:
            col1 = row[1].strip() if len(row) > 1 else ""
            col0 = row[0].strip() if len(row) > 0 else ""
            if not col0 and col1:
                col1_lower = col1.lower()
                has_threshold_pattern = any(x in col1_lower for x in ("≤", ">", "level", "not available"))
                all_data_empty = all(cell.strip() == "" for cell in row[2:])
                if has_threshold_pattern and all_data_empty:
                    is_section_header = True

        if is_section_header:
            row_labels.append(RowLabel.SECTION_HEADER)
            new_rows.append(row)
            current_state = None
            continue

        # C. State row detection
        state_match = detect_state_in_row(row, catalogs) if catalogs else None
        if state_match:
            current_state = state_match[0]
            row_labels.append(RowLabel.MASTER)
            row_updated = list(row)
            if state_location == "column":
                # For column-based tables, propagate state name into the configured column
                if state_col < len(row_updated):
                    row_updated[state_col] = current_state
            new_rows.append(row_updated)
            continue

        # D. Non-state rows
        if state_location == "column":
            # Propagate state to the state column
            row_updated = list(row)
            state_cell = row[state_col].strip() if state_col < len(row) else ""
            if not state_cell and current_state:
                if state_col < len(row_updated):
                    row_updated[state_col] = current_state
                propagated_count += 1
                
                # Check for child / continuation
                if len(row_updated) > 1 and row_updated[1].strip() != "":
                    row_labels.append(RowLabel.CHILD)
                else:
                    row_labels.append(RowLabel.CONTINUATION)
            else:
                row_labels.append(RowLabel.DATA)
            new_rows.append(row_updated)
        else:
            # For spanning state tables, copy the row exactly as-is without overwriting category column
            row_labels.append(RowLabel.DATA)
            new_rows.append(row)

    stats = dict(table.cleanup_stats or {})
    stats["state_propagations"] = propagated_count

    steps = list(table.normalization_steps)
    if "propagate_hierarchy" not in steps:
        steps.append("propagate_hierarchy")

    return replace(
        table,
        rows=new_rows,
        row_labels=row_labels,
        normalization_steps=steps,
        cleanup_stats=stats,
        normalized_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    )

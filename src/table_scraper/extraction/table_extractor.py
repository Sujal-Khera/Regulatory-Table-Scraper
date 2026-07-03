"""Extract all tables per page within a PageRange."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Any

from table_scraper.domain.models import PageRange, RawTable
from table_scraper.domain.protocols import PdfReader
from table_scraper.extraction.table_selector import select_primary_table


def _resolve_heuristic(config: Any) -> str:
    """Resolve the active table selection heuristic from config."""
    heuristic = "largest_area"
    if hasattr(config, "table_selector") and config.table_selector is not None:
        heuristic = str(config.table_selector)
    elif hasattr(config, "defaults") and config.defaults is not None:
        defaults = config.defaults
        if hasattr(defaults, "table_selector") and defaults.table_selector is not None:
            heuristic = str(defaults.table_selector)
    elif isinstance(config, dict):
        if "table_selector" in config and config["table_selector"] is not None:
            heuristic = str(config["table_selector"])
        elif "defaults" in config and isinstance(config["defaults"], dict):
            heuristic = str(config["defaults"].get("table_selector", "largest_area"))
    return heuristic


def extract_raw_tables(
    pdf: PdfReader,
    page_range: PageRange,
    parameter_id: str,
    config: Any,
) -> list[RawTable]:
    """Extract tables from each page in the confirmed range.

    Args:
        pdf: Open PdfReader resource.
        page_range: Confirmed page range for extraction.
        parameter_id: Target parameter identifier.
        config: Settings configuration.

    Returns:
        List of extracted RawTable objects (one per page in the range).
    """
    heuristic = _resolve_heuristic(config)

    # Compute deterministic page range ID
    range_str = f"{page_range.start_page}-{page_range.end_page}"
    if page_range.page_list:
        range_str += f"-{','.join(map(str, page_range.page_list))}"
    page_range_id = hashlib.sha256(range_str.encode("utf-8")).hexdigest()[:16]

    pages_to_scan = page_range.page_list if page_range.page_list else list(range(page_range.start_page, page_range.end_page + 1))
    raw_tables: list[RawTable] = []

    for page_num in pages_to_scan:
        if page_num < 1 or page_num > pdf.page_count:
            continue

        try:
            candidates = pdf.extract_tables(page_num)
        except Exception:
            candidates = []

        candidate_tables_meta = []
        for i, table in enumerate(candidates):
            cols = max(len(row) for row in table) if table else 0
            candidate_tables_meta.append({
                "index": i,
                "row_count": len(table),
                "column_count": cols,
                "area_score": len(table) * cols
            })

        # Select primary table
        selected_index, rows = select_primary_table(candidates, config)

        row_count = len(rows)
        column_count = max(len(row) for row in rows) if rows else 0

        # Construct warnings
        warnings = []
        if not candidates:
            warnings.append(f"No tables detected on page {page_num}")
        elif row_count == 0:
            warnings.append(f"Primary selected table on page {page_num} is empty")

        raw_table = RawTable(
            parameter_id=parameter_id,
            pdf_page=page_num,
            rows=rows,
            row_count=row_count,
            column_count=column_count,
            selected_table_index=max(0, selected_index),
            candidate_tables=candidate_tables_meta,
            selection_heuristic=heuristic,
            extracted_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            extraction_warnings=warnings,
            page_range_id=page_range_id
        )
        raw_tables.append(raw_table)

    return raw_tables


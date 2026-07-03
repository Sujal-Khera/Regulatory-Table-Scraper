"""Concatenate multi-page RawTable instances and strip repeated headers."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from table_scraper.domain.models import MergedTable, RawTable


def _detect_header_size(first_page_rows: list[list[str]], other_pages: list[list[list[str]]]) -> int:
    """Auto-detect header height based on matching starting rows across pages."""
    if not first_page_rows or not other_pages:
        return 0

    max_h = min(5, len(first_page_rows))
    detected_h = 0

    for h in range(1, max_h + 1):
        candidate_header = first_page_rows[:h]
        matched_any = False
        for page_rows in other_pages:
            if len(page_rows) >= h and page_rows[:h] == candidate_header:
                matched_any = True
                break
        if matched_any:
            detected_h = h

    return detected_h


def merge_multi_page_tables(
    pages: list[RawTable],
    config: Any,
) -> MergedTable:
    """Merge per-page raw tables into one MergedTable.

    Handles sorting in page order, auto-detects and strips repeated headers,
    aligns columns by padding shorter rows, and tracks source page lineage.

    Args:
        pages: List of per-page RawTable objects to merge.
        config: Application configuration.

    Returns:
        A unified MergedTable instance.
    """
    # Sort pages to guarantee ascending page order merge
    sorted_pages = sorted(pages, key=lambda p: p.pdf_page)

    parameter_id = getattr(config, "parameter_id", "unknown")
    if isinstance(config, dict) and "parameter_id" in config:
        parameter_id = config["parameter_id"]

    if not sorted_pages:
        return MergedTable(
            parameter_id=parameter_id,
            source_pages=[],
            rows=[],
            row_count=0,
            column_count=0,
            headers_stripped_count=0,
            header_signature=[],
            merge_log=[],
            merged_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        )

    parameter_id = sorted_pages[0].parameter_id

    # Find first non-empty page to initialize header signature
    first_non_empty = None
    for p in sorted_pages:
        if p.rows:
            first_non_empty = p
            break

    if first_non_empty is None:
        return MergedTable(
            parameter_id=parameter_id,
            source_pages=[p.pdf_page for p in sorted_pages],
            rows=[],
            row_count=0,
            column_count=0,
            headers_stripped_count=0,
            header_signature=[],
            merge_log=[],
            merged_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        )

    # Gather rows from other non-empty pages to detect header signature size
    other_pages_rows = [
        p.rows for p in sorted_pages
        if p.pdf_page != first_non_empty.pdf_page and p.rows
    ]

    header_rows_count = None
    if hasattr(config, "header_rows") and getattr(config, "header_rows") is not None:
        header_rows_count = int(getattr(config, "header_rows"))
    elif isinstance(config, dict) and "header_rows" in config and config["header_rows"] is not None:
        header_rows_count = int(config["header_rows"])

    if header_rows_count is not None:
        header_size = min(header_rows_count, len(first_non_empty.rows))
    else:
        header_size = _detect_header_size(first_non_empty.rows, other_pages_rows)

    if header_size > 0:
        header_signature = first_non_empty.rows[:header_size]
    else:
        header_signature = []

    all_rows: list[list[str]] = []
    headers_stripped_count = 0
    merge_log = []
    source_pages = []
    input_raw_table_hashes = []

    for p in sorted_pages:
        source_pages.append(p.pdf_page)

        # Compute hash for raw table lineage tracking
        rows_str = json.dumps(p.rows)
        raw_hash = hashlib.sha256(rows_str.encode("utf-8")).hexdigest()
        input_raw_table_hashes.append(raw_hash)

        if not p.rows:
            merge_log.append({
                "pdf_page": p.pdf_page,
                "rows_added": 0,
                "headers_removed": 0
            })
            continue

        rows_to_add = p.rows
        stripped_in_page = 0

        # Strip repeated headers on pages after the first non-empty page
        if p.pdf_page != first_non_empty.pdf_page:
            if header_size > 0 and len(p.rows) >= header_size:
                if p.rows[:header_size] == header_signature:
                    rows_to_add = p.rows[header_size:]
                    stripped_in_page = header_size
                    headers_stripped_count += header_size

        all_rows.extend(rows_to_add)
        merge_log.append({
            "pdf_page": p.pdf_page,
            "rows_added": len(rows_to_add),
            "headers_removed": stripped_in_page
        })

    # Columns alignment & padding
    max_cols = 0
    if all_rows:
        max_cols = max(len(row) for row in all_rows)
        for row in all_rows:
            if len(row) < max_cols:
                row.extend([""] * (max_cols - len(row)))

    # Flat header signature for audit
    flat_header = header_signature[0] if header_signature else []

    # Get page range if accessible from config
    page_range = getattr(config, "page_range", None)
    if isinstance(config, dict):
        page_range = config.get("page_range")

    return MergedTable(
        parameter_id=parameter_id,
        source_pages=source_pages,
        rows=all_rows,
        row_count=len(all_rows),
        column_count=max_cols,
        headers_stripped_count=headers_stripped_count,
        header_signature=flat_header,
        merge_log=merge_log,
        page_range=page_range,
        merged_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        input_raw_table_hashes=input_raw_table_hashes,
    )


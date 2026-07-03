"""Drop empty rows/columns and compress sparse rows."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json

from table_scraper.domain.models import MergedTable, NormalizedTable


def _align_misaligned_headers(rows: list[list[str]], header_depth: int) -> list[list[str]]:
    if not rows or len(rows) <= header_depth:
        return rows
        
    width = max(len(r) for r in rows)
    uniform_rows = [list(r) + [""] * (width - len(r)) for r in rows]
    
    header_rows = uniform_rows[:header_depth]
    data_rows = uniform_rows[header_depth:]
    
    col_has_header_text = [False] * width
    col_has_data_text = [False] * width
    
    for c in range(width):
        for r in header_rows:
            if r[c].strip() not in ("", "/", "\\", "-"):
                col_has_header_text[c] = True
                break
        for r in data_rows:
            if r[c].strip() != "":
                col_has_data_text[c] = True
                break
                
    for c in range(1, width):
        # Case 1: Header shifted right
        if col_has_header_text[c] and not col_has_data_text[c]:
            if col_has_data_text[c - 1] and not col_has_header_text[c - 1]:
                for r_idx in range(header_depth):
                    if uniform_rows[r_idx][c].strip() != "":
                        uniform_rows[r_idx][c - 1] = uniform_rows[r_idx][c]
                        uniform_rows[r_idx][c] = ""
                col_has_header_text[c - 1] = True
                col_has_header_text[c] = False
                
        # Case 2: Header shifted left
        elif col_has_header_text[c - 1] and not col_has_data_text[c - 1]:
            if col_has_data_text[c] and not col_has_header_text[c]:
                for r_idx in range(header_depth):
                    if uniform_rows[r_idx][c - 1].strip() != "":
                        uniform_rows[r_idx][c] = uniform_rows[r_idx][c - 1]
                        uniform_rows[r_idx][c - 1] = ""
                col_has_header_text[c] = True
                col_has_header_text[c - 1] = False
                
    return uniform_rows


def normalize_geometry(raw: MergedTable) -> NormalizedTable:
    """Normalize table geometry by stripping empty rows and columns.

    Pads rows to ensure uniform length, preserves column/row ordering, and
    records metadata for pipeline execution tracing.

    Args:
        raw: The input MergedTable from the extraction stage.

    Returns:
        A structured NormalizedTable with clean geometry.
    """
    if not raw.rows:
        return NormalizedTable(
            parameter_id=raw.parameter_id,
            rows=[],
            row_count=0,
            column_count=0,
            normalization_steps=["normalize_geometry"],
            row_labels=None,
            source_merged_table_hash=hashlib.sha256(b"").hexdigest(),
            normalized_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            cleanup_stats={"empty_rows_removed": 0, "empty_cols_removed": 0, "cid_tokens_removed": 0},
            wide_format=None,
        )

    # Align misaligned headers and ghost columns
    header_depth = min(4, len(raw.rows))
    aligned_rows = _align_misaligned_headers(raw.rows, header_depth)

    # 1. Identify non-empty columns
    non_empty_cols = []
    num_cols = max(len(r) for r in aligned_rows)
    for col_idx in range(num_cols):
        col_is_empty = True
        for row in aligned_rows:
            if col_idx < len(row) and row[col_idx].strip() != "":
                col_is_empty = False
                break
        if not col_is_empty:
            non_empty_cols.append(col_idx)

    # 2. Filter rows and columns
    cleaned_rows: list[list[str]] = []
    empty_rows_count = 0

    for row in aligned_rows:
        # Skip completely empty rows
        if all(cell.strip() == "" for cell in row):
            empty_rows_count += 1
            continue

        # Extract only active column cells
        new_row = []
        for col_idx in non_empty_cols:
            if col_idx < len(row):
                new_row.append(row[col_idx])
            else:
                new_row.append("")
        cleaned_rows.append(new_row)

    column_count = len(non_empty_cols)
    empty_cols_count = num_cols - column_count

    # 3. Align and pad rows to normalized width
    for row in cleaned_rows:
        if len(row) < column_count:
            row.extend([""] * (column_count - len(row)))

    # Lineage hash from MergedTable rows
    raw_str = json.dumps(raw.rows)
    source_hash = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()

    cleanup_stats = {
        "empty_rows_removed": empty_rows_count,
        "empty_cols_removed": empty_cols_count,
        "cid_tokens_removed": 0,
    }

    return NormalizedTable(
        parameter_id=raw.parameter_id,
        rows=cleaned_rows,
        row_count=len(cleaned_rows),
        column_count=column_count,
        normalization_steps=["normalize_geometry"],
        row_labels=None,
        source_merged_table_hash=source_hash,
        normalized_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        cleanup_stats=cleanup_stats,
        wide_format=None,
    )


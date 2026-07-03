"""Compute shape signals for pattern classification."""

from __future__ import annotations

import re
from typing import Any

from table_scraper.domain.enums import RowLabel
from table_scraper.domain.models import NormalizedTable


def extract_features(table: NormalizedTable) -> dict[str, float]:
    """Compute classifier feature signals from a NormalizedTable.

    Extracts row/col counts, densities, keyword occurrences, hierarchy
    markers, and variance measurements to feed the signature scoring engine.

    Args:
        table: NormalizedTable to analyze.

    Returns:
        Typed dictionary of feature_name -> float score/density/count.
    """
    row_count = len(table.rows)
    column_count = table.column_count

    # 1. Empty Row and Column ratios
    empty_rows = sum(1 for r in table.rows if all(c.strip() == "" for c in r))
    empty_row_ratio = empty_rows / row_count if row_count > 0 else 0.0

    empty_cols = 0
    for col_idx in range(column_count):
        if all(col_idx < len(r) and r[col_idx].strip() == "" for r in table.rows):
            empty_cols += 1
    empty_column_ratio = empty_cols / column_count if column_count > 0 else 0.0

    # 2. Merged Header Indicators
    merged_header_score = 0.0
    if table.rows:
        first_row = table.rows[0]
        for i in range(len(first_row)):
            if first_row[i].strip() == "":
                merged_header_score += 1.0
            elif i > 0 and first_row[i] == first_row[i - 1]:
                merged_header_score += 1.0
        merged_header_indicators = merged_header_score / len(first_row) if first_row else 0.0
    else:
        merged_header_indicators = 0.0

    # 3. Repeated Header Indicators
    repeated_header_indicators = 0.0
    if table.cleanup_stats:
        repeated_header_indicators = float(table.cleanup_stats.get("headers_stripped_count", 0))

    # 4. Cell content densities
    total_cells = 0
    num_cells = 0
    alpha_cells = 0

    digit_pattern = re.compile(r"\d")
    alpha_pattern = re.compile(r"[a-zA-Z]")

    for row in table.rows:
        for cell in row:
            total_cells += 1
            if digit_pattern.search(cell):
                num_cells += 1
            if alpha_pattern.search(cell):
                alpha_cells += 1

    numeric_density = num_cells / total_cells if total_cells > 0 else 0.0
    text_density = alpha_cells / total_cells if total_cells > 0 else 0.0
    average_cells_per_row = total_cells / row_count if row_count > 0 else 0.0

    # 5. Row length variance of non-empty cells
    non_empty_counts = [sum(1 for c in row if c.strip() != "") for row in table.rows]
    if non_empty_counts:
        mean_non_empty = sum(non_empty_counts) / len(non_empty_counts)
        row_length_variance = sum((x - mean_non_empty) ** 2 for x in non_empty_counts) / len(non_empty_counts)
    else:
        row_length_variance = 0.0

    header_repetition_frequency = repeated_header_indicators / row_count if row_count > 0 else 0.0

    # 6. Keyword occurrences
    state_count = 0
    if table.cleanup_stats:
        state_count = float(table.cleanup_stats.get("state_propagations", 0))
    if table.row_labels:
        state_count += sum(1 for label in table.row_labels if label == RowLabel.MASTER)
    state_name_occurrence = float(state_count)

    utility_count = 0
    discom_kw = ["discom", "utility", "licensee", " Torrent", "MSEDCL", "GUVNL", "UGVCL", "PGVCL", "DGVCL", "MGVCL", "BESCOM", "CESC", "TPL"]
    for row in table.rows:
        for cell in row:
            cell_lower = cell.lower()
            if any(kw.lower() in cell_lower for kw in discom_kw):
                utility_count += 1
    utility_name_occurrence = float(utility_count)

    section_count = 0
    sec_kw = ["ht", "lt", "eht", "high tension", "low tension", "extra high tension", "domestic", "commercial", "agriculture", "industrial"]
    for row in table.rows:
        for cell in row:
            cell_lower = cell.lower()
            if any(kw in cell_lower for kw in sec_kw):
                section_count += 1
    section_keyword_occurrence = float(section_count)

    voltage_count = 0
    volt_pattern = re.compile(r"\b\d+\s*kv\b|\bvoltage\b|\bvolt\b|\bkv\b", re.IGNORECASE)
    for row in table.rows:
        for cell in row:
            if volt_pattern.search(cell):
                voltage_count += 1
    voltage_keyword_occurrence = float(voltage_count)

    tariff_count = 0
    tariff_kw = ["tariff", "charge", "surcharge", "rate", "cost", "price", "fee"]
    for row in table.rows:
        for cell in row:
            cell_lower = cell.lower()
            if any(kw in cell_lower for kw in tariff_kw):
                tariff_count += 1
    tariff_keyword_occurrence = float(tariff_count)

    year_count = 0
    year_pattern = re.compile(r"\b20\d{2}-\d{2}\b")
    for row in table.rows:
        for cell in row:
            if year_pattern.search(cell):
                year_count += 1
    year_occurrence = float(year_count)

    # 7. Structural hierarchy indicators
    continuation_count = 0
    hierarchy_count = 0
    if table.row_labels:
        continuation_count = sum(1 for label in table.row_labels if label == RowLabel.CONTINUATION)
        hierarchy_count = sum(1 for label in table.row_labels if label in (RowLabel.MASTER, RowLabel.CHILD))

    continuation_row_indicators = float(continuation_count)
    hierarchy_indicators = float(hierarchy_count)

    indent_count = 0
    for row in table.rows:
        if len(row) > 1 and row[0].strip() == "" and row[1].strip() != "":
            indent_count += 1
    indentation_indicators = float(indent_count)

    return {
        "row_count": float(row_count),
        "column_count": float(column_count),
        "empty_row_ratio": empty_row_ratio,
        "empty_column_ratio": empty_column_ratio,
        "merged_header_indicators": merged_header_indicators,
        "repeated_header_indicators": repeated_header_indicators,
        "numeric_density": numeric_density,
        "text_density": text_density,
        "average_cells_per_row": average_cells_per_row,
        "row_length_variance": row_length_variance,
        "header_repetition_frequency": header_repetition_frequency,
        "state_name_occurrence": state_name_occurrence,
        "utility_name_occurrence": utility_name_occurrence,
        "section_keyword_occurrence": section_keyword_occurrence,
        "voltage_keyword_occurrence": voltage_keyword_occurrence,
        "tariff_keyword_occurrence": tariff_keyword_occurrence,
        "year_occurrence": year_occurrence,
        "continuation_row_indicators": continuation_row_indicators,
        "indentation_indicators": indentation_indicators,
        "hierarchy_indicators": hierarchy_indicators,
    }


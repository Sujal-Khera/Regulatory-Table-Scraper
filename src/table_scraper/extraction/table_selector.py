"""Select primary table per page using rows x columns heuristic."""

from __future__ import annotations

from typing import Any


def select_primary_table(
    candidate_tables: list[list[list[str]]],
    config: Any,
) -> tuple[int, list[list[str]]]:
    """Pick the primary table from multiple candidates on one page.

    Args:
        candidate_tables: List of candidate tables on the page.
        config: Application configuration carrying defaults.

    Returns:
        Tuple of (selected_index, table_rows).
    """
    if not candidate_tables:
        return -1, []

    heuristic = "largest_area"
    target_index = 0

    # Resolve heuristic from config object
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

    # Resolve target table_index for by_index heuristic
    if heuristic == "by_index":
        if hasattr(config, "table_index") and config.table_index is not None:
            target_index = int(config.table_index)
        elif isinstance(config, dict) and "table_index" in config and config["table_index"] is not None:
            target_index = int(config["table_index"])

    selected_index = 0

    if heuristic == "first_table":
        selected_index = 0
    elif heuristic == "by_index":
        selected_index = target_index
        if selected_index < 0 or selected_index >= len(candidate_tables):
            selected_index = 0
    else:  # largest_area (default)
        max_area = -1
        for idx, table in enumerate(candidate_tables):
            if not table:
                continue
            cols = max(len(row) for row in table)
            area = len(table) * cols
            if area > max_area:
                max_area = area
                selected_index = idx

    return selected_index, candidate_tables[selected_index]


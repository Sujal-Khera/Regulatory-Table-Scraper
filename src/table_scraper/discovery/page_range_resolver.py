"""Compute PageRange via anchor chain or TOC ordering."""

from __future__ import annotations

from typing import Any

from table_scraper.domain.enums import PageRangeSource
from table_scraper.domain.models import PageIndex, PageRange, ParameterDefinition, TableTitle


def _resolve_strategy(config: Any) -> str:
    """Resolve the page range strategy from config."""
    if hasattr(config, "defaults") and config.defaults is not None:
        defaults = config.defaults
        if hasattr(defaults, "page_range_strategy"):
            return str(getattr(defaults, "page_range_strategy"))

    if hasattr(config, "page_range_strategy"):
        return str(getattr(config, "page_range_strategy"))

    if isinstance(config, dict):
        if "defaults" in config and isinstance(config["defaults"], dict):
            return str(config["defaults"].get("page_range_strategy", "anchor_chain"))
        if "page_range_strategy" in config:
            return str(config["page_range_strategy"])

    return "anchor_chain"


def _resolve_toc_offset(config: Any) -> int:
    """Resolve the TOC offset delta from config."""
    if hasattr(config, "toc_page_offset") and getattr(config, "toc_page_offset") is not None:
        return int(getattr(config, "toc_page_offset"))

    if isinstance(config, dict):
        if "toc_page_offset" in config and config["toc_page_offset"] is not None:
            return int(config["toc_page_offset"])

    return 0


def resolve_page_range(
    parameter: ParameterDefinition,
    page_index: PageIndex,
    config: Any,
) -> PageRange:
    """Compute inclusive start/end PDF pages for a parameter.

    Resolves page ranges by mapping parameter anchors to page index records.
    Uses either the index anchor chain or the table-of-contents start delta.

    Args:
        parameter: Discovered parameter definition.
        page_index: Processed PageIndex of the workspace.
        config: Settings configuration.

    Returns:
        A suggested PageRange instance.
    """
    strategy = _resolve_strategy(config)
    toc_offset = _resolve_toc_offset(config)

    # Gather all page-index titles
    all_anchors: list[tuple[int, TableTitle]] = []
    for record in page_index.pages:
        for title in record.table_titles:
            all_anchors.append((record.pdf_page, title))

    # Match current parameter's table number in page index
    match_idx = -1
    for idx, (pdf_page, title) in enumerate(all_anchors):
        if title.table_number == parameter.table_title.table_number:
            match_idx = idx
            break

    # Anchor-chain strategy (default)
    if strategy == "anchor_chain" and match_idx != -1:
        start_page, start_title = all_anchors[match_idx]
        anchor_end_title = None

        if match_idx + 1 < len(all_anchors):
            next_page, next_title = all_anchors[match_idx + 1]
            end_page = max(start_page, next_page - 1)
            anchor_end_title = next_title
            boundary_rule = f"Bounded by next index anchor '{next_title.table_number}' on page {next_page}"
        else:
            end_page = page_index.page_count
            boundary_rule = "Extend to end of document (last index anchor)"

        return PageRange(
            start_page=start_page,
            end_page=end_page,
            source=PageRangeSource.ANCHOR_CHAIN,
            parameter_id=parameter.parameter_id,
            boundary_rule=boundary_rule,
            anchor_start_title=start_title,
            anchor_end_title=anchor_end_title,
        )

    # TOC next start strategy or fallback
    calibrated_start = (parameter.toc_start_page or 1) + toc_offset
    start_page = parameter.pdf_start_page or calibrated_start
    start_page = max(1, min(start_page, page_index.page_count))

    # Resolve end page by looking at subsequent TOC entry
    toc_entries: list[Any] = []
    if hasattr(config, "toc") and getattr(config, "toc") is not None:
        toc_entries = list(getattr(config, "toc"))
    elif isinstance(config, dict) and "toc" in config and config["toc"] is not None:
        toc_entries = list(config["toc"])

    toc_match_idx = -1
    for idx, entry in enumerate(toc_entries):
        # Entry can be a TocEntry object or a dictionary
        entry_table_num = getattr(
            getattr(entry, "table_title", None), "table_number", None
        ) or entry.get("table_title", {}).get("table_number")
        if entry_table_num == parameter.table_title.table_number:
            toc_match_idx = idx
            break

    anchor_end_title = None
    if toc_match_idx != -1 and toc_match_idx + 1 < len(toc_entries):
        next_entry = toc_entries[toc_match_idx + 1]
        next_printed = getattr(next_entry, "printed_page", None) or next_entry.get("printed_page")
        if next_printed is not None:
            next_calibrated = next_printed + toc_offset
            end_page = max(start_page, next_calibrated - 1)
            next_title_data = getattr(next_entry, "table_title", None) or next_entry.get("table_title")
            if isinstance(next_title_data, TableTitle):
                anchor_end_title = next_title_data
            boundary_rule = f"Bounded by next TOC entry on page {next_calibrated}"
        else:
            end_page = page_index.page_count
            boundary_rule = "TOC printed page missing; extended to end of document"
    else:
        # Fallback to finding next title in PageIndex
        next_index_page = None
        next_title = None
        for pdf_page, title in all_anchors:
            if pdf_page > start_page and title.table_number != parameter.table_title.table_number:
                next_index_page = pdf_page
                next_title = title
                break

        if next_index_page is not None:
            end_page = max(start_page, next_index_page - 1)
            anchor_end_title = next_title
            boundary_rule = f"Bounded by next index anchor '{next_title.table_number}' on page {next_index_page}"
        else:
            end_page = page_index.page_count
            boundary_rule = "No subsequent anchor found; extended to end of document"

    # Set appropriate starting anchor if possible
    anchor_start_title = parameter.table_title
    if match_idx != -1:
        anchor_start_title = all_anchors[match_idx][1]

    return PageRange(
        start_page=start_page,
        end_page=end_page,
        source=PageRangeSource.TOC_NEXT_START,
        parameter_id=parameter.parameter_id,
        boundary_rule=boundary_rule,
        anchor_start_title=anchor_start_title,
        anchor_end_title=anchor_end_title,
    )


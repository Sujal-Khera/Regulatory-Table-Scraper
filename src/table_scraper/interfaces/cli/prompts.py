"""Interactive CLI prompts for parameter selection and page range confirmation."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid
from typing import Any

from table_scraper.domain.enums import SelectionMode, ExportMode, PageRangeSource
from table_scraper.domain.models import PageRange, ParameterCatalog, UserSelection


def list_parameters(catalog: ParameterCatalog) -> None:
    """Display discovered parameters with page ranges.

    Prints supported vs unsupported parameters sorted by page.
    """
    print(f"\n--- Discovered Parameters ({catalog.supported_count} Supported) ---")
    supported = [p for p in catalog.parameters if p.supported]
    unsupported = [p for p in catalog.parameters if not p.supported]

    print("\nSupported Parameters:")
    for param in supported:
        pr = param.suggested_range
        print(f"  * {param.parameter_id:<15} : {param.display_name:<30} (Pages {pr.start_page}-{pr.end_page})")

    if unsupported:
        print("\nUnsupported Parameters:")
        for param in unsupported:
            pr = param.suggested_range
            print(f"  * {param.parameter_id:<15} : {param.display_name:<30} (Pages {pr.start_page}-{pr.end_page})")


def confirm_page_range(parameter_id: str, suggested_range: PageRange) -> PageRange:
    """Prompt user to confirm or adjust a PageRange.

    Returns the confirmed PageRange.
    """
    print(f"\nConfirm page range for parameter '{parameter_id}' (suggested: {suggested_range.start_page}-{suggested_range.end_page})")
    try:
        val = input("Enter range override (e.g. '12-14') or press Enter to accept suggestion: ").strip()
        if val:
            parts = val.split("-")
            start = int(parts[0])
            end = int(parts[1]) if len(parts) > 1 else start
            return PageRange(
                start_page=start,
                end_page=end,
                source=PageRangeSource.USER_CONFIRMED,
                confirmed_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                confirmed_by="cli",
            )
    except Exception:
        print("Invalid input format; falling back to suggested range.")

    return PageRange(
        start_page=suggested_range.start_page,
        end_page=suggested_range.end_page,
        source=PageRangeSource.USER_CONFIRMED,
        confirmed_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        confirmed_by="cli",
    )


def build_user_selection(catalog: ParameterCatalog) -> UserSelection:
    """Collect user parameter selection and confirmed ranges.

    Supports catalog selection mode.
    """
    list_parameters(catalog)

    print("\nSelect parameter IDs to process (comma-separated, or 'all'):")
    val = input("Selection: ").strip()

    supported_ids = [p.parameter_id for p in catalog.parameters if p.supported]
    if not val or val.lower() == "all":
        selected_ids = list(supported_ids)
    else:
        selected_ids = [pid.strip() for pid in val.split(",") if pid.strip() in supported_ids]
        if not selected_ids:
            print("No valid supported parameters selected; running for all.")
            selected_ids = list(supported_ids)

    confirmed_ranges: dict[str, PageRange] = {}
    for param in catalog.parameters:
        if param.parameter_id in selected_ids:
            confirmed_ranges[param.parameter_id] = confirm_page_range(
                param.parameter_id,
                param.suggested_range,
            )

    return UserSelection(
        selection_id=str(uuid.uuid4()),
        created_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        selection_mode=SelectionMode.CATALOG,
        parameter_ids=selected_ids,
        confirmed_ranges=confirmed_ranges,
        export_mode=ExportMode.SINGLE_WORKBOOK,
        skip_validation=False,
        force_reextract=False,
    )

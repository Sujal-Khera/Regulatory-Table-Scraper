"""Thin wrapper around openpyxl for Excel warehouse export."""

from __future__ import annotations

from typing import Any

from table_scraper.domain.models import ExcelWorkbook


class OpenpyxlExcelWriter:
    """
    ExcelWriter adapter implementation.

    TODO: Write multi-sheet workbook from dict of DataFrames.
    TODO: Delegate formatting to export.formatter module.
    """

    def write(
        self,
        sheets: dict[str, Any],
        path: str,
        format_spec: dict[str, Any],
    ) -> ExcelWorkbook:
        """Write sheets to Excel and return metadata envelope."""
        raise NotImplementedError

"""Map TOC printed page numbers to PDF index via phrase search."""

from __future__ import annotations

import re
from typing import Any

from table_scraper.domain.errors import DiscoveryError
from table_scraper.domain.protocols import PdfReader


def calibrate_page_offset(toc_page: int, pdf: PdfReader, phrase: str) -> int:
    """Compute pdf_page - printed_page offset using a unique phrase search.

    Scans the document to find the first PDF page containing the phrase.
    The offset is calculated as actual_pdf_page - toc_page.

    Args:
        toc_page: Printed page number from the TOC.
        pdf: Open PdfReader resource.
        phrase: Case-insensitive search phrase to locate.

    Returns:
        The computed page offset delta.

    Raises:
        DiscoveryError: If the phrase cannot be found in the PDF.
    """
    if not phrase:
        raise DiscoveryError("Calibration phrase cannot be empty.")

    phrase_lower = phrase.lower()
    toc_pattern = re.compile(r"TABLE[- ]?\d+(?:\([A-Z]\))?\s*:\s*(.*?)\s+(\d+)", re.IGNORECASE)

    for page_num in range(1, pdf.page_count + 1):
        try:
            text = pdf.extract_text(page_num)
            if not text:
                continue

            # Identify if this is a TOC page by counting TOC entries
            toc_matches = sum(1 for line in text.splitlines() if toc_pattern.search(line))
            if toc_matches > 2:
                continue

            if phrase_lower in text.lower():
                return page_num - toc_page
        except Exception:
            continue


    raise DiscoveryError(
        f"Calibration failed: unique phrase {phrase!r} not found in PDF."
    )


def preview_pages(pdf: PdfReader, page_range: Any, lines: int = 15) -> dict[int, str]:
    """Return first N lines of text per page for user verification.

    Args:
        pdf: Open PdfReader resource.
        page_range: PageRange object or dict defining the start/end/list of pages.
        lines: Maximum number of lines of text to return per page.

    Returns:
        Mapping of pdf_page -> preview text string.
    """
    if hasattr(page_range, "start_page"):
        start = page_range.start_page
        end = page_range.end_page
        page_list = getattr(page_range, "page_list", None)
    elif isinstance(page_range, dict):
        start = page_range.get("start_page", 1)
        end = page_range.get("end_page", 1)
        page_list = page_range.get("page_list", None)
    else:
        raise ValueError("page_range must be a PageRange or a dictionary.")

    pages_to_scan = page_list if page_list else list(range(start, end + 1))
    previews: dict[int, str] = {}

    for page in pages_to_scan:
        if page < 1 or page > pdf.page_count:
            continue
        try:
            text = pdf.extract_text(page)
            text_lines = text.splitlines()[:lines]
            previews[page] = "\n".join(text_lines)
        except Exception:
            previews[page] = ""

    return previews


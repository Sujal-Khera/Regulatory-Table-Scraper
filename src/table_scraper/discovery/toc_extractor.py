"""Parse TOC pages and emit raw TocEntry list."""

from __future__ import annotations

import re
from typing import Any

from table_scraper.domain.enums import TitleSource
from table_scraper.domain.models import TableTitle, TocEntry
from table_scraper.domain.protocols import PdfReader


def _resolve_toc_max_pages(config: Any) -> int:
    """Resolve toc_max_pages from config."""
    if hasattr(config, "defaults") and config.defaults is not None:
        defaults = config.defaults
        if hasattr(defaults, "toc_max_pages"):
            return int(getattr(defaults, "toc_max_pages"))

    if hasattr(config, "toc_max_pages"):
        return int(getattr(config, "toc_max_pages"))

    if isinstance(config, dict):
        if "defaults" in config and isinstance(config["defaults"], dict):
            return int(config["defaults"].get("toc_max_pages", 15))
        if "toc_max_pages" in config:
            return int(config["toc_max_pages"])

    return 15  # Fallback default


def _resolve_toc_entry_pattern(config: Any) -> str:
    """Resolve toc_entry_pattern from config."""
    if hasattr(config, "discovery") and config.discovery is not None:
        discovery = config.discovery
        if hasattr(discovery, "toc_patterns") and discovery.toc_patterns is not None:
            toc = discovery.toc_patterns
            if hasattr(toc, "toc_entry_pattern"):
                return str(getattr(toc, "toc_entry_pattern"))

    if hasattr(config, "toc_entry_pattern"):
        return str(getattr(config, "toc_entry_pattern"))

    if isinstance(config, dict):
        if "discovery" in config and isinstance(config["discovery"], dict):
            discovery = config["discovery"]
            if "toc_patterns" in discovery and isinstance(discovery["toc_patterns"], dict):
                return str(discovery["toc_patterns"].get("toc_entry_pattern"))
            if "toc_entry_pattern" in discovery:
                return str(discovery["toc_entry_pattern"])
        if "toc_entry_pattern" in config:
            return str(config["toc_entry_pattern"])

    return r"TABLE[- ]?\d+(?:\([A-Z]\))?\s*:\s*(.*?)\s+(\d+)"


def extract_toc(pdf: PdfReader, config: Any) -> list[TocEntry]:
    """Parse table-of-contents pages from the PDF front matter.

    Args:
        pdf: Open PdfReader resource.
        config: Settings configuration object.

    Returns:
        List of parsed TocEntry objects.
    """
    toc_max_pages = _resolve_toc_max_pages(config)
    toc_pattern_str = _resolve_toc_entry_pattern(config)

    try:
        pattern = re.compile(toc_pattern_str, re.IGNORECASE)
    except Exception:
        pattern = re.compile(r"TABLE[- ]?\d+(?:\([A-Z]\))?\s*:\s*(.*?)\s+(\d+)", re.IGNORECASE)

    table_num_extractor = re.compile(r"\d+(?:\([a-zA-Z]\))?")
    entries: list[TocEntry] = []

    # Scan up to toc_max_pages in front matter
    max_scan = min(toc_max_pages, pdf.page_count)
    for page_num in range(1, max_scan + 1):
        try:
            page_text = pdf.extract_text(page_num)
        except Exception:
            continue

        if not page_text:
            continue

        for line in page_text.splitlines():
            line_stripped = line.strip()
            if not line_stripped:
                continue

            match = pattern.search(line_stripped)
            if not match:
                continue

            # Capture groups: 1 = title text, 2 = printed page number
            if pattern.groups >= 2 and match.group(1) and match.group(2):
                title_text = match.group(1).strip()
                try:
                    printed_page = int(match.group(2))
                except ValueError:
                    continue
            else:
                continue

            if not title_text or printed_page < 1:
                continue

            # Extract table number
            table_num_match = table_num_extractor.search(line_stripped)
            if not table_num_match:
                continue

            raw_table_num = table_num_match.group(0)
            table_number = raw_table_num.lower()  # Normalize to lowercase

            # Ensure raw_text in TableTitle contains table_number and title_text
            safe_raw_text = line_stripped.replace(raw_table_num, table_number, 1)
            if title_text not in safe_raw_text:
                safe_raw_text = f"TABLE-{table_number}: {title_text} {printed_page}"

            try:
                title = TableTitle(
                    raw_text=safe_raw_text,
                    table_number=table_number,
                    title_text=title_text,
                    printed_page=printed_page,
                    source=TitleSource.TOC,
                    confidence=1.0,
                )
                entry = TocEntry(
                    table_title=title,
                    printed_page=printed_page,
                    raw_line=line_stripped,
                )
                entries.append(entry)
            except ValueError:
                # Ignore invalid mapping formats
                continue

    return entries


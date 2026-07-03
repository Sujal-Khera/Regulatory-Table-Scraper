"""Apply configurable regex to extract TableTitle objects from page text."""

from __future__ import annotations

import re
from typing import Any

from table_scraper.domain.enums import TitleSource
from table_scraper.domain.models import TableTitle


def _resolve_pattern(config: Any) -> str:
    """Dynamically resolve the table title regex pattern from the config."""
    # Try AppSettings or similar object structure
    if hasattr(config, "discovery") and config.discovery is not None:
        discovery = config.discovery
        if hasattr(discovery, "toc_patterns") and discovery.toc_patterns is not None:
            toc = discovery.toc_patterns
            if hasattr(toc, "table_title_pattern"):
                return getattr(toc, "table_title_pattern")

    # Try direct attributes
    if hasattr(config, "toc_patterns") and config.toc_patterns is not None:
        toc = config.toc_patterns
        if hasattr(toc, "table_title_pattern"):
            return getattr(toc, "table_title_pattern")

    if hasattr(config, "table_title_pattern"):
        return getattr(config, "table_title_pattern")

    # Try dictionary structures
    if isinstance(config, dict):
        if "discovery" in config and isinstance(config["discovery"], dict):
            discovery = config["discovery"]
            if "toc_patterns" in discovery and isinstance(discovery["toc_patterns"], dict):
                return discovery["toc_patterns"].get("table_title_pattern")
            if "table_title_pattern" in discovery:
                return discovery["table_title_pattern"]
        if "toc_patterns" in config and isinstance(config["toc_patterns"], dict):
            return config["toc_patterns"].get("table_title_pattern")
        if "table_title_pattern" in config:
            return config["table_title_pattern"]

    # Fallback to loading via ConfigLoader if available
    try:
        from table_scraper.config.loader import get_config_loader
        loader = get_config_loader()
        discovery_cfg = loader.load_discovery()
        return discovery_cfg.toc_patterns.table_title_pattern
    except Exception:
        pass

    # Safe hardcoded fallback matching config/discovery/toc_patterns.yaml
    return r"TABLE[- ]?\d+(?:\([A-Z]\))?\s*:\s*([^\n]+)"


def detect_table_titles(page_text: str, config: Any) -> list[TableTitle]:
    """Detect regulatory table titles in page text using regex pattern.

    Args:
        page_text: The plain text of a page to scan.
        config: The configuration containing the regex patterns.

    Returns:
        List of structured TableTitle instances with normalized fields.
    """
    if not page_text:
        return []

    # Skip TOC pages by counting TOC-like entries
    toc_pattern = re.compile(r"TABLE[- ]?\d+(?:\([A-Z]\))?\s*:\s*(.*?)\s+(\d+)", re.IGNORECASE)
    toc_matches = sum(1 for line in page_text.splitlines() if toc_pattern.search(line))
    if toc_matches > 2:
        return []

    pattern_str = _resolve_pattern(config)

    try:
        pattern = re.compile(pattern_str, re.IGNORECASE)
    except Exception:
        # Fallback to default pattern if compiled pattern is invalid
        pattern = re.compile(r"TABLE[- ]?\d+(?:\([A-Z]\))?\s*:\s*([^\n]+)", re.IGNORECASE)

    titles: list[TableTitle] = []
    table_num_extractor = re.compile(r"\d+(?:\([a-zA-Z]\))?")

    for match in pattern.finditer(page_text):
        raw_text = match.group(0)
        match_start = match.start()
        match_end = match.end()

        # Extract title text
        if pattern.groups >= 1 and match.group(1):
            title_text = match.group(1).strip()
        else:
            if ":" in raw_text:
                title_text = raw_text.split(":", 1)[1].strip()
            else:
                title_text = raw_text.strip()

        if not title_text:
            continue

        # Extract and normalize table number
        table_num_match = table_num_extractor.search(raw_text)
        if not table_num_match:
            continue

        raw_table_num = table_num_match.group(0)
        table_number = raw_table_num.lower()  # Normalize e.g. 5(A) -> 5(a)

        # Make raw_text safe for TableTitle.__post_init__ substrings checks.
        # If raw_table_num had uppercase chars, "table_number in raw_text" would fail.
        # Replace the first occurrence of raw_table_num with normalized table_number.
        safe_raw_text = raw_text.replace(raw_table_num, table_number, 1)

        # Extra safety check: if for any reason title_text is still not in safe_raw_text,
        # ensure it is present by reconstructing it or keeping it safe.
        if title_text not in safe_raw_text:
            # Reconstruct to guarantee substring safety
            safe_raw_text = f"TABLE-{table_number}: {title_text}"

        try:
            title = TableTitle(
                raw_text=safe_raw_text,
                table_number=table_number,
                title_text=title_text,
                source=TitleSource.PAGE_SCAN,
                match_start=match_start,
                match_end=match_end,
                confidence=1.0,
            )
            titles.append(title)
        except ValueError:
            # Skip invalid title mappings instead of crashing the pipeline
            continue

    return titles


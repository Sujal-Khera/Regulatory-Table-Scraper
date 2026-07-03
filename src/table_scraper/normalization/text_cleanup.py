"""OCR artifact removal and bilingual text cleanup."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import re

from table_scraper.domain.models import NormalizedTable


def clean_text(value: str) -> str:
    """Strip whitespace, nulls, and (cid:###) OCR artifacts.

    Normalizes unicode whitespace, repeated spaces, dash variations, and
    quotation marks.

    Args:
        value: The raw string to clean.

    Returns:
        The cleaned string.
    """
    if not value:
        return ""

    # 1. Remove null bytes
    val = value.replace("\x00", "")

    # 2. Remove CID tokens
    val = re.sub(r"\(cid:\d+\)", "", val)

    # 3. Normalize unicode whitespace to normal space
    val = re.sub(r"[\xa0\u2000-\u200a\u202f\u205f\u3000\t]+", " ", val)

    # 4. Normalize dashes (en-dash, em-dash, hyphen, minus sign)
    val = re.sub(r"[\u2013\u2014\u2212\u2010\u2011\u2012\u2015]+", "-", val)

    # 5. Normalize quotation marks
    val = val.replace("“", '"').replace("”", '"').replace("„", '"').replace("‟", '"')
    val = val.replace("‘", "'").replace("’", "'").replace("‚", "'").replace("‛", "'")

    # 6. Trim and compress internal spacing
    val = re.sub(r"\s+", " ", val)
    val = re.sub(r'^[\s/]+', '', val)
    val = re.sub(r'[\s/]+$', '', val)
    val = re.sub(r'\*+$', '', val)
    return val.strip()


def extract_english(value: str) -> str:
    """Extract English tokens from bilingual cell text.

    Removes Devanagari Unicode characters (Hindi script), keeping ASCII text,
    numbers, and standard punctuation.

    Args:
        value: The string to filter.

    Returns:
        The text containing only English/ASCII characters.
    """
    if not value:
        return ""

    # Remove Devanagari script range
    hindi_pattern = re.compile(r"[\u0900-\u097f]+")
    cleaned = hindi_pattern.sub("", value)

    # Compress multiple spaces that might result from removal
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r'^[\s/]+', '', cleaned)
    cleaned = re.sub(r'[\s/]+$', '', cleaned)
    cleaned = re.sub(r'\*+$', '', cleaned)
    return cleaned.strip()


def normalize_text_cells(table: NormalizedTable) -> NormalizedTable:
    """Clean cell text, strip CID tokens, and extract English tokens.

    Iterates over all rows of the table, cleans the cell text, records the
    number of CID tokens removed, and returns a new NormalizedTable with
    updated statistics and steps.

    Args:
        table: The input NormalizedTable.

    Returns:
        A new NormalizedTable containing cleaned cells.
    """
    cleaned_rows: list[list[str]] = []
    cid_count = 0
    cid_pattern = re.compile(r"\(cid:\d+\)")

    for row in table.rows:
        cleaned_row = []
        for cell in row:
            # Count CID tokens in raw cell
            cids = cid_pattern.findall(cell)
            cid_count += len(cids)

            # Apply clean text and bilingual extraction
            cleaned_cell = clean_text(cell)
            final_cell = extract_english(cleaned_cell)
            cleaned_row.append(final_cell)
        cleaned_rows.append(cleaned_row)

    # Update cleanup statistics
    stats = dict(table.cleanup_stats or {})
    stats["cid_tokens_removed"] = stats.get("cid_tokens_removed", 0) + cid_count

    steps = list(table.normalization_steps)
    steps.append("normalize_text")

    return replace(
        table,
        rows=cleaned_rows,
        normalization_steps=steps,
        cleanup_stats=stats,
        normalized_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    )




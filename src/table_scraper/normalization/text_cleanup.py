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


def clean_state_candidate(val: str) -> str:
    """Clean and normalize state name candidates by removing OCR/special characters."""
    val = re.sub(r"\(cid:\d+\)", "", val)
    val = val.replace("/", "").replace("*", "").strip()
    return val.lower()


def resolve_canonical_state(state_clean: str, catalogs: Any) -> str | None:
    """Resolve cleaned state candidate to the exact canonical catalog name casing."""
    states_map = {s.lower(): s for s in catalogs.states.states}
    state_aliases = {k.lower(): v.lower() for k, v in catalogs.state_aliases.aliases.items()}

    if state_clean in states_map:
        return states_map[state_clean]
    if state_clean in state_aliases:
        alias_target = state_aliases[state_clean]
        return states_map.get(alias_target, alias_target.title())

    # Fuzzy match checks
    for state_lower, state_canon in states_map.items():
        if re.search(r"\b" + re.escape(state_lower) + r"\b", state_clean):
            return state_canon
    for alias_lower, state_lower in state_aliases.items():
        if len(alias_lower) <= 3:
            words = re.findall(r"\b\w+\b", state_clean)
            if alias_lower in words:
                return states_map.get(state_lower, state_lower.title())
        else:
            if re.search(r"\b" + re.escape(alias_lower) + r"\b", state_clean):
                return states_map.get(state_lower, state_lower.title())
    return None


def detect_state_in_row(row: list[str], catalogs: Any) -> tuple[str, int] | None:
    """Detect and resolve any canonical state name mentioned in the row's metadata fields."""
    excluded = {
        "ht", "lt", "eht", "category", "power", "surcharge", "charge",
        "voltage", "level", "kv", "utility", "discom", "tension",
        "industry", "industries", "supply", "domestic", "commercial",
        "traction", "irrigation", "general", "billing", "period", "policy",
        "residential", "apartment", "apartments", "township", "townships",
        "colony", "colonies", "villa", "villas", "station", "stations"
    }
    for col_idx in range(min(4, len(row))):
        cell = row[col_idx]
        cleaned = clean_state_candidate(cell)
        if not cleaned:
            continue

        words = re.findall(r"\b\w+\b", cleaned)
        if any(w in excluded for w in words):
            continue

        state_canon = resolve_canonical_state(cleaned, catalogs)
        if state_canon:
            return state_canon, col_idx
    return None




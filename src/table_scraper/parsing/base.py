"""Abstract base for parser plugin implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
import hashlib
import re
from typing import Any

from table_scraper.domain.enums import TablePattern
from table_scraper.domain.models import NormalizedTable, ParseResult, StateBlock


class BaseParser(ABC):
    """Abstract ParserPlugin base class.

    Each parsing family subclasses this base and implements specific layout
    parsing patterns, emitting ParseResult containing ParsedRecords.
    """

    @property
    @abstractmethod
    def parser_id(self) -> str:
        """Unique parser plugin identifier."""

    @property
    @abstractmethod
    def pattern(self) -> TablePattern:
        """Primary TablePattern this plugin handles."""

    @abstractmethod
    def parse(
        self,
        table: NormalizedTable,
        blocks: list[StateBlock] | None,
        config: Any,
    ) -> ParseResult:
        """Parse a normalized table into canonical ParsedRecord list."""
        raise NotImplementedError


_active_annotated_table = None


def parse_float(val: str, row_idx: int | None = None, col_idx: int | None = None) -> float | None:
    """Safely parse a cell string into a float value.

    Strips commas, unit symbols, and matches standard numeric patterns.
    Uses context-aware metadata to reject years, voltages, state names,
    and serial numbers.

    Args:
        val: Raw string to convert.
        row_idx: Optional 0-based row index in NormalizedTable.
        col_idx: Optional 0-based column index in NormalizedTable.

    Returns:
        Float value if matching, else None.
    """
    if not val:
        return None

    # 1. Use the active annotated table context if available
    global _active_annotated_table
    if _active_annotated_table is not None and row_idx is not None and col_idx is not None:
        if row_idx < len(_active_annotated_table.annotations):
            row_ann = _active_annotated_table.annotations[row_idx]
            if col_idx < len(row_ann):
                ann = row_ann[col_idx]
                if not ann.is_numeric or ann.entity_type in (
                    "year", "voltage", "header", "state", "utility", "serial_number"
                ):
                    return None
                return ann.numeric_value

    # 2. Direct string fallback check using EntityRecognizer
    try:
        from table_scraper.entity_recognition import EntityRecognizer, EntityType
        recognizer = EntityRecognizer()
        match = recognizer.recognize(val)
        if match.entity_type in (EntityType.YEAR, EntityType.VOLTAGE, EntityType.STATE, EntityType.UTILITY):
            return None
    except Exception:
        pass

    cleaned = val.replace(",", "").strip()
    match_num = re.search(r"[-+]?\d+(?:\.\d+)?", cleaned)
    if match_num:
        try:
            return float(match_num.group(0))
        except ValueError:
            return None
    return None


def generate_record_id(parameter_id: str, state: str, utility: str, extra: str) -> str:
    """Compute a unique deterministic record identifier.

    Uses SHA-256 to hash fields and returns a 16-character hex signature.

    Args:
        parameter_id: Owning parameter ID.
        state: Target state name.
        utility: Target utility name.
        extra: Additional differentiating coordinates (e.g. category, voltage).

    Returns:
        A unique 16-character string.
    """
    coord = f"{parameter_id}:{state.lower()}:{utility.lower()}:{extra.lower()}"
    return hashlib.sha256(coord.encode("utf-8")).hexdigest()[:16]


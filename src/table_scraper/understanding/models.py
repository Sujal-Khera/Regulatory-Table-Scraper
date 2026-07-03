"""Models representing document semantic structures and annotations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from table_scraper.domain.models import NormalizedTable


class ColumnRole(str, Enum):
    STATE = "state"
    UTILITY = "utility"
    CATEGORY = "category"
    SUBCATEGORY = "subcategory"
    YEAR = "year"
    VALUE = "value"
    UNIT = "unit"
    NOTES = "notes"
    VOLTAGE = "voltage"
    SERIAL_NUMBER = "serial_number"
    UNKNOWN = "unknown"


class EntityType(str, Enum):
    STATE = "state"
    UTILITY = "utility"
    YEAR = "year"
    VOLTAGE = "voltage"
    CHARGE = "charge"
    PERCENTAGE = "percentage"
    COUNT = "count"
    CATEGORY = "category"
    UNIT = "unit"
    NOTES = "notes"
    SERIAL_NUMBER = "serial_number"
    HEADER = "header"
    EMPTY = "empty"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ColumnDescriptor:
    """Semantic description of one table column."""

    index: int
    raw_headers: list[str]
    display_name: str
    semantic_role: ColumnRole
    entity_type: EntityType | None = None
    unit: str | None = None
    year: str | None = None
    group: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HeaderTree:
    """Tree representation of multi-row headers."""

    raw_rows: list[list[str]]
    depth: int
    tree_data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CellAnnotation:
    """Semantic annotation for a single cell."""

    entity_type: EntityType
    canonical_value: str | None
    confidence: float
    is_numeric: bool
    numeric_value: float | None
    unit: str | None
    flags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AnnotatedTable:
    """Table accompanied by semantic column descriptors and cell annotations."""

    parameter_id: str
    table: NormalizedTable
    columns: list[ColumnDescriptor]
    annotations: list[list[CellAnnotation]]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentContext:
    """Partial document context containing semantic table information."""

    parameter_id: str
    table: NormalizedTable
    columns: list[ColumnDescriptor]
    annotations: list[list[CellAnnotation]]
    header_tree: HeaderTree
    source_pages: list[int] = field(default_factory=list)

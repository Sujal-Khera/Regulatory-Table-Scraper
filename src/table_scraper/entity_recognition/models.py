"""Domain models for the entity recognition engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EntityType(str, Enum):
    STATE = "state"
    UTILITY = "utility"
    VOLTAGE = "voltage"
    YEAR = "year"
    UNIT = "unit"
    CATEGORY = "category"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class EntityMatch:
    """Represents a successfully recognized semantic entity."""

    raw_value: str
    entity_type: EntityType
    canonical_value: str
    confidence: float
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MatcherResult:
    """Outcome of a single matcher invocation."""

    matched: bool
    match: EntityMatch | None = None


@dataclass(frozen=True)
class RecognitionContext:
    """Contextual metadata to aid disambiguation and inference."""

    active_state: str | None = None
    column_header: str | None = None
    row_index: int | None = None
    col_index: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

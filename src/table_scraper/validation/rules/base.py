"""Pluggable validation rule base for post-parse quality checks."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from table_scraper.domain.models import ParseResult, ValidationCheck


class BaseValidationRule(ABC):
    """Abstract validation rule.

    Subclasses implement structural or value checks on ParsedRecords within
    a ParseResult using configuration rules.
    """

    @property
    @abstractmethod
    def rule_id(self) -> str:
        """Unique rule identifier."""

    @abstractmethod
    def run(self, result: ParseResult, config: Any) -> ValidationCheck:
        """Execute rule and return a ValidationCheck outcome."""
        raise NotImplementedError


def check_required_fields(record_fields: dict[str, Any], required: list[str]) -> list[str]:
    """Helper to find missing required fields in a record.

    Args:
        record_fields: ParsedRecord fields mapping.
        required: List of required field keys.

    Returns:
        List of missing field names.
    """
    missing = []
    for field in required:
        if field not in record_fields or record_fields[field] is None:
            missing.append(field)
        elif isinstance(record_fields[field], str) and not record_fields[field].strip():
            missing.append(field)
    return missing


def check_numeric_range(
    val: float | None,
    min_val: float | None = None,
    max_val: float | None = None,
) -> bool:
    """Helper to check if a numeric value is within standard thresholds.

    Args:
        val: The float value to check.
        min_val: Optional inclusive lower bound.
        max_val: Optional inclusive upper bound.

    Returns:
        True if the value is within range, else False.
    """
    if val is None:
        return False
    if min_val is not None and val < min_val:
        return False
    if max_val is not None and val > max_val:
        return False
    return True


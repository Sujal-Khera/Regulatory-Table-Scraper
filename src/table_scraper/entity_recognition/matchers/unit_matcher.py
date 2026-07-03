"""Unit matcher implementation."""

from __future__ import annotations

import re
from typing import Any

from table_scraper.entity_recognition.models import (
    EntityMatch,
    EntityType,
    MatcherResult,
    RecognitionContext,
)
from table_scraper.entity_recognition.utils import clean_text_basic, load_yaml_catalog


class UnitMatcher:
    """Matches charge units (Rs/kWh, Rs/kW/month, %, etc.) using catalogs, regex, and context."""

    def __init__(self) -> None:
        self.units: dict[str, list[str]] = {}
        self._load_catalogs()

        # Compile common unit regexes
        self.unit_patterns = [
            re.compile(r"\b(?:rs|paise|p|₹|rupees)\s*/\s*(?:kwh|kw|kva|mw)\b", re.IGNORECASE),
            re.compile(r"\b(?:rs|paise|p|₹|rupees)\s*/\s*(?:kw|kva|mw)\s*/\s*(?:month|m|day|d)\b", re.IGNORECASE),
            re.compile(r"%", re.IGNORECASE),
        ]

    def _load_catalogs(self) -> None:
        data = load_yaml_catalog("charge_units.yaml")
        if data and "units" in data:
            for canonical, info in data["units"].items():
                unit_name = str(canonical).strip()
                aliases = [str(a).strip().lower() for a in info.get("aliases", [])]
                self.units[unit_name] = aliases

    def match(
        self, value: str, context: RecognitionContext | None = None
    ) -> MatcherResult:
        """Identify if a string matches a canonical unit or expression."""
        cleaned = clean_text_basic(value)
        if not cleaned:
            return MatcherResult(matched=False)

        lower_val = cleaned.lower()

        # 1. Exact catalog match (or catalog alias match)
        for canonical, aliases in self.units.items():
            if lower_val == canonical.lower() or lower_val in aliases:
                return MatcherResult(
                    matched=True,
                    match=EntityMatch(
                        raw_value=value,
                        entity_type=EntityType.UNIT,
                        canonical_value=canonical,
                        confidence=1.0,
                        provenance={"method": "catalog_unit_match", "unit": canonical},
                    ),
                )

        # 2. Check if the string contains "%" or is percent/percentage
        if "%" in cleaned or "percent" in lower_val or "percentage" in lower_val:
            return MatcherResult(
                matched=True,
                match=EntityMatch(
                    raw_value=value,
                    entity_type=EntityType.UNIT,
                    canonical_value="%",
                    confidence=0.95,
                    provenance={"method": "percentage_character_match"},
                ),
            )

        # 3. Pattern-based regex matching for unregistered units
        for pattern in self.unit_patterns:
            m = pattern.search(cleaned)
            if m:
                # Deduce canonical form: e.g. "₹/kWh" -> "Rs/kWh"
                matched_str = m.group(0).lower()
                canonical = cleaned
                if "kwh" in matched_str:
                    canonical = "Rs/kWh"
                elif "kw" in matched_str and "month" in matched_str:
                    canonical = "Rs/kW/month"
                elif "kva" in matched_str and "month" in matched_str:
                    canonical = "Rs/kVA/month"
                elif "mw" in matched_str and "day" in matched_str:
                    canonical = "Rs/MW/day"

                return MatcherResult(
                    matched=True,
                    match=EntityMatch(
                        raw_value=value,
                        entity_type=EntityType.UNIT,
                        canonical_value=canonical,
                        confidence=0.85,
                        provenance={"method": "regex_unit_match", "matched_pattern": pattern.pattern},
                    ),
                )

        # 4. Column header context: if the header has unit keywords
        if context and context.column_header:
            header_lower = context.column_header.lower()
            if "unit" in header_lower or "charge" in header_lower:
                # If header suggests unit/charge, match keywords like "rs", "paise", "kw", etc.
                if any(kw in lower_val for kw in ["rs", "paise", "kwh", "kw", "kva", "%"]):
                    # Return best guess
                    canonical = cleaned
                    if "kwh" in lower_val:
                        canonical = "Rs/kWh"
                    elif "kw" in lower_val:
                        canonical = "Rs/kW/month"
                    elif "kva" in lower_val:
                        canonical = "Rs/kVA/month"

                    return MatcherResult(
                        matched=True,
                        match=EntityMatch(
                            raw_value=value,
                            entity_type=EntityType.UNIT,
                            canonical_value=canonical,
                            confidence=0.75,
                            provenance={"method": "column_header_unit_context"},
                        ),
                    )

        return MatcherResult(matched=False)

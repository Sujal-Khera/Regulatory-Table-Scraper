"""Year matcher implementation."""

from __future__ import annotations

import re
from typing import Any

from table_scraper.entity_recognition.models import (
    EntityMatch,
    EntityType,
    MatcherResult,
    RecognitionContext,
)
from table_scraper.entity_recognition.utils import clean_text_basic


class YearMatcher:
    """Matches calendar years and financial years using regexes and normalizes them."""

    def __init__(self) -> None:
        # Regexes for financial years (e.g. 2023-24, FY 2023-24, 2023/24, FY 23-24)
        self.fy_pattern1 = re.compile(r"\b(20\d{2})\s*-\s*(\d{2})\b")  # matches 2023-24
        self.fy_pattern2 = re.compile(r"\b(20\d{2})\s*/\s*(\d{2})\b")  # matches 2023/24
        self.fy_pattern3 = re.compile(r"\bFY\s*(\d{2})\s*-\s*(\d{2})\b", re.IGNORECASE)  # matches FY 23-24
        self.fy_pattern4 = re.compile(r"\bFY\s*(20\d{2})\s*-\s*(\d{2})\b", re.IGNORECASE)  # matches FY 2023-24

        # Regexes for calendar years (e.g. 2023, 2024)
        self.cy_pattern = re.compile(r"\b(20\d{2})\b")

    def match(
        self, value: str, context: RecognitionContext | None = None
    ) -> MatcherResult:
        """Identify and normalize year expressions (both calendar and financial)."""
        cleaned = clean_text_basic(value)
        if not cleaned:
            return MatcherResult(matched=False)

        # 1. Match financial year: 2023-24
        m = self.fy_pattern1.search(cleaned)
        if m:
            start_year = m.group(1)
            end_year = m.group(2)
            canonical = f"{start_year}-{end_year}"
            return MatcherResult(
                matched=True,
                match=EntityMatch(
                    raw_value=value,
                    entity_type=EntityType.YEAR,
                    canonical_value=canonical,
                    confidence=1.0,
                    provenance={"method": "regex_fy_standard", "type": "financial_year"},
                ),
            )

        # 2. Match financial year with slash: 2023/24
        m = self.fy_pattern2.search(cleaned)
        if m:
            start_year = m.group(1)
            end_year = m.group(2)
            canonical = f"{start_year}-{end_year}"
            return MatcherResult(
                matched=True,
                match=EntityMatch(
                    raw_value=value,
                    entity_type=EntityType.YEAR,
                    canonical_value=canonical,
                    confidence=0.95,
                    provenance={"method": "regex_fy_slash", "type": "financial_year"},
                ),
            )

        # 3. Match FY 2023-24
        m = self.fy_pattern4.search(cleaned)
        if m:
            start_year = m.group(1)
            end_year = m.group(2)
            canonical = f"{start_year}-{end_year}"
            return MatcherResult(
                matched=True,
                match=EntityMatch(
                    raw_value=value,
                    entity_type=EntityType.YEAR,
                    canonical_value=canonical,
                    confidence=1.0,
                    provenance={"method": "regex_fy_prefix_long", "type": "financial_year"},
                ),
            )

        # 4. Match FY 23-24
        m = self.fy_pattern3.search(cleaned)
        if m:
            start_short = m.group(1)
            end_short = m.group(2)
            canonical = f"20{start_short}-{end_short}"
            return MatcherResult(
                matched=True,
                match=EntityMatch(
                    raw_value=value,
                    entity_type=EntityType.YEAR,
                    canonical_value=canonical,
                    confidence=0.9,
                    provenance={"method": "regex_fy_prefix_short", "type": "financial_year"},
                ),
            )

        # 5. Match calendar year: 2023
        m = self.cy_pattern.search(cleaned)
        if m:
            cy_val = m.group(1)
            # If we match a calendar year, check context: does it mean a financial year?
            # E.g. in cross subsidy, columns might just be calendar year strings.
            # We return it as a calendar year.
            return MatcherResult(
                matched=True,
                match=EntityMatch(
                    raw_value=value,
                    entity_type=EntityType.YEAR,
                    canonical_value=cy_val,
                    confidence=0.85,
                    provenance={"method": "regex_cy", "type": "calendar_year"},
                ),
            )

        # 6. Fallback year match for strings like "Year 2023" or similar
        # Check if contains a 4-digit number starting with 20
        fallback_match = re.search(r"\b(20\d{2})\b", cleaned)
        if fallback_match:
            year_val = fallback_match.group(1)
            return MatcherResult(
                matched=True,
                match=EntityMatch(
                    raw_value=value,
                    entity_type=EntityType.YEAR,
                    canonical_value=year_val,
                    confidence=0.7,
                    provenance={"method": "fallback_year_search"},
                ),
            )

        return MatcherResult(matched=False)

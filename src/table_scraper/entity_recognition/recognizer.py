"""Orchestrator class for entity recognition."""

from __future__ import annotations

from typing import Any

from table_scraper.entity_recognition.matchers.category_matcher import CategoryMatcher
from table_scraper.entity_recognition.matchers.state_matcher import StateMatcher
from table_scraper.entity_recognition.matchers.unit_matcher import UnitMatcher
from table_scraper.entity_recognition.matchers.utility_matcher import UtilityMatcher
from table_scraper.entity_recognition.matchers.voltage_matcher import VoltageMatcher
from table_scraper.entity_recognition.matchers.year_matcher import YearMatcher
from table_scraper.entity_recognition.models import (
    EntityMatch,
    EntityType,
    RecognitionContext,
)


class EntityRecognizer:
    """Orchestrates all semantic matchers to perform unified entity recognition."""

    def __init__(self) -> None:
        self.state_matcher = StateMatcher()
        self.utility_matcher = UtilityMatcher()
        self.voltage_matcher = VoltageMatcher()
        self.year_matcher = YearMatcher()
        self.unit_matcher = UnitMatcher()
        self.category_matcher = CategoryMatcher()

    def recognize(
        self, value: str, context: RecognitionContext | None = None
    ) -> EntityMatch:
        """Run all matchers and return the highest confidence match, fallback to UNKNOWN."""
        matches: list[EntityMatch] = []

        # Run specific matchers
        state_m = self.recognize_state(value, context)
        if state_m:
            matches.append(state_m)

        utility_m = self.recognize_utility(value, context)
        if utility_m:
            matches.append(utility_m)

        voltage_m = self.recognize_voltage(value, context)
        if voltage_m:
            matches.append(voltage_m)

        year_m = self.recognize_year(value, context)
        if year_m:
            matches.append(year_m)

        unit_m = self.recognize_unit(value, context)
        if unit_m:
            matches.append(unit_m)

        category_m = self.recognize_category(value, context)
        if category_m:
            matches.append(category_m)

        if not matches:
            return EntityMatch(
                raw_value=value,
                entity_type=EntityType.UNKNOWN,
                canonical_value=value,
                confidence=0.0,
                provenance={"method": "no_match_fallback"},
            )

        # Return match with highest confidence
        matches.sort(key=lambda m: m.confidence, reverse=True)
        return matches[0]

    def recognize_state(
        self, value: str, context: RecognitionContext | None = None
    ) -> EntityMatch | None:
        """Check if value is a state."""
        result = self.state_matcher.match(value, context)
        return result.match if result.matched else None

    def recognize_utility(
        self, value: str, context: RecognitionContext | None = None
    ) -> EntityMatch | None:
        """Check if value is a utility/DISCOM."""
        result = self.utility_matcher.match(value, context)
        return result.match if result.matched else None

    def recognize_voltage(
        self, value: str, context: RecognitionContext | None = None
    ) -> EntityMatch | None:
        """Check if value is a voltage expression."""
        result = self.voltage_matcher.match(value, context)
        return result.match if result.matched else None

    def recognize_year(
        self, value: str, context: RecognitionContext | None = None
    ) -> EntityMatch | None:
        """Check if value is a year expression."""
        result = self.year_matcher.match(value, context)
        return result.match if result.matched else None

    def recognize_unit(
        self, value: str, context: RecognitionContext | None = None
    ) -> EntityMatch | None:
        """Check if value is a unit expression."""
        result = self.unit_matcher.match(value, context)
        return result.match if result.matched else None

    def recognize_category(
        self, value: str, context: RecognitionContext | None = None
    ) -> EntityMatch | None:
        """Check if value is a consumer category."""
        result = self.category_matcher.match(value, context)
        return result.match if result.matched else None

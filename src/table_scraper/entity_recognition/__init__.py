"""Entity Recognition Engine package."""

from __future__ import annotations

from table_scraper.entity_recognition.matchers.category_matcher import CategoryMatcher
from table_scraper.entity_recognition.matchers.state_matcher import StateMatcher
from table_scraper.entity_recognition.matchers.unit_matcher import UnitMatcher
from table_scraper.entity_recognition.matchers.utility_matcher import UtilityMatcher
from table_scraper.entity_recognition.matchers.voltage_matcher import VoltageMatcher
from table_scraper.entity_recognition.matchers.year_matcher import YearMatcher
from table_scraper.entity_recognition.models import (
    EntityMatch,
    EntityType,
    MatcherResult,
    RecognitionContext,
)
from table_scraper.entity_recognition.recognizer import EntityRecognizer

__all__ = [
    "EntityRecognizer",
    "EntityMatch",
    "EntityType",
    "MatcherResult",
    "RecognitionContext",
    "StateMatcher",
    "UtilityMatcher",
    "VoltageMatcher",
    "YearMatcher",
    "UnitMatcher",
    "CategoryMatcher",
]

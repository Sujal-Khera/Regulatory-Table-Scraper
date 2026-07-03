"""Automatic table pattern detection."""

from table_scraper.patterns.classifier import classify_table
from table_scraper.patterns.features import extract_features
from table_scraper.patterns.signatures import load_pattern_signatures

__all__ = ["classify_table", "extract_features", "load_pattern_signatures"]

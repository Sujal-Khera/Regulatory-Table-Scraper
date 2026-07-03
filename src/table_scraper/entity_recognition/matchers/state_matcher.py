"""State matcher implementation."""

from __future__ import annotations

import difflib
from typing import Any

from table_scraper.entity_recognition.models import (
    EntityMatch,
    EntityType,
    MatcherResult,
    RecognitionContext,
)
from table_scraper.entity_recognition.utils import clean_text_basic, load_yaml_catalog


class StateMatcher:
    """Matches Indian states and Union Territories using catalogs and fuzzy matching."""

    def __init__(self) -> None:
        self.states: list[str] = []
        self.aliases: dict[str, str] = {}
        self._load_catalogs()

    def _load_catalogs(self) -> None:
        # Load states.yaml
        states_data = load_yaml_catalog("states.yaml")
        if states_data and "states" in states_data:
            self.states = [str(s).strip() for s in states_data["states"]]

        # Load state_aliases.yaml
        aliases_data = load_yaml_catalog("state_aliases.yaml")
        if aliases_data and "aliases" in aliases_data:
            for k, v in aliases_data["aliases"].items():
                self.aliases[str(k).strip().lower()] = str(v).strip()

    def _normalize_comparison(self, s: str) -> str:
        """Normalize string for robust comparison (lowercase, strip, and/& normalized)."""
        normalized = clean_text_basic(s).lower()
        normalized = normalized.replace("&", "and")
        # remove extra spacing
        return " ".join(normalized.split())

    def match(
        self, value: str, context: RecognitionContext | None = None
    ) -> MatcherResult:
        """Identify if a string matches a canonical state or alias."""
        cleaned = clean_text_basic(value)
        if not cleaned:
            return MatcherResult(matched=False)

        norm_val = self._normalize_comparison(cleaned)

        # 1. Exact catalog match
        for state in self.states:
            if self._normalize_comparison(state) == norm_val:
                return MatcherResult(
                    matched=True,
                    match=EntityMatch(
                        raw_value=value,
                        entity_type=EntityType.STATE,
                        canonical_value=state,
                        confidence=1.0,
                        provenance={"method": "exact_catalog_match"},
                    ),
                )

        # 2. Alias catalog match
        if norm_val in self.aliases:
            canonical = self.aliases[norm_val]
            return MatcherResult(
                matched=True,
                match=EntityMatch(
                    raw_value=value,
                    entity_type=EntityType.STATE,
                    canonical_value=canonical,
                    confidence=1.0,
                    provenance={"method": "alias_catalog_match", "alias": cleaned},
                ),
            )

        # 3. Handle minor spelling or OCR errors via fuzzy matching
        best_state = None
        best_ratio = 0.0

        for state in self.states:
            norm_state = self._normalize_comparison(state)
            ratio = difflib.SequenceMatcher(None, norm_val, norm_state).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_state = state

        # Repeat for aliases to see if it matches an alias fuzzily
        best_alias_canonical = None
        best_alias_ratio = 0.0
        for alias, canonical in self.aliases.items():
            norm_alias = self._normalize_comparison(alias)
            ratio = difflib.SequenceMatcher(None, norm_val, norm_alias).ratio()
            if ratio > best_alias_ratio:
                best_alias_ratio = ratio
                best_alias_canonical = canonical

        # Pick the best overall fuzzy match
        if best_ratio >= 0.85 or best_alias_ratio >= 0.85:
            if best_ratio >= best_alias_ratio:
                return MatcherResult(
                    matched=True,
                    match=EntityMatch(
                        raw_value=value,
                        entity_type=EntityType.STATE,
                        canonical_value=best_state,
                        confidence=round(best_ratio * 0.9, 2),
                        provenance={"method": "fuzzy_state_match", "similarity": best_ratio},
                    ),
                )
            else:
                return MatcherResult(
                    matched=True,
                    match=EntityMatch(
                        raw_value=value,
                        entity_type=EntityType.STATE,
                        canonical_value=best_alias_canonical,
                        confidence=round(best_alias_ratio * 0.9, 2),
                        provenance={"method": "fuzzy_alias_match", "similarity": best_alias_ratio},
                    ),
                )

        return MatcherResult(matched=False)

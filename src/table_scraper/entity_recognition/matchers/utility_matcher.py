"""Utility matcher implementation."""

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


class UtilityMatcher:
    """Matches Indian utility/DISCOM names using catalogs, regex patterns, and context."""

    def __init__(self) -> None:
        self.utilities_by_state: dict[str, list[str]] = {}
        # Inverted index to map utility name -> parent state
        self.utility_to_state: dict[str, str] = {}
        self._load_catalogs()

        # Common utility pattern keywords / regexes
        self.utility_patterns = [
            re.compile(r"\b[A-Z]{2,7}(?:PDCL|ED|TRANSCO|GENCO|SPDCL|EPDCL|CPDCL|NPDCL|EDCL)\b", re.IGNORECASE),
            re.compile(r"\b[A-Za-z0-9_]+(?:\s+Electricity\s+Department|\s+ED)\b", re.IGNORECASE),
            re.compile(r"\b(?:DISCOM|TRANSCO|GENCO|Licensee)\b", re.IGNORECASE),
        ]

    def _load_catalogs(self) -> None:
        data = load_yaml_catalog("utilities.yaml")
        if data and "utilities" in data:
            for state, utils in data["utilities"].items():
                state_name = str(state).strip()
                utils_list = [str(u).strip() for u in utils]
                self.utilities_by_state[state_name] = utils_list
                for u in utils_list:
                    # Store mapping for lowercase match
                    self.utility_to_state[u.lower()] = state_name

    def _clean_utility_name(self, name: str) -> str:
        """Strip leading/trailing slash/asterisks/spaces and normalize case."""
        return clean_text_basic(name)

    def match(
        self, value: str, context: RecognitionContext | None = None
    ) -> MatcherResult:
        """Identify if a string matches a catalog utility or is recognized as one by regex/context."""
        cleaned = self._clean_utility_name(value)
        if not cleaned:
            return MatcherResult(matched=False)

        lower_val = cleaned.lower()

        # 1. Exact catalog match
        if lower_val in self.utility_to_state:
            # Find the original case name from the catalog list
            parent_state = self.utility_to_state[lower_val]
            canonical_name = cleaned
            for u in self.utilities_by_state.get(parent_state, []):
                if u.lower() == lower_val:
                    canonical_name = u
                    break

            return MatcherResult(
                matched=True,
                match=EntityMatch(
                    raw_value=value,
                    entity_type=EntityType.UTILITY,
                    canonical_value=canonical_name,
                    confidence=1.0,
                    provenance={
                        "method": "exact_catalog_match",
                        "parent_state": parent_state,
                    },
                ),
            )

        # 2. Substring or fuzzy catalog match
        for u_lower, parent_state in self.utility_to_state.items():
            # Check if value is a substring of the catalog utility, or vice versa
            if (len(lower_val) >= 4 and lower_val in u_lower) or (len(u_lower) >= 4 and u_lower in lower_val):
                # Retrieve canonical name
                canonical_name = cleaned
                for u in self.utilities_by_state.get(parent_state, []):
                    if u.lower() == u_lower:
                        canonical_name = u
                        break

                return MatcherResult(
                    matched=True,
                    match=EntityMatch(
                        raw_value=value,
                        entity_type=EntityType.UTILITY,
                        canonical_value=canonical_name,
                        confidence=0.9,
                        provenance={
                            "method": "catalog_substring_match",
                            "parent_state": parent_state,
                            "catalog_entry": canonical_name,
                        },
                    ),
                )

        # 3. Context state constraint: check utilities of the active state
        if context and context.active_state:
            state_utils = self.utilities_by_state.get(context.active_state, [])
            for u in state_utils:
                if u.lower() in lower_val or lower_val in u.lower():
                    return MatcherResult(
                        matched=True,
                        match=EntityMatch(
                            raw_value=value,
                            entity_type=EntityType.UTILITY,
                            canonical_value=u,
                            confidence=0.85,
                            provenance={
                                "method": "active_state_context_match",
                                "parent_state": context.active_state,
                            },
                        ),
                    )

        # 4. Regex pattern matching (fallback for unregistered utilities)
        for pattern in self.utility_patterns:
            if pattern.search(cleaned):
                # Infer parent state if active state is set in context
                inferred_state = context.active_state if context else None
                return MatcherResult(
                    matched=True,
                    match=EntityMatch(
                        raw_value=value,
                        entity_type=EntityType.UTILITY,
                        canonical_value=cleaned,
                        confidence=0.6,
                        provenance={
                            "method": "regex_pattern_match",
                            "pattern": pattern.pattern,
                            "parent_state": inferred_state,
                        },
                    ),
                )

        # 5. Header-based context fallback: if the column header is "Utility" or similar
        if context and context.column_header:
            header_lower = context.column_header.lower()
            if any(kw in header_lower for kw in ["utility", "discom", "licensee"]):
                # Avoid matching simple numbers or states as utility fallback
                is_numeric = False
                try:
                    float(cleaned.replace("%", "").replace(",", "").strip())
                    is_numeric = True
                except ValueError:
                    pass

                if not is_numeric and len(cleaned) > 2:
                    return MatcherResult(
                        matched=True,
                        match=EntityMatch(
                            raw_value=value,
                            entity_type=EntityType.UTILITY,
                            canonical_value=cleaned,
                            confidence=0.5,
                            provenance={
                                "method": "column_header_context_fallback",
                                "parent_state": context.active_state,
                            },
                        ),
                    )

        return MatcherResult(matched=False)

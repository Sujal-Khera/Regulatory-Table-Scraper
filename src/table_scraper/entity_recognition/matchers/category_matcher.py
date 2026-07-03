"""Category matcher implementation."""

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


class CategoryMatcher:
    """Matches consumer categories and subcategories using catalogs, patterns, and keywords."""

    def __init__(self) -> None:
        self.categories: dict[str, list[str]] = {}
        self.subcategories: dict[str, list[str]] = {}
        self._load_catalogs()

    def _load_catalogs(self) -> None:
        data = load_yaml_catalog("consumer_categories.yaml")
        if data and "categories" in data:
            for cat, info in data["categories"].items():
                cat_name = str(cat).strip()
                aliases = [str(a).strip().lower() for a in info.get("aliases", [])]
                subcats = [str(s).strip() for s in info.get("subcategories", [])]
                self.categories[cat_name] = aliases
                self.subcategories[cat_name] = subcats

    def match(
        self, value: str, context: RecognitionContext | None = None
    ) -> MatcherResult:
        """Identify if a string matches a canonical consumer category or subcategory."""
        cleaned = clean_text_basic(value)
        if not cleaned:
            return MatcherResult(matched=False)

        lower_val = cleaned.lower()

        # 1. Exact catalog category or alias match
        for cat, aliases in self.categories.items():
            if lower_val == cat.lower() or lower_val in aliases:
                return MatcherResult(
                    matched=True,
                    match=EntityMatch(
                        raw_value=value,
                        entity_type=EntityType.CATEGORY,
                        canonical_value=cat,
                        confidence=1.0,
                        provenance={"method": "catalog_category_match", "category": cat},
                    ),
                )

        # 2. Exact catalog subcategory match
        for cat, subcats in self.subcategories.items():
            for subcat in subcats:
                if lower_val == subcat.lower():
                    return MatcherResult(
                        matched=True,
                        match=EntityMatch(
                            raw_value=value,
                            entity_type=EntityType.CATEGORY,
                            canonical_value=cat,
                            confidence=0.95,
                            provenance={"method": "catalog_subcategory_match", "category": cat, "subcategory": subcat},
                        ),
                    )

        # 3. Substring keyword match (e.g. "HT Industry" contains "industry")
        for cat, aliases in self.categories.items():
            # Check if any alias or the category name itself is a word inside the cleaned string
            keywords = [cat.lower()] + aliases
            for kw in keywords:
                if len(kw) >= 3 and re.search(rf"\b{re.escape(kw)}\b", lower_val):
                    return MatcherResult(
                        matched=True,
                        match=EntityMatch(
                            raw_value=value,
                            entity_type=EntityType.CATEGORY,
                            canonical_value=cat,
                            confidence=0.9,
                            provenance={"method": "substring_category_match", "category": cat, "matched_keyword": kw},
                        ),
                    )

        # 4. Context-based matching: if column header indicates consumer category
        if context and context.column_header:
            header_lower = context.column_header.lower()
            if any(kw in header_lower for kw in ["category", "consumer", "tariff"]):
                # If header says "category", and the cell is non-numeric, it is likely a consumer category
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
                            entity_type=EntityType.CATEGORY,
                            canonical_value=cleaned,
                            confidence=0.75,
                            provenance={"method": "column_header_category_context"},
                        ),
                    )

        return MatcherResult(matched=False)

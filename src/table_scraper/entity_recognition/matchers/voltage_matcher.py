"""Voltage matcher implementation."""

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


class VoltageMatcher:
    """Matches voltage levels and bands using catalogs, regex, and keywords."""

    def __init__(self) -> None:
        self.voltages: dict[str, list[str]] = {}
        self._load_catalogs()

        # Compile common voltage patterns
        self.kv_pattern = re.compile(r"\b(\d+)\s*k[Vv]\b")
        self.volts_pattern = re.compile(r"\b(\d+)\s*[Vv]\b")

    def _load_catalogs(self) -> None:
        data = load_yaml_catalog("voltage_levels.yaml")
        if data and "voltages" in data:
            for band, info in data["voltages"].items():
                band_name = str(band).strip()
                aliases = [str(a).strip().lower() for a in info.get("aliases", [])]
                self.voltages[band_name] = aliases

    def match(
        self, value: str, context: RecognitionContext | None = None
    ) -> MatcherResult:
        """Identify if a string matches a voltage level, band, or expression."""
        cleaned = clean_text_basic(value)
        if not cleaned:
            return MatcherResult(matched=False)

        lower_val = cleaned.lower()

        # 1. Match regex patterns like "11 kV" or "33kV"
        kv_match = self.kv_pattern.search(cleaned)
        if kv_match:
            kv_val = int(kv_match.group(1))
            # Categorize the band based on kv value
            if kv_val < 11:
                band = "LT"
            elif kv_val <= 33:
                band = "HT"
            else:
                band = "EHT"

            canonical = f"{kv_val} kV"
            return MatcherResult(
                matched=True,
                match=EntityMatch(
                    raw_value=value,
                    entity_type=EntityType.VOLTAGE,
                    canonical_value=canonical,
                    confidence=0.95,
                    provenance={"method": "regex_kv_match", "kv_value": kv_val, "band": band},
                ),
            )

        # 2. Match regex pattern for pure volts "230 V" or "415 V"
        volts_match = self.volts_pattern.search(cleaned)
        if volts_match:
            volts_val = int(volts_match.group(1))
            canonical = f"{volts_val} V"
            return MatcherResult(
                matched=True,
                match=EntityMatch(
                    raw_value=value,
                    entity_type=EntityType.VOLTAGE,
                    canonical_value=canonical,
                    confidence=0.9,
                    provenance={"method": "regex_volts_match", "volts_value": volts_val, "band": "LT"},
                ),
            )

        # 3. Alias lookup in catalog (e.g. "low tension" -> "LT")
        for band, aliases in self.voltages.items():
            if lower_val == band.lower() or lower_val in aliases:
                return MatcherResult(
                    matched=True,
                    match=EntityMatch(
                        raw_value=value,
                        entity_type=EntityType.VOLTAGE,
                        canonical_value=band,
                        confidence=1.0,
                        provenance={"method": "catalog_alias_match", "band": band},
                    ),
                )


        # 4. Partial substring match in catalog aliases (e.g. "ht industrial" contains "ht")
        for band, aliases in self.voltages.items():
            for alias in aliases:
                # To prevent matching short terms like "lt" inside words like "result" or "surcharge",
                # check for word boundaries
                if re.search(rf"\b{re.escape(alias)}\b", lower_val):
                    return MatcherResult(
                        matched=True,
                        match=EntityMatch(
                            raw_value=value,
                            entity_type=EntityType.VOLTAGE,
                            canonical_value=band,
                            confidence=0.8,
                            provenance={"method": "substring_alias_match", "band": band, "matched_keyword": alias},
                        ),
                    )

        # 5. Header-based context: if the header has a voltage keyword
        if context and context.column_header:
            header_lower = context.column_header.lower()
            # If the column header is a voltage (e.g. "11 kV"), and this cell has numeric context
            header_kv = self.kv_pattern.search(context.column_header)
            if header_kv and len(cleaned) < 5:
                # If we're parsing values under a "11 kV" column, the voltage context is the header's voltage
                kv_val = int(header_kv.group(1))
                return MatcherResult(
                    matched=True,
                    match=EntityMatch(
                        raw_value=value,
                        entity_type=EntityType.VOLTAGE,
                        canonical_value=f"{kv_val} kV",
                        confidence=0.7,
                        provenance={"method": "column_header_voltage_context", "kv_value": kv_val},
                    ),
                )

        return MatcherResult(matched=False)

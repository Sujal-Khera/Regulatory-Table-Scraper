"""Shared utilities for parsing units from text headers or cell values."""

from __future__ import annotations


def extract_unit_from_text(text: str, default: str = "Rs/kWh") -> str:
    """Extract standard billing unit from a text string.

    Matches standard regulatory charge units like Rs/kWh, Rs/kW/month, Rs/kVA/month,
    Rs/MW/month, Rs/MW/day, paise/kWh, etc.
    """
    text_lower = text.lower()
    if "paise/kwh" in text_lower or "p/kwh" in text_lower:
        return "paise/kWh"
    if "rs/kw/month" in text_lower or "rs/kw/m" in text_lower or "rs./kw/month" in text_lower:
        return "Rs/kW/month"
    if "rs/kva/month" in text_lower or "rs/kva/m" in text_lower:
        return "Rs/kVA/month"
    if "rs/mw/month" in text_lower or "rs/mw/m" in text_lower:
        return "Rs/MW/month"
    if "rs/mw/day" in text_lower or "rs/mw/d" in text_lower:
        return "Rs/MW/day"
    if "rs/mwh" in text_lower:
        return "Rs/MWh"
    if "%" in text_lower or "percent" in text_lower:
        return "%"
    if "rs cr" in text_lower or "rs. cr" in text_lower:
        return "Rs Cr."
    if "rs/kwh" in text_lower or "rs./kwh" in text_lower:
        return "Rs/kWh"
    return default

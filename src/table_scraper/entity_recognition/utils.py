"""Utility functions for entity recognition matchers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from table_scraper.config.loader import resolve_config_root


def get_catalog_path(filename: str) -> Path:
    """Resolve the path to a catalog YAML file."""
    config_root = resolve_config_root()
    return config_root / "catalogs" / filename


def load_yaml_catalog(filename: str) -> dict[str, Any]:
    """Load a YAML catalog file from the config directories."""
    path = get_catalog_path(filename)
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def clean_text_basic(val: str) -> str:
    """Normalize string values by stripping slashes, asterisks, and whitespace."""
    if not val:
        return ""
    # Strip leading/trailing whitespaces, slash characters, and asterisks
    cleaned = val.strip()
    # Strip any sequence of leading/trailing '/' or '*' and whitespaces around them
    cleaned = re.sub(r'^[\s/*]+', '', cleaned)
    cleaned = re.sub(r'[\s/*]+$', '', cleaned)
    # Re-strip
    return cleaned.strip()

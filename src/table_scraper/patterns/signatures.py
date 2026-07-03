"""Load pattern signatures from config/patterns/pattern_signatures.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import yaml

DEFAULT_SIGNATURES: dict[str, Any] = {
    "key_value": {
        "weights": {
            "column_count": -4.0,
            "text_density": 2.0,
            "numeric_density": 1.0,
            "hierarchy_indicators": -3.0,
            "indentation_indicators": -2.0,
        },
        "rules": [
            {"feature": "column_count", "operator": "equals", "value": 2.0, "score": 15.0},
            {"feature": "column_count", "operator": "greater_than", "value": 2.0, "score": -15.0},
        ],
    },
    "numeric_matrix": {
        "weights": {
            "numeric_density": 8.0,
            "column_count": 2.0,
            "state_name_occurrence": -3.0,
            "hierarchy_indicators": -2.0,
        },
        "rules": [
            {"feature": "column_count", "operator": "greater_than", "value": 2.0, "score": 5.0},
            {"feature": "numeric_density", "operator": "greater_than", "value": 0.5, "score": 8.0},
            {"feature": "state_name_occurrence", "operator": "equals", "value": 0.0, "score": 5.0},
        ],
    },
    "state_block_matrix": {
        "weights": {
            "state_name_occurrence": 10.0,
            "hierarchy_indicators": 6.0,
            "numeric_density": 4.0,
            "column_count": 2.0,
        },
        "rules": [
            {"feature": "state_name_occurrence", "operator": "greater_than", "value": 0.0, "score": 15.0},
            {"feature": "hierarchy_indicators", "operator": "greater_than", "value": 0.0, "score": 8.0},
        ],
    },
    "wide_table": {
        "weights": {
            "column_count": 8.0,
            "numeric_density": 3.0,
            "average_cells_per_row": 4.0,
        },
        "rules": [
            {"feature": "column_count", "operator": "greater_than", "value": 8.0, "score": 20.0},
            {"feature": "column_count", "operator": "less_than", "value": 4.0, "score": -20.0},
        ],
    },
    "simple_matrix": {
        "weights": {
            "numeric_density": 6.0,
            "column_count": 2.0,
            "state_name_occurrence": -6.0,
            "hierarchy_indicators": -6.0,
        },
        "rules": [
            {"feature": "column_count", "operator": "greater_than", "value": 2.0, "score": 5.0},
            {"feature": "state_name_occurrence", "operator": "equals", "value": 0.0, "score": 10.0},
            {"feature": "hierarchy_indicators", "operator": "equals", "value": 0.0, "score": 8.0},
        ],
    },
    "hierarchical_parent_child": {
        "weights": {
            "text_density": 6.0,
            "hierarchy_indicators": 8.0,
            "indentation_indicators": 4.0,
            "numeric_density": -4.0,
        },
        "rules": [
            {"feature": "hierarchy_indicators", "operator": "greater_than", "value": 0.0, "score": 10.0},
            {"feature": "numeric_density", "operator": "less_than", "value": 0.3, "score": 5.0},
        ],
    },
}


def load_pattern_signatures(config_path: str | None = None) -> dict[str, Any]:
    """Load pattern signature weights and rules from YAML configuration.

    If the configuration file does not exist, falls back to the static
    in-memory DEFAULT_SIGNATURES definition.

    Args:
        config_path: Explicit path to the YAML file, or None to search standard paths.

    Returns:
        Dictionary of TablePattern key -> signature ruleset configuration.
    """
    paths_to_try = []
    if config_path:
        paths_to_try.append(Path(config_path))
    else:
        paths_to_try.extend(
            [
                Path("src/table_scraper/config/patterns/pattern_signatures.yaml"),
                Path("config/patterns/pattern_signatures.yaml"),
                Path("table_scraper/config/patterns/pattern_signatures.yaml"),
            ]
        )

    for p in paths_to_try:
        if p.exists() and p.is_file():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    if isinstance(data, dict):
                        return data
            except Exception:
                continue

    return DEFAULT_SIGNATURES


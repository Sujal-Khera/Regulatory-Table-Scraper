"""Convert ParsedRecord list to typed DataFrame with column order from config."""

from __future__ import annotations

from typing import Any
import pandas as pd

from table_scraper.domain.models import ParsedRecord


def _load_export_config(parameter_id: str) -> dict[str, Any]:
    """Load the export section from a parameter YAML file.

    Returns a dict with keys: column_display_names, exclude_columns.
    Returns empty dict if config cannot be loaded.
    """
    try:
        from table_scraper.config.loader import get_config_loader
        loader = get_config_loader()
        param_yaml = loader._load_yaml(f"parsers/parameters/{parameter_id}.yaml")
        if isinstance(param_yaml, dict):
            return param_yaml.get("export", {})
    except Exception:
        pass
    return {}


def records_to_dataframe(records: list[ParsedRecord], schema: Any) -> pd.DataFrame:
    """Build a pandas DataFrame from ParseResult records.

    Applies column ordering, handles missing keys by injecting null placeholders,
    and formats types for database warehouse loading.

    Args:
        records: List of ParsedRecord instances.
        schema: Parameter schema defining column layouts and types.

    Returns:
        Structured pandas DataFrame.
    """
    if not records:
        return pd.DataFrame()

    # Resolve parameter_id from first record for export config lookup
    parameter_id = records[0].parameter_id if records else None
    export_cfg = _load_export_config(parameter_id) if parameter_id else {}

    # 1. Flatten records into row dicts
    rows_data: list[dict[str, Any]] = []
    for record in records:
        row_dict = dict(record.fields)
        # Map state_level sentinels to empty strings for Excel exports
        for key in ["utility", "discom"]:
            if row_dict.get(key) == "state_level":
                row_dict[key] = ""
        # Attach system coordinate metadata for lineage audit
        row_dict["record_id"] = record.record_id
        row_dict["parameter_id"] = record.parameter_id
        row_dict["confidence"] = record.confidence
        # Add source_pages as comma-separated string
        row_dict["source_pages"] = ", ".join(str(p) for p in record.source_pages) if record.source_pages else ""
        rows_data.append(row_dict)

    df = pd.DataFrame(rows_data)

    # 2. Resolve target column schema ordering
    column_ordering = None
    if schema is not None:
        if hasattr(schema, "columns") and schema.columns is not None:
            column_ordering = list(schema.columns)
        elif hasattr(schema, "fields") and hasattr(schema.fields, "keys"):
            column_ordering = list(schema.fields.keys())
        elif isinstance(schema, dict):
            if "columns" in schema and schema["columns"] is not None:
                column_ordering = list(schema["columns"])
            elif "fields" in schema and isinstance(schema["fields"], dict):
                column_ordering = list(schema["fields"].keys())
            else:
                column_ordering = list(schema.keys())

    # 3. Align DataFrame schema and column sorting
    if column_ordering:
        # Pre-populate missing columns with None to prevent KeyError
        for col in column_ordering:
            if col not in df.columns:
                df[col] = None

        # Build column index (schema columns first, then presentation fields)
        meta_cols = ["record_id", "parameter_id"]
        presentation_cols = ["confidence", "source_pages"]
        ordered_cols = [c for c in column_ordering if c not in meta_cols and c not in presentation_cols]
        for m in presentation_cols:
            if m in df.columns:
                ordered_cols.append(m)
        for m in meta_cols:
            if m in df.columns:
                ordered_cols.append(m)

        # Retain any extra fields not defined in schema at the end
        extra_cols = [c for c in df.columns if c not in ordered_cols]
        df = df[ordered_cols + extra_cols]

    # 4. Exclude internal columns per export config
    exclude_columns = export_cfg.get("exclude_columns", [])
    if exclude_columns:
        cols_to_drop = [c for c in exclude_columns if c in df.columns]
        if cols_to_drop:
            df = df.drop(columns=cols_to_drop)

    # 5. Sort by State → Utility/Discom → Category (where available)
    sort_cols = []
    for col_name in ["state", "utility", "discom", "consumer_category", "consumer_subcategory"]:
        if col_name in df.columns:
            sort_cols.append(col_name)
    if sort_cols:
        df = df.sort_values(by=sort_cols, na_position="last").reset_index(drop=True)

    # 6. Rename columns using display name map from export config
    display_names = export_cfg.get("column_display_names", {})
    if display_names:
        rename_map = {k: v for k, v in display_names.items() if k in df.columns}
        if rename_map:
            df = df.rename(columns=rename_map)

    return df

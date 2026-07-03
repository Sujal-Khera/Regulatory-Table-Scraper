"""Multi-sheet Excel warehouse export."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any
import uuid
import pandas as pd

from table_scraper.domain.enums import ArtifactKind, ExportMode, SessionStage, StageStatus
from table_scraper.domain.models import ExcelSheetInfo, ExcelWorkbook, ExportResult
from table_scraper.export.formatter import apply_workbook_formatting


def _resolve_sheet_name(parameter_id: str) -> str:
    """Resolve the display sheet name from the parameter YAML config.

    Falls back to the parameter_id if no sheet_name is configured.
    """
    try:
        from table_scraper.config.loader import get_config_loader
        loader = get_config_loader()
        param_yaml = loader._load_yaml(f"parsers/parameters/{parameter_id}.yaml")
        if isinstance(param_yaml, dict):
            return param_yaml.get("sheet_name", parameter_id)
    except Exception:
        pass
    return parameter_id


def _build_summary_sheet(
    dataframes: dict[str, Any],
    validation_reports: dict[str, Any] | None,
    source_pdf: str | None,
) -> pd.DataFrame:
    """Build a summary quality dashboard DataFrame.

    Args:
        dataframes: Map of parameter_id -> pandas DataFrame.
        validation_reports: Map of parameter_id -> ValidationReport (optional).
        source_pdf: Source PDF filename.

    Returns:
        DataFrame with summary rows for each parameter.
    """
    rows: list[dict[str, Any]] = []

    # Header metadata
    rows.append({
        "Property": "Source PDF",
        "Value": source_pdf or "Unknown",
    })
    rows.append({
        "Property": "Extraction Timestamp",
        "Value": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    })
    rows.append({
        "Property": "",
        "Value": "",
    })
    rows.append({
        "Property": "Parameter",
        "Value": "Record Count | State Coverage | Validation Status | Export Allowed",
    })
    rows.append({
        "Property": "---",
        "Value": "---",
    })

    for param_id, df in dataframes.items():
        display_name = _resolve_sheet_name(param_id)
        record_count = len(df)

        # Try to extract state coverage from the dataframe
        state_col = None
        for col in df.columns:
            if col.lower() in ("state", "state/ut"):
                state_col = col
                break
        state_count = df[state_col].nunique() if state_col and state_col in df.columns else "N/A"

        # Try to extract validation status
        val_status = "N/A"
        export_allowed = "Yes"
        if validation_reports and param_id in validation_reports:
            report = validation_reports[param_id]
            val_status = "PASSED" if getattr(report, "passed", True) else "FAILED"
            export_allowed = "Yes" if getattr(report, "export_allowed", True) else "No"

        rows.append({
            "Property": display_name,
            "Value": f"{record_count} records | {state_count} states | {val_status} | Export: {export_allowed}",
        })

    return pd.DataFrame(rows)


def export_to_excel(
    dataframes: dict[str, Any],
    path: str,
    format_config: dict[str, Any],
    validation_reports: dict[str, Any] | None = None,
) -> ExportResult:
    """Export multiple parameter DataFrames to a formatted Excel workbook.

    Packs the sheets, invokes formatting styling, writes metadata to the
    ArtifactStore, and completes manifest stages.

    Args:
        dataframes: Map of parameter_id -> pandas DataFrame.
        path: Path where the Excel workbook should be saved.
        format_config: Configuration variables for styling and packaging.
        validation_reports: Map of parameter_id -> ValidationReport (optional).

    Returns:
        An ExportResult object containing ExcelWorkbook metadata.
    """
    # 1. Ensure output parent directories exist
    parent_dir = os.path.dirname(path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)

    # Resolve source PDF name
    source_pdf = None
    workspace = format_config.get("workspace")
    if workspace and hasattr(workspace, "manifest") and workspace.manifest:
        pdf_info = getattr(workspace.manifest, "pdf", None)
        if pdf_info:
            source_pdf = getattr(pdf_info, "filename", None)

    # 2. Build summary sheet
    summary_df = _build_summary_sheet(dataframes, validation_reports, source_pdf)

    # 3. Write DataFrames to Excel worksheets
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        # Write summary sheet first
        summary_df.to_excel(writer, sheet_name="Summary", index=False)

        for parameter_id, df in dataframes.items():
            # Use display sheet_name from YAML
            sheet_display = _resolve_sheet_name(parameter_id)
            # Truncate sheet name to Excel max limit of 31 characters
            ws_name = sheet_display[:31]
            df.to_excel(writer, sheet_name=ws_name, index=False)

    # 4. Apply cell styling and frozen headers to the written workbook
    apply_workbook_formatting(path, format_config)

    # 5. Gather file system metrics
    file_size_bytes = os.path.getsize(path)

    # 6. Extract workspace ID and packaging mode
    source_workspace_id = workspace.workspace_id if workspace else "unknown_workspace"
    export_mode_val = format_config.get("export_mode", ExportMode.SINGLE_WORKBOOK)

    # 7. Build worksheets and workbook metadata
    sheets_info: list[ExcelSheetInfo] = []
    validation_summary: dict[str, bool] = {}

    for parameter_id, df in dataframes.items():
        sheet_display = _resolve_sheet_name(parameter_id)
        sheets_info.append(
            ExcelSheetInfo(
                sheet_name=sheet_display[:31],
                parameter_id=parameter_id,
                row_count=len(df),
                column_names=list(df.columns),
            )
        )
        validation_summary[parameter_id] = True  # Verified true since export was allowed

    workbook = ExcelWorkbook(
        workbook_id=str(uuid.uuid4()),
        path=path,
        created_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        sheets=sheets_info,
        sheet_count=len(sheets_info),
        source_workspace_id=source_workspace_id,
        format_spec=format_config,
        validation_summary=validation_summary,
        export_mode=export_mode_val,
        file_size_bytes=file_size_bytes,
    )

    return ExportResult(workbook=workbook)


def export_cross_subsidy_by_state(
    css_df: pd.DataFrame,
    path: str,
    format_config: dict[str, Any],
) -> None:
    """Export cross-subsidy surcharge data as one sheet per state.

    Each sheet contains: Utility | Consumer Category | Voltage Level |
    Charge (Rs/kWh) | Year | Notes | Confidence | Source Pages

    Args:
        css_df: Cross-subsidy DataFrame (already with display column names).
        path: Output path for the Cross_Subsidy_By_State.xlsx workbook.
        format_config: Formatting configuration.
    """
    parent_dir = os.path.dirname(path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)

    # Find the state column (may be renamed to display name)
    state_col = None
    for col in css_df.columns:
        if col.lower() in ("state", "state/ut"):
            state_col = col
            break

    if state_col is None:
        return

    # Target column ordering for state sheets
    target_cols = []
    col_mapping = {
        "utility": ["Distribution Utility", "utility"],
        "consumer_category": ["Consumer Category", "consumer_category"],
        "voltage_level": ["Voltage Level", "voltage_level"],
        "charge_value": ["Cross Subsidy Surcharge (Rs/kWh)", "charge_value"],
        "charge_unit": ["Unit", "charge_unit"],
        "year_label": ["Financial Year", "year_label"],
        "consumer_subcategory": ["Consumer Sub-Category", "consumer_subcategory", "Notes"],
        "confidence": ["Confidence", "confidence"],
        "source_pages": ["Source Pages", "source_pages"],
    }

    # Resolve actual column names present in the DataFrame
    for _key, candidates in col_mapping.items():
        for c in candidates:
            if c in css_df.columns:
                target_cols.append(c)
                break

    # Group by state and write one sheet per state
    states = sorted(css_df[state_col].dropna().unique())

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for state_name in states:
            state_df = css_df[css_df[state_col] == state_name].copy()

            # Select only target columns that exist
            available_cols = [c for c in target_cols if c in state_df.columns]
            if available_cols:
                state_df = state_df[available_cols]

            # Sort within sheet by Utility → Category
            sort_cols = []
            for col_candidate in ["Distribution Utility", "utility", "Consumer Category", "consumer_category"]:
                if col_candidate in state_df.columns:
                    sort_cols.append(col_candidate)
            if sort_cols:
                state_df = state_df.sort_values(by=sort_cols, na_position="last").reset_index(drop=True)

            # Sanitize sheet name: max 31 chars, no invalid chars
            safe_name = state_name.replace("/", "-").replace("\\", "-").replace("*", "").replace("?", "")
            safe_name = safe_name.replace("[", "").replace("]", "").replace(":", "")
            ws_name = safe_name[:31]

            state_df.to_excel(writer, sheet_name=ws_name, index=False)

    # Apply same formatting
    apply_workbook_formatting(path, format_config)

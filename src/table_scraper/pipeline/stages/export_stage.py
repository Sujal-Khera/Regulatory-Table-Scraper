"""Export stage — validate and export one or more parameters to Excel."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from table_scraper.domain.enums import SessionStage, StageStatus, ArtifactKind
from table_scraper.domain.models import ExportResult
from table_scraper.storage.artifact_store import ArtifactStore
from table_scraper.validation.runner import validate_parse_result
from table_scraper.export.dataframe_builder import records_to_dataframe
from table_scraper.export.excel_exporter import export_to_excel, export_cross_subsidy_by_state
from table_scraper.config.loader import load_parameter_config
from table_scraper.pipeline.session import PipelineSession


def stage_export(
    session: PipelineSession,
    parameter_ids: list[str],
    output_path: Path | str,
) -> ExportResult | None:
    """Run validation gate and Excel export for multiple parameters."""
    workspace = session.workspace
    manifest = workspace.manifest
    store = ArtifactStore(workspace)

    dataframes: dict[str, Any] = {}
    validation_reports: dict[str, Any] = {}

    # Ensure settings carries workspace context for nested artifact writes
    settings_dict = {}
    if session.settings is not None:
        if isinstance(session.settings, dict):
            settings_dict = dict(session.settings)
        else:
            settings_dict = {
                k: getattr(session.settings, k)
                for k in dir(session.settings)
                if not k.startswith("_")
            }
    settings_dict["workspace"] = workspace

    for parameter_id in parameter_ids:
        # 1. Load parse records
        if not store.exists(ArtifactKind.RECORDS, parameter_id):
            continue

        parse_result = store.read(ArtifactKind.RECORDS, parameter_id)

        # 2. Execute validation checks
        report = validate_parse_result(parse_result, settings_dict)
        validation_reports[parameter_id] = report

        # Update manifest for VALIDATE parameter stage
        rel_val_path = workspace.path_for(ArtifactKind.VALIDATION, parameter_id).relative_to(workspace.root).as_posix()
        val_paths = [rel_val_path]

        with workspace._lock:
            parameter_status = dict(workspace.manifest.parameter_status)
            entry = dict(parameter_status.get(parameter_id, {}))
            entry[SessionStage.VALIDATE.value] = {
                "status": StageStatus.COMPLETE.value,
                "artifact_paths": val_paths,
                "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            }
            parameter_status[parameter_id] = entry
            workspace.manifest = replace(
                workspace.manifest,
                parameter_status=parameter_status,
                updated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            )
            workspace._persist_manifest()

        workspace.mark_stage_complete(
            stage=SessionStage.VALIDATE,
            input_hash=manifest.pdf.content_hash,
            artifact_paths=val_paths,
        )

        # 3. Export gating: skip exporting if blocking validation failures exist
        if not report.export_allowed:
            continue

        # 4. Read schema mapping and build pandas DataFrame
        schema = None
        try:
            param_cfg = load_parameter_config(parameter_id)
            schema = getattr(param_cfg, "schema", None)
        except Exception:
            pass

        df = records_to_dataframe(parse_result.records, schema)
        dataframes[parameter_id] = df

    if not dataframes:
        return None

    # 5. Export to multi-sheet Excel file (with summary sheet)
    export_result = export_to_excel(
        dataframes, str(output_path), settings_dict,
        validation_reports=validation_reports,
    )

    # 6. Export Cross_Subsidy_By_State workbook if cross_subsidy data is present
    export_paths = [str(Path(output_path).name)]
    if "cross_subsidy_surcharge" in dataframes:
        css_df = dataframes["cross_subsidy_surcharge"]
        state_wb_path = Path(output_path).parent / "Cross_Subsidy_By_State.xlsx"
        try:
            export_cross_subsidy_by_state(css_df, str(state_wb_path), settings_dict)
            if state_wb_path.is_file():
                export_paths.append(state_wb_path.name)
        except Exception:
            pass  # Non-blocking: warehouse workbook is the primary artifact

    # 7. Update manifest for EXPORT parameter stage
    for parameter_id in dataframes.keys():
        with workspace._lock:
            parameter_status = dict(workspace.manifest.parameter_status)
            entry = dict(parameter_status.get(parameter_id, {}))
            entry[SessionStage.EXPORT.value] = {
                "status": StageStatus.COMPLETE.value,
                "artifact_paths": export_paths,
                "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            }
            parameter_status[parameter_id] = entry
            workspace.manifest = replace(
                workspace.manifest,
                parameter_status=parameter_status,
                updated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            )
            workspace._persist_manifest()

    workspace.mark_stage_complete(
        stage=SessionStage.EXPORT,
        input_hash=manifest.pdf.content_hash,
        artifact_paths=export_paths,
    )

    return export_result

"""Execute pipeline stages in order with idempotent skip-if-complete behavior."""

from __future__ import annotations

from typing import Any

from table_scraper.domain.enums import SessionStage, StageStatus, ArtifactKind
from table_scraper.domain.models import PipelineResult, ExportResult
from table_scraper.storage.artifact_store import ArtifactStore
from table_scraper.pipeline.session import PipelineSession

# Import stage functions
from table_scraper.pipeline.stages.index_stage import stage_index
from table_scraper.pipeline.stages.discover_stage import stage_discover
from table_scraper.pipeline.stages.extract_stage import stage_extract
from table_scraper.pipeline.stages.parse_stage import stage_parse
from table_scraper.pipeline.stages.export_stage import stage_export


def run_pipeline(session: PipelineSession, stages: list[SessionStage]) -> PipelineResult:
    """Execute requested pipeline stages sequentially.

    Supports resume capabilities by verifying manifest stage statuses and
    stale/invalidation flags.

    Args:
        session: Active PipelineSession container.
        stages: Ordered list of SessionStages to execute.

    Returns:
        PipelineResult summary of manifest state and outputs.
    """
    workspace = session.workspace
    store = ArtifactStore(workspace)

    # 1. Attempt to resume user selections and catalogs from ArtifactStore
    if session.catalog is None and store.exists(ArtifactKind.PARAMETER_CATALOG):
        try:
            session.catalog = store.read(ArtifactKind.PARAMETER_CATALOG)
        except Exception:
            pass

    if session.user_selection is None and store.exists(ArtifactKind.USER_SELECTION):
        try:
            session.user_selection = store.read(ArtifactKind.USER_SELECTION)
        except Exception:
            pass

    # 2. Iterate stages in order
    export_result = None
    for stage in stages:
        if stage == SessionStage.INDEX:
            stage_index(session)

        elif stage == SessionStage.DISCOVER:
            stage_discover(session)

        elif stage == SessionStage.SELECT:
            # Save user selection checkpoint if available
            if session.user_selection is not None:
                store.write(ArtifactKind.USER_SELECTION, session.user_selection)
                for param_id, pr in session.user_selection.confirmed_ranges.items():
                    store.write(ArtifactKind.CONFIRMED_RANGE, pr, param_id)

                workspace.mark_stage_complete(
                    stage=SessionStage.SELECT,
                    input_hash=workspace.manifest.pdf.content_hash,
                    artifact_paths=[
                        str(workspace.path_for(ArtifactKind.USER_SELECTION).relative_to(workspace.root))
                    ],
                )

        elif stage == SessionStage.EXTRACT:
            if not session.user_selection:
                raise ValueError("User Selection checkpoint missing for stage EXTRACT.")

            for param_id in session.user_selection.parameter_ids:
                page_range = session.user_selection.confirmed_ranges.get(param_id)
                if not page_range:
                    # Fallback to catalog suggested range
                    if session.catalog:
                        for p in session.catalog.parameters:
                            if p.parameter_id == param_id:
                                page_range = p.suggested_range
                                break
                if not page_range:
                    raise ValueError(f"No page range confirmed or suggested for parameter {param_id}")

                stage_extract(session, param_id, page_range)

        elif stage in (SessionStage.NORMALIZE, SessionStage.CLASSIFY, SessionStage.PARSE):
            if not session.user_selection:
                raise ValueError(f"User Selection checkpoint missing for stage {stage.value}.")

            for param_id in session.user_selection.parameter_ids:
                stage_parse(session, param_id)

        elif stage in (SessionStage.VALIDATE, SessionStage.EXPORT):
            if not session.user_selection:
                raise ValueError(f"User Selection checkpoint missing for stage {stage.value}.")

            # Determine export target path
            export_path = session.user_selection.export_path
            if not export_path:
                export_path = str(workspace.path_for(ArtifactKind.EXCEL))

            export_result = stage_export(session, session.user_selection.parameter_ids, export_path)

    # 3. Compile pipeline results
    processed_params = session.user_selection.parameter_ids if session.user_selection else []
    export_results: list[ExportResult] = []
    if export_result is not None:
        export_results.append(export_result)

    return PipelineResult(
        manifest=workspace.manifest,
        parameters_processed=processed_params,
        export_results=export_results,
    )


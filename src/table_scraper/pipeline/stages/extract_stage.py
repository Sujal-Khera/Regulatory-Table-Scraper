"""Extract stage — raw table extraction and merge for one parameter."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from table_scraper.domain.enums import SessionStage, StageStatus, ArtifactKind
from table_scraper.domain.models import PageRange
from table_scraper.storage.artifact_store import ArtifactStore
from table_scraper.adapters.pdf_reader import PdfPlumberReader
from table_scraper.extraction.table_extractor import extract_raw_tables
from table_scraper.extraction.table_merger import merge_multi_page_tables
from table_scraper.pipeline.session import PipelineSession


def stage_extract(
    session: PipelineSession,
    parameter_id: str,
    page_range: PageRange,
) -> None:
    """Run extraction and merge for a parameter."""
    workspace = session.workspace
    manifest = workspace.manifest
    store = ArtifactStore(workspace)

    # Helper to check parameter-scoped stage status
    def _is_param_complete() -> bool:
        param_dict = manifest.parameter_status.get(parameter_id, {})
        stage_dict = param_dict.get(SessionStage.EXTRACT.value, {})
        return stage_dict.get("status") == StageStatus.COMPLETE.value

    # 1. Skip if already completed and not stale
    if _is_param_complete() and not workspace.is_stage_stale(SessionStage.EXTRACT):
        if store.exists(ArtifactKind.RAW_MERGED, parameter_id):
            return

    # 2. Extract raw tables page by page
    pdf_path = workspace.manifest.pdf.path
    with PdfPlumberReader.open(pdf_path) as reader:
        raw_pages = extract_raw_tables(reader, page_range, parameter_id, session.settings)

    # 3. Merge pages and strip duplicate headers
    merged = merge_multi_page_tables(raw_pages, session.settings)

    # 4. Write artifacts
    store.write(ArtifactKind.RAW_PAGES, raw_pages, parameter_id)
    store.write(ArtifactKind.RAW_MERGED, merged, parameter_id)

    # 5. Mark stage complete for parameter in parameter_status manifest
    rel_pages_path = str(workspace.path_for(ArtifactKind.RAW_PAGES, parameter_id).relative_to(workspace.root))
    rel_merged_path = str(workspace.path_for(ArtifactKind.RAW_MERGED, parameter_id).relative_to(workspace.root))
    artifact_paths = [rel_pages_path, rel_merged_path]

    with workspace._lock:
        parameter_status = dict(workspace.manifest.parameter_status)
        entry = dict(parameter_status.get(parameter_id, {}))
        entry[SessionStage.EXTRACT.value] = {
            "status": StageStatus.COMPLETE.value,
            "artifact_paths": artifact_paths,
            "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }
        parameter_status[parameter_id] = entry
        workspace.manifest = replace(
            workspace.manifest,
            parameter_status=parameter_status,
            updated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        )
        workspace._persist_manifest()

    # Also record global stage completion
    workspace.mark_stage_complete(
        stage=SessionStage.EXTRACT,
        input_hash=manifest.pdf.content_hash,
        artifact_paths=artifact_paths,
    )


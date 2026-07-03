"""Index stage — build PageIndex for the workspace PDF."""

from __future__ import annotations

from table_scraper.domain.enums import SessionStage, StageStatus, ArtifactKind
from table_scraper.domain.models import PageIndex
from table_scraper.storage.artifact_store import ArtifactStore
from table_scraper.adapters.pdf_reader import PdfPlumberReader
from table_scraper.indexing.page_indexer import build_page_index
from table_scraper.pipeline.session import PipelineSession


def stage_index(session: PipelineSession) -> None:
    """Run full-PDF page indexing stage.

    Checks workspace manifest to avoid redundant work unless stale or missing.
    """
    workspace = session.workspace
    manifest = workspace.manifest
    store = ArtifactStore(workspace)

    # 1. Skip if already completed and not stale
    if workspace.stage_status(SessionStage.INDEX) == StageStatus.COMPLETE and not workspace.is_stage_stale(SessionStage.INDEX):
        if store.exists(ArtifactKind.PAGE_INDEX):
            return

    # 2. Execute indexing
    pdf_path = workspace.manifest.pdf.path
    with PdfPlumberReader.open(pdf_path) as reader:
        result = build_page_index(reader, workspace, session.settings)

    # 3. Mark stage complete in workspace manifest
    artifact_paths = [
        str(workspace.path_for(ArtifactKind.PAGE_INDEX).relative_to(workspace.root)),
        str(workspace.path_for(ArtifactKind.PAGE_INDEX_CSV).relative_to(workspace.root)),
    ]
    workspace.mark_stage_complete(
        stage=SessionStage.INDEX,
        input_hash=manifest.pdf.content_hash,
        artifact_paths=artifact_paths,
    )


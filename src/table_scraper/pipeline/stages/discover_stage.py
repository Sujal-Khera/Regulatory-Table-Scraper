"""Discover stage — build ParameterCatalog and suggested page ranges."""

from __future__ import annotations

from table_scraper.domain.enums import SessionStage, StageStatus, ArtifactKind
from table_scraper.storage.artifact_store import ArtifactStore
from table_scraper.adapters.pdf_reader import PdfPlumberReader
from table_scraper.discovery.toc_extractor import extract_toc
from table_scraper.discovery.parameter_catalog import build_parameter_catalog
from table_scraper.pipeline.session import PipelineSession


def stage_discover(session: PipelineSession) -> None:
    """Run TOC and parameter discovery stage.

    Saves the ParameterCatalog to ArtifactStore and updates the stage manifest.
    """
    workspace = session.workspace
    manifest = workspace.manifest
    store = ArtifactStore(workspace)

    # 1. Check if discover stage is already complete and not stale
    if workspace.stage_status(SessionStage.DISCOVER) == StageStatus.COMPLETE and not workspace.is_stage_stale(SessionStage.DISCOVER):
        if store.exists(ArtifactKind.PARAMETER_CATALOG):
            try:
                session.catalog = store.read(ArtifactKind.PARAMETER_CATALOG)
                return
            except Exception:
                pass

    # 2. Load dependencies: PageIndex
    if not store.exists(ArtifactKind.PAGE_INDEX):
        raise FileNotFoundError("PageIndex artifact missing; run stage_index first.")
    page_index = store.read(ArtifactKind.PAGE_INDEX)

    # 3. Extract TOC and merge with index anchors
    pdf_path = workspace.manifest.pdf.path
    with PdfPlumberReader.open(pdf_path) as reader:
        toc = extract_toc(reader, session.settings)

    catalog = build_parameter_catalog(toc, page_index, session.settings)
    session.catalog = catalog

    # 4. Save ParameterCatalog to workspace
    store.write(ArtifactKind.PARAMETER_CATALOG, catalog)

    # 5. Mark stage completed in manifest
    artifact_paths = [
        workspace.path_for(ArtifactKind.PARAMETER_CATALOG).relative_to(workspace.root).as_posix(),
    ]
    workspace.mark_stage_complete(
        stage=SessionStage.DISCOVER,
        input_hash=manifest.pdf.content_hash,
        artifact_paths=artifact_paths,
    )


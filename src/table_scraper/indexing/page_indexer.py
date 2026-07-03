"""Build full-PDF PageIndex from PdfReader."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import time
from typing import Any

from table_scraper.domain.enums import ArtifactKind, TitleSource
from table_scraper.domain.models import PageIndex, PageIndexResult, PageRecord
from table_scraper.domain.protocols import PdfReader
from table_scraper.indexing.title_detector import detect_table_titles
from table_scraper.storage.artifact_store import ArtifactCodec, ArtifactStore
from table_scraper.storage.workspace import Workspace


def build_page_index(
    pdf: PdfReader,
    workspace: Workspace,
    config: Any,
) -> PageIndexResult:
    """Iterate all pages and build a searchable PageIndex.

    Performs page-by-page text and table geometry scanning, invokes the title
    detector to extract regulatory anchors, constructs the PageIndex aggregate
    object, and persists JSON/CSV artifacts.

    Args:
        pdf: Open PdfReader resource wrapper.
        workspace: PDF-scoped workspace for path resolution and manifest updates.
        config: Application configuration bundle.

    Returns:
        Summary result of the indexing stage.
    """
    start_time = time.perf_counter()

    page_records: list[PageRecord] = []
    title_anchor_pages: list[int] = []
    pages_with_titles = 0
    pages_with_tables = 0

    # 1. Page-by-page extraction
    for page_num in range(1, pdf.page_count + 1):
        # Extract page text
        page_text = pdf.extract_text(page_num)
        text_length = len(page_text)

        # Detect table titles
        titles = detect_table_titles(page_text, config)

        # Attach canonical page number and source to detected titles
        for title in titles:
            title.pdf_page = page_num
            if title.source is None:
                title.source = TitleSource.PAGE_SCAN

        # Detect tables and calculate count
        try:
            tables = pdf.extract_tables(page_num)
            table_count = len(tables)
        except Exception:
            table_count = 0

        contains_table = table_count > 0

        # Create the PageRecord snapshot
        record = PageRecord(
            pdf_page=page_num,
            page_text=page_text,
            table_titles=titles,
            contains_table=contains_table,
            text_length=text_length,
            table_count=table_count,
            indexed_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        )
        page_records.append(record)

        # Track aggregates
        if titles:
            pages_with_titles += 1
            title_anchor_pages.append(page_num)
        if contains_table:
            pages_with_tables += 1

    end_time = time.perf_counter()
    build_duration_ms = int((end_time - start_time) * 1000)

    # 2. Resolve index version & config hash
    store = ArtifactStore(workspace)
    index_version = 1
    try:
        old_index = store.read(ArtifactKind.PAGE_INDEX)
        if old_index and hasattr(old_index, "index_version"):
            index_version = old_index.index_version + 1
    except Exception:
        pass

    config_snapshot_hash = None
    try:
        if config is not None:
            encoded_cfg = ArtifactCodec.encode_value(config)
            serialized_cfg = json.dumps(encoded_cfg, sort_keys=True)
            config_snapshot_hash = hashlib.sha256(serialized_cfg.encode("utf-8")).hexdigest()
    except Exception:
        pass

    # 3. Create canonical PageIndex object
    page_index = PageIndex(
        schema_version="1.0.0",
        workspace_id=workspace.workspace_id,
        pdf_hash=workspace.manifest.pdf.content_hash,
        page_count=pdf.page_count,
        pages=page_records,
        indexed_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        index_version=index_version,
        pages_with_titles=pages_with_titles,
        pages_with_tables=pages_with_tables,
        title_anchor_pages=sorted(title_anchor_pages),
        build_duration_ms=build_duration_ms,
        config_snapshot_hash=config_snapshot_hash,
    )

    # 4. Persist index artifacts
    # JSON Persistence
    store.write(ArtifactKind.PAGE_INDEX, page_index)

    # Flat CSV Persistence for human inspection
    csv_rows = []
    for record in page_records:
        csv_rows.append(
            {
                "pdf_page": record.pdf_page,
                "contains_table": record.contains_table,
                "text_length": record.text_length,
                "table_count": record.table_count or 0,
                "table_titles": "; ".join(t.raw_text for t in record.table_titles),
            }
        )
    store.write(ArtifactKind.PAGE_INDEX_CSV, csv_rows)

    # SQLite Search Index (FTS5) - Try/catch wrapper in case sqlite_index is not implemented
    try:
        from table_scraper.storage.sqlite_index import PageSearchIndex

        db_path = str(workspace.path_for(ArtifactKind.PAGE_INDEX_DB))
        search_index = PageSearchIndex(db_path)
        search_index.build(page_index)
    except (NotImplementedError, ImportError):
        # Swallow not implemented error if FTS component is a placeholder
        pass
    except Exception:
        # Resilient build boundary
        pass

    return PageIndexResult(
        page_index=page_index,
        pages_indexed=pdf.page_count,
        pages_with_titles=pages_with_titles,
    )


"""Parse stage — normalize, classify, and parse one parameter."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from table_scraper.domain.enums import SessionStage, StageStatus, ArtifactKind
from table_scraper.storage.artifact_store import ArtifactStore
from table_scraper.pipeline.session import PipelineSession


def stage_parse(session: PipelineSession, parameter_id: str) -> None:
    """Run normalization, classification, and parsing for a parameter."""
    workspace = session.workspace
    manifest = workspace.manifest
    store = ArtifactStore(workspace)

    # Helper to check parameter-scoped stage status
    def _is_param_complete(stg: SessionStage) -> bool:
        param_dict = manifest.parameter_status.get(parameter_id, {})
        stage_dict = param_dict.get(stg.value, {})
        return stage_dict.get("status") == StageStatus.COMPLETE.value

    # 1. Skip if already completed and not stale
    if _is_param_complete(SessionStage.PARSE) and not workspace.is_stage_stale(SessionStage.PARSE):
        if store.exists(ArtifactKind.RECORDS, parameter_id):
            return

    # 2. Load input: RAW_MERGED
    if not store.exists(ArtifactKind.RAW_MERGED, parameter_id):
        raise FileNotFoundError(f"Raw merged table missing for parameter {parameter_id}")
    merged = store.read(ArtifactKind.RAW_MERGED, parameter_id)

    # 3. Normalize table
    from table_scraper.normalization.geometry import normalize_geometry
    from table_scraper.normalization.text_cleanup import normalize_text_cells
    from table_scraper.normalization.hierarchy import propagate_hierarchy
    from table_scraper.normalization.block_segmentation import segment_state_blocks

    geom = normalize_geometry(merged)
    cleaned = normalize_text_cells(geom)
    normalized = propagate_hierarchy(cleaned, session.settings)


    # Write normalized table
    store.write(ArtifactKind.NORMALIZED, normalized, parameter_id)

    # Block segmentation
    blocks = segment_state_blocks(normalized, session.settings)

    # Write blocks
    store.write(ArtifactKind.STATE_BLOCKS, blocks, parameter_id)

    # Update manifest for NORMALIZE parameter stage
    rel_norm_path = str(workspace.path_for(ArtifactKind.NORMALIZED, parameter_id).relative_to(workspace.root))
    rel_blocks_path = str(workspace.path_for(ArtifactKind.STATE_BLOCKS, parameter_id).relative_to(workspace.root))
    norm_paths = [rel_norm_path, rel_blocks_path]

    # Run Document Understanding / Header Semantics
    try:
        from table_scraper.entity_recognition import EntityRecognizer
        from table_scraper.understanding.header_analyzer import HeaderAnalyzer
        from table_scraper.understanding.metadata_annotator import MetadataAnnotator
        from table_scraper.storage.artifact_store import ArtifactCodec

        recognizer = EntityRecognizer()
        header_analyzer = HeaderAnalyzer(recognizer)
        depth = header_analyzer.detect_header_depth(normalized)
        header_tree = header_analyzer.build_header_tree(normalized, depth)
        columns = header_analyzer.resolve_column_semantics(header_tree, parameter_id)

        metadata_annotator = MetadataAnnotator(recognizer)
        annotated_table = metadata_annotator.annotate_table(normalized, columns, depth)

        # Set active annotated table for context-aware parse_float
        from table_scraper.parsing import base
        base._active_annotated_table = annotated_table

        # Persist new artifacts to workspaces/{workspace_id}/parsing/{parameter_id}/
        parsing_dir = workspace.root / "parsing" / parameter_id
        parsing_dir.mkdir(parents=True, exist_ok=True)

        header_tree_path = parsing_dir / "header_tree.json"
        header_tree_payload = ArtifactCodec.encode_value(header_tree)
        ArtifactCodec.write_json_atomic(header_tree_path, header_tree_payload)

        column_descriptors_path = parsing_dir / "column_descriptors.json"
        column_descriptors_payload = ArtifactCodec.encode_value(columns)
        ArtifactCodec.write_json_atomic(column_descriptors_path, column_descriptors_payload)

        annotated_table_path = parsing_dir / "annotated_table.json"
        annotated_table_payload = ArtifactCodec.encode_value(annotated_table)
        ArtifactCodec.write_json_atomic(annotated_table_path, annotated_table_payload)

        # Add to norm_paths for manifest tracking
        norm_paths.extend([
            f"parsing/{parameter_id}/header_tree.json",
            f"parsing/{parameter_id}/column_descriptors.json",
            f"parsing/{parameter_id}/annotated_table.json"
        ])
    except Exception as e:
        print(f"Error in Document Understanding run in stage_parse: {e}")

    with workspace._lock:
        parameter_status = dict(workspace.manifest.parameter_status)
        entry = dict(parameter_status.get(parameter_id, {}))
        entry[SessionStage.NORMALIZE.value] = {
            "status": StageStatus.COMPLETE.value,
            "artifact_paths": norm_paths,
            "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }
        workspace.manifest = replace(
            workspace.manifest,
            parameter_status=parameter_status,
            updated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        )
        workspace._persist_manifest()

    workspace.mark_stage_complete(
        stage=SessionStage.NORMALIZE,
        input_hash=manifest.pdf.content_hash,
        artifact_paths=norm_paths,
    )

    # 4. Classify table pattern
    from table_scraper.patterns.classifier import classify_table
    classification = classify_table(normalized, session.settings)
    store.write(ArtifactKind.PATTERN, classification, parameter_id)

    # Update manifest for CLASSIFY parameter stage
    rel_pattern_path = str(workspace.path_for(ArtifactKind.PATTERN, parameter_id).relative_to(workspace.root))
    classify_paths = [rel_pattern_path]

    with workspace._lock:
        parameter_status = dict(workspace.manifest.parameter_status)
        entry = dict(parameter_status.get(parameter_id, {}))
        entry[SessionStage.CLASSIFY.value] = {
            "status": StageStatus.COMPLETE.value,
            "artifact_paths": classify_paths,
            "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }
        workspace.manifest = replace(
            workspace.manifest,
            parameter_status=parameter_status,
            updated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        )
        workspace._persist_manifest()

    workspace.mark_stage_complete(
        stage=SessionStage.CLASSIFY,
        input_hash=manifest.pdf.content_hash,
        artifact_paths=classify_paths,
    )

    # 5. Route and parse
    from table_scraper.parsing.router import route_and_parse
    from table_scraper.parsing.registry import ParserRegistry

    # Ensure registry is initialized
    if session.registry is None:
        session.registry = ParserRegistry()

    # Inject workspace into session settings if needed
    if session.settings is not None:
        if isinstance(session.settings, dict):
            session.settings["workspace"] = workspace
        elif hasattr(session.settings, "workspace"):
            session.settings.workspace = workspace

    result = route_and_parse(normalized, classification, blocks, session.settings, session.registry)
    store.write(ArtifactKind.RECORDS, result, parameter_id)

    # Update manifest for PARSE parameter stage
    rel_records_path = str(workspace.path_for(ArtifactKind.RECORDS, parameter_id).relative_to(workspace.root))
    parse_paths = [rel_records_path]

    with workspace._lock:
        parameter_status = dict(workspace.manifest.parameter_status)
        entry = dict(parameter_status.get(parameter_id, {}))
        entry[SessionStage.PARSE.value] = {
            "status": StageStatus.COMPLETE.value,
            "artifact_paths": parse_paths,
            "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }
        workspace.manifest = replace(
            workspace.manifest,
            parameter_status=parameter_status,
            updated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        )
        workspace._persist_manifest()

    workspace.mark_stage_complete(
        stage=SessionStage.PARSE,
        input_hash=manifest.pdf.content_hash,
        artifact_paths=parse_paths,
    )


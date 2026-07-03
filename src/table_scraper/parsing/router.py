"""Route normalized tables to the correct parser via pattern and parameter config."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from table_scraper.domain.enums import ArtifactKind, SessionStage, StageStatus
from table_scraper.domain.models import NormalizedTable, ParseResult, PatternClassification, StateBlock
from table_scraper.parsing.registry import ParserRegistry


def route_and_parse(
    normalized: NormalizedTable,
    classification: PatternClassification,
    blocks: list[StateBlock] | None,
    parameter_config: Any,
    registry: ParserRegistry,
) -> ParseResult:
    """Select the appropriate parser plugin and execute parsing.

    Binds lineage tracking hash, stage statuses, and classification audit logs.

    Args:
        normalized: NormalizedTable containing structured cell data.
        classification: PatternClassification result from pattern recognizer.
        blocks: Optional state blocks list from segmentation step.
        parameter_config: Active profile config.
        registry: Initialized ParserRegistry.

    Returns:
        The consolidated ParseResult containing parsed records.
    """
    # 1. Select the parser plugin
    parser = None
    try:
        parser = registry.get_by_parameter(normalized.parameter_id, parameter_config)
    except Exception:
        pass

    if parser is None and classification.parser_id:
        try:
            parser = registry.get_by_id(classification.parser_id)
        except KeyError:
            pass

    if parser is None and classification.parser_family:
        try:
            parser = registry.get_by_family(classification.parser_family)
        except KeyError:
            pass

    if parser is None and classification.pattern:
        try:
            parser = registry.get_by_pattern(classification.pattern)
        except KeyError:
            pass

    if parser is None:
        raise ValueError(f"No parser could be resolved for parameter {normalized.parameter_id}")

    # 2. Execute parsing logic in the chosen parser plugin
    result = parser.parse(normalized, blocks, parameter_config)

    # 3. Enrich ParseResult with routing provenance and metadata
    state_blocks_used = [b.block_id for b in blocks] if blocks else []
    parser_family = getattr(parser, "parser_family", None)

    result = replace(
        result,
        parser_family=parser_family,
        classification=classification,
        input_table_hash=classification.input_table_hash,
        state_blocks_used=state_blocks_used,
    )

    # 4. Save result via ArtifactStore if workspace is available
    workspace = None
    if hasattr(parameter_config, "workspace") and parameter_config.workspace is not None:
        workspace = parameter_config.workspace
    elif isinstance(parameter_config, dict) and "workspace" in parameter_config:
        workspace = parameter_config["workspace"]

    if workspace is not None:
        try:
            from table_scraper.storage.artifact_store import ArtifactStore
            store = ArtifactStore(workspace)
            store.write(ArtifactKind.RECORDS, result)

            if hasattr(workspace, "manifest") and workspace.manifest is not None:
                workspace.manifest.stage_status[SessionStage.PARSE] = StageStatus.COMPLETE
                workspace.manifest.save()
        except Exception:
            pass

    return result


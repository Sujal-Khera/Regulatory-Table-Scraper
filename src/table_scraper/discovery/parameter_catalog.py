"""Merge TOC and page-index anchors into ParameterCatalog."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import timezone, datetime
import re
from typing import Any

from table_scraper.config.loader import load_parameter_config
from table_scraper.discovery.page_range_resolver import resolve_page_range
from table_scraper.domain.enums import DiscoverySource, PageRangeSource
from table_scraper.domain.models import (
    PageIndex,
    PageRange,
    ParameterCatalog,
    ParameterDefinition,
    TableTitle,
    TocEntry,
)


def _match_aliases(title_text: str, config: Any) -> str | None:
    """Find parameter ID matching any alias in the title text (case-insensitive)."""
    title_text_lower = title_text.lower()
    aliases: dict[str, tuple[str, ...]] = {}

    if hasattr(config, "discovery") and config.discovery is not None:
        discovery = config.discovery
        if hasattr(discovery, "parameter_aliases") and discovery.parameter_aliases is not None:
            aliases = getattr(discovery.parameter_aliases, "aliases", {})
    elif isinstance(config, dict):
        if "discovery" in config and isinstance(config["discovery"], dict):
            disc_dict = config["discovery"]
            if "parameter_aliases" in disc_dict and isinstance(disc_dict["parameter_aliases"], dict):
                aliases = disc_dict["parameter_aliases"].get("aliases", {})

    for param_id, alias_list in aliases.items():
        for alias in alias_list:
            if alias.lower() in title_text_lower:
                return param_id

    return None


def _find_phrase_in_index(page_index: PageIndex, phrase: str) -> int | None:
    """Find the first PDF page containing the case-insensitive phrase."""
    phrase_lower = phrase.lower()
    toc_pattern = re.compile(r"TABLE[- ]?\d+(?:\([A-Z]\))?\s*:\s*(.*?)\s+(\d+)", re.IGNORECASE)
    for record in page_index.pages:
        # Identify if this is a TOC page by counting TOC entries
        toc_matches = sum(1 for line in record.page_text.splitlines() if toc_pattern.search(line))
        if toc_matches > 2:
            continue
        if phrase_lower in record.page_text.lower():
            return record.pdf_page
    return None



def build_parameter_catalog(
    toc: list[TocEntry],
    page_index: PageIndex,
    config: Any,
) -> ParameterCatalog:
    """Build ParameterCatalog from TOC entries and page index anchors.

    Args:
        toc: List of parsed table of contents entries.
        page_index: Aggregate page index of the PDF.
        config: Application configuration bundle.

    Returns:
        The constructed and verified ParameterCatalog.
    """
    # 1. Resolve supported parameters from profile
    supported_params: set[str] = set()
    if hasattr(config, "profile") and config.profile is not None:
        if hasattr(config.profile, "supported_parameters"):
            supported_params = set(config.profile.supported_parameters)
    elif isinstance(config, dict):
        if "profile" in config and isinstance(config["profile"], dict):
            supported_params = set(config["profile"].get("supported_parameters", []))

    # 2. Match TOC entries to supported parameters
    toc_matches: dict[str, TocEntry] = {}
    for entry in toc:
        param_id = _match_aliases(entry.table_title.title_text, config)
        if param_id and param_id in supported_params:
            toc_matches[param_id] = entry

    # 3. Match PageIndex table titles to supported parameters
    index_matches: dict[str, tuple[int, TableTitle]] = {}
    for record in page_index.pages:
        for title in record.table_titles:
            param_id = _match_aliases(title.title_text, config)
            if param_id and param_id in supported_params:
                # If multiple titles match, keep the first one
                if param_id not in index_matches:
                    index_matches[param_id] = (record.pdf_page, title)

    # 4. Calibrate TOC printed page numbers to PDF pages via phrase search
    offsets: list[int] = []
    calibration_phrases: list[dict[str, Any]] = []

    for param_id, entry in toc_matches.items():
        try:
            param_cfg = load_parameter_config(param_id)
            phrase = param_cfg.calibration_phrase
            if phrase:
                pdf_page = _find_phrase_in_index(page_index, phrase)
                if pdf_page is not None:
                    delta = pdf_page - entry.printed_page
                    offsets.append(delta)
                    calibration_phrases.append(
                        {
                            "phrase": phrase,
                            "toc_page": entry.printed_page,
                            "pdf_page": pdf_page,
                            "delta": delta,
                        }
                    )
        except Exception:
            continue

    if offsets:
        toc_page_offset = Counter(offsets).most_common(1)[0][0]
        offset_calibration_method = "phrase_search"
    else:
        toc_page_offset = 0
        offset_calibration_method = "default"

    # 5. Merge sources and build ParameterDefinitions
    all_discovered_ids = set(toc_matches.keys()) | set(index_matches.keys())
    parameter_definitions: list[ParameterDefinition] = []

    for param_id in all_discovered_ids:
        # Load parameter config from YAML
        try:
            param_cfg = load_parameter_config(param_id)
        except Exception:
            # Fallback values if configuration file loading fails
            class DummyConfig:
                display_name = param_id.replace("_", " ").title()
                calibration_phrase = None
                parser_id = "default_parser"
                parser_family = None
                force_pattern = None

            param_cfg = DummyConfig()

        # Determine discovery source
        if param_id in toc_matches and param_id in index_matches:
            discovery_source = DiscoverySource.MERGED
        elif param_id in toc_matches:
            discovery_source = DiscoverySource.TOC
        else:
            discovery_source = DiscoverySource.INDEX

        # Determine page anchors
        toc_start_page = toc_matches[param_id].printed_page if param_id in toc_matches else None

        if param_id in index_matches:
            pdf_start_page = index_matches[param_id][0]
            table_title = index_matches[param_id][1]
        else:
            pdf_start_page = toc_start_page + toc_page_offset if toc_start_page is not None else None
            table_title = toc_matches[param_id].table_title

        # Create a dummy suggested range first to resolve circular dependency
        dummy_range = PageRange(
            start_page=pdf_start_page or 1,
            end_page=pdf_start_page or 1,
            source=PageRangeSource.TOC_NEXT_START,
        )

        param_def = ParameterDefinition(
            parameter_id=param_id,
            display_name=param_cfg.display_name,
            table_title=table_title,
            supported=True,
            suggested_range=dummy_range,
            toc_start_page=toc_start_page,
            pdf_start_page=pdf_start_page,
            parser_id=getattr(param_cfg, "parser_id", None),
            parser_family=getattr(param_cfg, "parser_family", None),
            pattern_override=getattr(param_cfg, "force_pattern", None),
            calibration_phrase=getattr(param_cfg, "calibration_phrase", None),
            discovery_source=discovery_source,
        )

        # Resolve PageRange suggesting bounds
        resolver_config = {
            "toc_page_offset": toc_page_offset,
            "toc": toc,
            "defaults": getattr(config, "defaults", None),
        }
        suggested_range = resolve_page_range(param_def, page_index, resolver_config)

        # Reconstruct ParameterDefinition with the actual PageRange
        param_def = replace(param_def, suggested_range=suggested_range)
        parameter_definitions.append(param_def)

    # Sort parameter definitions by suggested_range.start_page ascending
    parameter_definitions.sort(key=lambda p: p.suggested_range.start_page)

    return ParameterCatalog(
        schema_version="1.0.0",
        workspace_id=page_index.workspace_id,
        generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        parameters=parameter_definitions,
        parameter_count=len(parameter_definitions),
        supported_count=len([p for p in parameter_definitions if p.supported]),
        toc_page_offset=toc_page_offset,
        offset_calibration_method=offset_calibration_method,
        offset_calibration_phrases=calibration_phrases,
        discovery_sources=list({d.discovery_source.value for d in parameter_definitions if d.discovery_source}),
    )


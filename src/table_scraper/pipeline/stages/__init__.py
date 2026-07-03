"""Pipeline stage orchestration entrypoints."""

from table_scraper.pipeline.stages.discover_stage import stage_discover
from table_scraper.pipeline.stages.export_stage import stage_export
from table_scraper.pipeline.stages.extract_stage import stage_extract
from table_scraper.pipeline.stages.index_stage import stage_index
from table_scraper.pipeline.stages.parse_stage import stage_parse

__all__ = [
    "stage_discover",
    "stage_export",
    "stage_extract",
    "stage_index",
    "stage_parse",
]

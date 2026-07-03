"""Pipeline orchestration — wire stages without business logic."""

from table_scraper.pipeline.runner import run_pipeline
from table_scraper.pipeline.session import PipelineSession

__all__ = ["PipelineSession", "run_pipeline"]

"""TOC, parameter catalog, and page range discovery."""

from table_scraper.discovery.page_offset_calibrator import calibrate_page_offset, preview_pages
from table_scraper.discovery.page_range_resolver import resolve_page_range
from table_scraper.discovery.parameter_catalog import build_parameter_catalog
from table_scraper.discovery.toc_extractor import extract_toc

__all__ = [
    "build_parameter_catalog",
    "calibrate_page_offset",
    "extract_toc",
    "preview_pages",
    "resolve_page_range",
]

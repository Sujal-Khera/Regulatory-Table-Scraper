"""Structural and text normalization before semantic parsing."""

from table_scraper.normalization.block_segmentation import segment_state_blocks
from table_scraper.normalization.geometry import normalize_geometry
from table_scraper.normalization.hierarchy import propagate_hierarchy
from table_scraper.normalization.text_cleanup import clean_text, extract_english, normalize_text_cells

__all__ = [
    "clean_text",
    "extract_english",
    "normalize_geometry",
    "normalize_text_cells",
    "propagate_hierarchy",
    "segment_state_blocks",
]

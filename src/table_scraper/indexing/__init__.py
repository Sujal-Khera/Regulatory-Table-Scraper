"""Full-PDF page indexing."""

from table_scraper.indexing.page_indexer import build_page_index
from table_scraper.indexing.title_detector import detect_table_titles

__all__ = ["build_page_index", "detect_table_titles"]

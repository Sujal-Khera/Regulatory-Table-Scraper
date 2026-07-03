"""FTS5 page search index backed by SQLite."""

from __future__ import annotations

from table_scraper.domain.models import PageIndex


class PageSearchIndex:
    """
    Full-text search over page text and table titles.

    TODO: Build FTS5 virtual table from PageIndex.
    TODO: Implement query(text, limit) returning PDF page numbers.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def build(self, page_index: PageIndex) -> None:
        """Build or rebuild the search index from a PageIndex."""
        raise NotImplementedError

    def query(self, text: str, limit: int = 20) -> list[int]:
        """Return matching 1-based PDF page numbers."""
        raise NotImplementedError

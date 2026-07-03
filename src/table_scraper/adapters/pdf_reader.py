"""Thin wrapper around pdfplumber for PDF text and table extraction."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import pdfplumber

from table_scraper.domain.errors import ExtractionError, WorkspaceError
from table_scraper.domain.protocols import PdfReader


class PdfPlumberReader:
    """PdfReader adapter implementation using pdfplumber.

    Provides a clean, resource-safe context manager wrapper for extraction
    of text and tables from a PDF document.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._pdf: pdfplumber.PDF | None = None
        self._page_count = 0

    @classmethod
    def open(cls, path: Path | str) -> PdfPlumberReader:
        """Open a PDF for reading.

        Args:
            path: Path to the PDF file.

        Returns:
            An open PdfPlumberReader instance.
        """
        instance = cls(path)
        instance._open_pdf()
        return instance

    def _open_pdf(self) -> None:
        """Helper to open pdfplumber resources and check page count."""
        try:
            self._pdf = pdfplumber.open(self._path)
            self._page_count = len(self._pdf.pages)
            if self._page_count < 1:
                raise WorkspaceError(f"PDF document at {self._path} has no pages.")
        except Exception as exc:
            if isinstance(exc, WorkspaceError):
                raise
            raise WorkspaceError(f"Failed to open PDF document {self._path}: {exc}") from exc

    @property
    def page_count(self) -> int:
        """Return total number of pages in the PDF."""
        if self._pdf is None:
            self._open_pdf()
        return self._page_count

    def extract_text(self, page: int) -> str:
        """Extract plain text from a 1-based PDF page index.

        Args:
            page: 1-based page number in `[1, page_count]`.

        Returns:
            Extracted page text, or `""` if empty.
        """
        if self._pdf is None:
            self._open_pdf()
        if page < 1 or page > self._page_count:
            raise IndexError(f"Page index {page} out of range [1, {self._page_count}]")
        try:
            pdf_page = self._pdf.pages[page - 1]
            text = pdf_page.extract_text()
            return text or ""
        except Exception as exc:
            raise ExtractionError(f"Failed to extract text from page {page}: {exc}") from exc

    def extract_tables(self, page: int) -> list[list[list[str]]]:
        """Extract all tables from a page as list of row grids.

        Args:
            page: 1-based page number in `[1, page_count]`.

        Returns:
            List of tables; each table is a grid of string cells.
        """
        if self._pdf is None:
            self._open_pdf()
        if page < 1 or page > self._page_count:
            raise IndexError(f"Page index {page} out of range [1, {self._page_count}]")
        try:
            pdf_page = self._pdf.pages[page - 1]
            tables = pdf_page.extract_tables()
            if not tables:
                return []

            normalized_tables: list[list[list[str]]] = []
            for table in tables:
                normalized_rows: list[list[str]] = []
                for row in table:
                    # Convert all cell values to strings, treating None as empty string
                    normalized_row = [str(cell) if cell is not None else "" for cell in row]
                    normalized_rows.append(normalized_row)
                normalized_tables.append(normalized_rows)
            return normalized_tables
        except Exception as exc:
            raise ExtractionError(f"Failed to extract tables from page {page}: {exc}") from exc

    def __enter__(self) -> PdfPlumberReader:
        """Open the PDF resource and return self."""
        if self._pdf is None:
            self._open_pdf()
        return self

    def __exit__(self, *args: Any) -> None:
        """Close the PDF resource and release handles."""
        if self._pdf is not None:
            try:
                self._pdf.close()
            except Exception:
                pass
            finally:
                self._pdf = None


"""External library wrappers — isolate pdfplumber and openpyxl."""

from table_scraper.adapters.excel_writer import OpenpyxlExcelWriter
from table_scraper.adapters.pdf_reader import PdfPlumberReader

__all__ = ["OpenpyxlExcelWriter", "PdfPlumberReader"]

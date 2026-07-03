import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
from table_scraper.adapters.pdf_reader import PdfPlumberReader
from table_scraper.domain.errors import ExtractionError, WorkspaceError

class TestPdfReader(unittest.TestCase):
    def setUp(self):
        self.pdf_path = "test_doc.pdf"

    @patch("table_scraper.adapters.pdf_reader.pdfplumber.open")
    def test_open_success(self, mock_open):
        mock_pdf = MagicMock()
        mock_pdf.pages = [MagicMock(), MagicMock()]
        mock_open.return_value = mock_pdf

        reader = PdfPlumberReader.open(self.pdf_path)
        self.assertEqual(reader.page_count, 2)
        mock_open.assert_called_once_with(Path(self.pdf_path))

    @patch("table_scraper.adapters.pdf_reader.pdfplumber.open")
    def test_open_failure_raises_workspace_error(self, mock_open):
        mock_open.side_effect = RuntimeError("Disk error")

        with self.assertRaises(WorkspaceError):
            PdfPlumberReader.open(self.pdf_path)

    @patch("table_scraper.adapters.pdf_reader.pdfplumber.open")
    def test_extract_text(self, mock_open):
        mock_pdf = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Page 1 Text"
        mock_pdf.pages = [mock_page]
        mock_open.return_value = mock_pdf

        with PdfPlumberReader(self.pdf_path) as reader:
            text = reader.extract_text(1)
            self.assertEqual(text, "Page 1 Text")
            mock_page.extract_text.assert_called_once()

    @patch("table_scraper.adapters.pdf_reader.pdfplumber.open")
    def test_extract_tables_with_none_normalization(self, mock_open):
        mock_pdf = MagicMock()
        mock_page = MagicMock()
        # Mock pdfplumber returning cells containing None
        mock_page.extract_tables.return_value = [
            [["Col1", "Col2"], ["Val1", None]]
        ]
        mock_pdf.pages = [mock_page]
        mock_open.return_value = mock_pdf

        with PdfPlumberReader(self.pdf_path) as reader:
            tables = reader.extract_tables(1)
            self.assertEqual(len(tables), 1)
            # Checked cell None is normalized to empty string
            self.assertEqual(tables[0], [["Col1", "Col2"], ["Val1", ""]])
            mock_page.extract_tables.assert_called_once()

    @patch("table_scraper.adapters.pdf_reader.pdfplumber.open")
    def test_extract_text_out_of_bounds_raises_index_error(self, mock_open):
        mock_pdf = MagicMock()
        mock_pdf.pages = [MagicMock()]
        mock_open.return_value = mock_pdf

        with PdfPlumberReader(self.pdf_path) as reader:
            with self.assertRaises(IndexError):
                reader.extract_text(2)

    @patch("table_scraper.adapters.pdf_reader.pdfplumber.open")
    def test_extract_text_error_raises_extraction_error(self, mock_open):
        mock_pdf = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.side_effect = Exception("Parsing crash")
        mock_pdf.pages = [mock_page]
        mock_open.return_value = mock_pdf

        with PdfPlumberReader(self.pdf_path) as reader:
            with self.assertRaises(ExtractionError):
                reader.extract_text(1)

if __name__ == "__main__":
    unittest.main()

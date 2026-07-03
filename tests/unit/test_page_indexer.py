import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
from table_scraper.indexing.page_indexer import build_page_index
from table_scraper.domain.models import PageIndexResult
from table_scraper.domain.enums import ArtifactKind

class TestPageIndexer(unittest.TestCase):
    def setUp(self):
        # Setup mock dependencies
        self.mock_pdf = MagicMock()
        self.mock_pdf.page_count = 2
        self.mock_pdf.extract_text.side_effect = [
            "TABLE-1: Test Table Title",
            "No titles here"
        ]
        self.mock_pdf.extract_tables.side_effect = [
            [[["Col1", "Col2"], ["Val1", "Val2"]]],
            []
        ]

        self.mock_workspace = MagicMock()
        self.mock_workspace.workspace_id = "test_workspace_id"
        self.mock_workspace.manifest.pdf.content_hash = "a" * 64
        self.mock_workspace.path_for.return_value = Path("test_page_index.db")

        self.config = {
            "discovery": {
                "toc_patterns": {
                    "table_title_pattern": r"TABLE[- ]?\d+(?:\([A-Z]\))?\s*:\s*([^\n]+)"
                }
            }
        }

    @patch("table_scraper.indexing.page_indexer.ArtifactStore")
    def test_build_page_index(self, mock_store_class):
        mock_store = MagicMock()
        mock_store_class.return_value = mock_store
        # Mocking read to return None (no previous index)
        mock_store.read.return_value = None

        result = build_page_index(self.mock_pdf, self.mock_workspace, self.config)

        self.assertIsInstance(result, PageIndexResult)
        self.assertEqual(result.pages_indexed, 2)
        self.assertEqual(result.pages_with_titles, 1)

        # Verify artifacts were written
        mock_store.write.assert_any_call(ArtifactKind.PAGE_INDEX, result.page_index)
        mock_store.write.assert_any_call(ArtifactKind.PAGE_INDEX_CSV, unittest.mock.ANY)

        # Verify page index contents
        page_index = result.page_index
        self.assertEqual(page_index.page_count, 2)
        self.assertEqual(page_index.pages_with_titles, 1)
        self.assertEqual(page_index.pages_with_tables, 1)
        self.assertEqual(page_index.title_anchor_pages, [1])

        # Verify page 1 record details
        page1 = page_index.pages[0]
        self.assertEqual(page1.pdf_page, 1)
        self.assertEqual(page1.text_length, len("TABLE-1: Test Table Title"))
        self.assertTrue(page1.contains_table)
        self.assertEqual(len(page1.table_titles), 1)
        self.assertEqual(page1.table_titles[0].table_number, "1")

        # Verify page 2 record details
        page2 = page_index.pages[1]
        self.assertEqual(page2.pdf_page, 2)
        self.assertFalse(page2.contains_table)
        self.assertEqual(len(page2.table_titles), 0)

if __name__ == "__main__":
    unittest.main()

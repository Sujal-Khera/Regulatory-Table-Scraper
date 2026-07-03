import unittest
from unittest.mock import MagicMock, patch
from table_scraper.domain.enums import TitleSource, PageRangeSource, DiscoverySource
from table_scraper.domain.models import TableTitle, TocEntry, PageIndex, PageRecord, ParameterDefinition, PageRange
from table_scraper.discovery.toc_extractor import extract_toc
from table_scraper.discovery.page_offset_calibrator import calibrate_page_offset, preview_pages
from table_scraper.discovery.page_range_resolver import resolve_page_range
from table_scraper.discovery.parameter_catalog import build_parameter_catalog

class TestDiscoveryEngine(unittest.TestCase):
    def setUp(self):
        self.config = {
            "defaults": {
                "toc_max_pages": 5,
                "page_range_strategy": "anchor_chain"
            },
            "discovery": {
                "toc_patterns": {
                    "table_title_pattern": r"TABLE[- ]?\d+(?:\([A-Z]\))?\s*:\s*([^\n]+)",
                    "toc_entry_pattern": r"TABLE[- ]?\d+(?:\([A-Z]\))?\s*:\s*(.*?)\s+(\d+)"
                },
                "parameter_aliases": {
                    "aliases": {
                        "banking_charges": ["Banking Charges", "banking fees"],
                        "transmission_charges": ["Transmission Charges", "grid cost"]
                    }
                }
            },
            "profile": {
                "supported_parameters": ["banking_charges", "transmission_charges"]
            }
        }

    def test_extract_toc(self):
        mock_pdf = MagicMock()
        mock_pdf.page_count = 2
        mock_pdf.extract_text.side_effect = [
            "TABLE-1: Banking Charges Policy  10\nTABLE-2: Transmission Charges  15",
            "Not a TOC page"
        ]

        toc_entries = extract_toc(mock_pdf, self.config)
        self.assertEqual(len(toc_entries), 2)
        self.assertEqual(toc_entries[0].printed_page, 10)
        self.assertEqual(toc_entries[0].table_title.table_number, "1")
        self.assertEqual(toc_entries[0].table_title.title_text, "Banking Charges Policy")
        self.assertEqual(toc_entries[0].table_title.source, TitleSource.TOC)

    def test_calibrate_page_offset(self):
        mock_pdf = MagicMock()
        mock_pdf.page_count = 5
        mock_pdf.extract_text.side_effect = [
            "TOC",
            "TOC cont",
            "Page 3 random content",
            "Here is the Banking Charges Policy on page 4",
            "Other content"
        ]

        # Banking Charges is on printed page 2, but actual PDF page is 4. Offset = 4 - 2 = 2.
        offset = calibrate_page_offset(2, mock_pdf, "Banking Charges")
        self.assertEqual(offset, 2)

    def test_preview_pages(self):
        mock_pdf = MagicMock()
        mock_pdf.page_count = 3
        mock_pdf.extract_text.side_effect = [
            "Line 1\nLine 2\nLine 3",
            "Page 2 Line 1",
            "Page 3 Line 1"
        ]

        class MockPageRange:
            start_page = 1
            end_page = 2

        previews = preview_pages(mock_pdf, MockPageRange(), lines=2)
        self.assertEqual(len(previews), 2)
        self.assertEqual(previews[1], "Line 1\nLine 2")
        self.assertEqual(previews[2], "Page 2 Line 1")

    def test_resolve_page_range_anchor_chain(self):
        # Setup contiguous page records to satisfy PageIndex validation
        pages = []
        for p in range(1, 11):
            titles = []
            if p == 1:
                titles.append(TableTitle(raw_text="TABLE-1: Title", table_number="1", title_text="Title", source=TitleSource.PAGE_SCAN, confidence=1.0))
            elif p == 5:
                titles.append(TableTitle(raw_text="TABLE-2: Other", table_number="2", title_text="Other", source=TitleSource.PAGE_SCAN, confidence=1.0))
            pages.append(
                PageRecord(
                    pdf_page=p,
                    page_text="",
                    table_titles=titles,
                    contains_table=(p in (1, 5)),
                    text_length=0
                )
            )

        page_index = PageIndex(
            schema_version="1.0.0",
            workspace_id="test_ws",
            pdf_hash="a" * 64,
            page_count=10,
            pages=pages,
            indexed_at="",
            index_version=1
        )

        param = ParameterDefinition(
            parameter_id="banking_charges",
            display_name="Banking Charges",
            table_title=TableTitle(raw_text="TABLE-1: Title", table_number="1", title_text="Title", source=TitleSource.PAGE_SCAN, confidence=1.0),
            supported=True,
            suggested_range=PageRange(start_page=1, end_page=1, source=PageRangeSource.ANCHOR_CHAIN),
            parser_id="test_parser"
        )

        # anchor_chain strategy should bound it to next title page - 1 (5 - 1 = 4)
        pr = resolve_page_range(param, page_index, self.config)
        self.assertEqual(pr.start_page, 1)
        self.assertEqual(pr.end_page, 4)
        self.assertEqual(pr.source, PageRangeSource.ANCHOR_CHAIN)

    @patch("table_scraper.discovery.parameter_catalog.load_parameter_config")
    def test_build_parameter_catalog(self, mock_load_config):
        # Setup mock parameter config
        mock_cfg = MagicMock()
        mock_cfg.display_name = "Banking Charges"
        mock_cfg.calibration_phrase = "Banking Charges"
        mock_cfg.parser_id = "banking_parser"
        mock_cfg.parser_family = None
        mock_cfg.force_pattern = None
        mock_load_config.return_value = mock_cfg

        toc = [
            TocEntry(
                table_title=TableTitle(raw_text="TABLE-1: Banking Charges Policy  10", table_number="1", title_text="Banking Charges Policy", printed_page=10, source=TitleSource.TOC, confidence=1.0),
                printed_page=10,
                raw_line="TABLE-1: Banking Charges Policy  10"
            )
        ]

        pages = []
        for p in range(1, 21):
            text = "Here is the Banking Charges Policy" if p == 12 else f"Page {p} content"
            pages.append(
                PageRecord(
                    pdf_page=p,
                    page_text=text,
                    table_titles=[],
                    contains_table=False,
                    text_length=len(text)
                )
            )

        page_index = PageIndex(
            schema_version="1.0.0",
            workspace_id="test_ws",
            pdf_hash="a" * 64,
            page_count=20,
            pages=pages,
            indexed_at="",
            index_version=1
        )

        catalog = build_parameter_catalog(toc, page_index, self.config)
        self.assertEqual(catalog.parameter_count, 1)
        self.assertEqual(catalog.toc_page_offset, 2)
        self.assertEqual(catalog.offset_calibration_method, "phrase_search")
        
        param = catalog.parameters[0]
        self.assertEqual(param.parameter_id, "banking_charges")
        self.assertEqual(param.pdf_start_page, 12)
        self.assertEqual(param.suggested_range.start_page, 12)
        self.assertEqual(param.suggested_range.end_page, 20)  # Extended to end of document

if __name__ == "__main__":
    unittest.main()

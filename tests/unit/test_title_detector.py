import unittest
from table_scraper.indexing.title_detector import detect_table_titles, _resolve_pattern
from table_scraper.domain.enums import TitleSource

class TestTitleDetector(unittest.TestCase):
    def setUp(self):
        self.config_dict = {
            "discovery": {
                "toc_patterns": {
                    "table_title_pattern": r"TABLE[- ]?\d+(?:\([A-Z]\))?\s*:\s*([^\n]+)"
                }
            }
        }

    def test_resolve_pattern_various_formats(self):
        # Dictionary config format
        pattern = _resolve_pattern(self.config_dict)
        self.assertEqual(pattern, r"TABLE[- ]?\d+(?:\([A-Z]\))?\s*:\s*([^\n]+)")

        # Direct string format fallback/etc
        class MockConfig:
            def __init__(self):
                self.table_title_pattern = "MOCK_PATTERN"
        self.assertEqual(_resolve_pattern(MockConfig()), "MOCK_PATTERN")

    def test_detect_standard_title(self):
        text = "TABLE-1: Banking Charges Policy\nThis page outlines the banking charges rules."
        titles = detect_table_titles(text, self.config_dict)
        self.assertEqual(len(titles), 1)
        self.assertEqual(titles[0].table_number, "1")
        self.assertEqual(titles[0].title_text, "Banking Charges Policy")
        self.assertEqual(titles[0].source, TitleSource.PAGE_SCAN)

    def test_detect_title_case_normalization(self):
        text = "TABLE 5(A): Cross Subsidy Surcharge"
        titles = detect_table_titles(text, self.config_dict)
        self.assertEqual(len(titles), 1)
        # Normalized table number to lowercase
        self.assertEqual(titles[0].table_number, "5(a)")
        self.assertEqual(titles[0].title_text, "Cross Subsidy Surcharge")
        # Substring validation requirements: raw_text must contain normalized table_number and title_text
        self.assertIn("5(a)", titles[0].raw_text)
        self.assertIn("Cross Subsidy Surcharge", titles[0].raw_text)

    def test_detect_multiple_titles(self):
        text = "TABLE-1: Banking Charges Policy\nTABLE-2: Transmission Charges"
        titles = detect_table_titles(text, self.config_dict)
        self.assertEqual(len(titles), 2)
        self.assertEqual(titles[0].table_number, "1")
        self.assertEqual(titles[1].table_number, "2")

    def test_no_titles(self):
        text = "This is a random page without any tables."
        titles = detect_table_titles(text, self.config_dict)
        self.assertEqual(len(titles), 0)

if __name__ == "__main__":
    unittest.main()

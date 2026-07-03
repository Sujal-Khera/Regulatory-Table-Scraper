"""Parser family plugin implementations."""

from table_scraper.parsing.families.key_value import KeyValueParser
from table_scraper.parsing.families.narrative import NarrativeParser
from table_scraper.parsing.families.numeric_matrix import NumericMatrixParser
from table_scraper.parsing.families.simple_matrix import SimpleMatrixParser
from table_scraper.parsing.families.state_block_matrix import StateBlockMatrixParser
from table_scraper.parsing.families.wide_to_long import WideToLongParser

__all__ = [
    "KeyValueParser",
    "NarrativeParser",
    "NumericMatrixParser",
    "SimpleMatrixParser",
    "StateBlockMatrixParser",
    "WideToLongParser",
]

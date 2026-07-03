"""Semantic parser plugins and routing."""

from table_scraper.parsing.base import BaseParser
from table_scraper.parsing.registry import ParserRegistry
from table_scraper.parsing.router import route_and_parse

__all__ = ["BaseParser", "ParserRegistry", "route_and_parse"]

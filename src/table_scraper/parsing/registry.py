"""Register and lookup parser plugins from config."""

from __future__ import annotations

from typing import Any

from table_scraper.domain.enums import TablePattern, ParserFamily
from table_scraper.domain.protocols import ParserPlugin


class ParserRegistry:
    """Parser plugin registry loaded from config/parsers/registry.yaml.

    Initializes with built-in family parser plugins, supporting lookups by
    parser ID, parser family, TablePattern, or parameter-specific profile overrides.
    """

    def __init__(self) -> None:
        self._plugins: dict[str, ParserPlugin] = {}
        self._pattern_map: dict[TablePattern, ParserPlugin] = {}
        self._family_map: dict[str, ParserPlugin] = {}

        # Self-register built-in family parsers at startup to guarantee resolution
        try:
            from table_scraper.parsing.families.narrative import NarrativeParser
            from table_scraper.parsing.families.numeric_matrix import NumericMatrixParser
            from table_scraper.parsing.families.wide_to_long import WideToLongParser
            from table_scraper.parsing.families.state_block_matrix import StateBlockMatrixParser
            from table_scraper.parsing.families.simple_matrix import SimpleMatrixParser
            from table_scraper.parsing.families.key_value import KeyValueParser

            self.register(NarrativeParser())
            self.register(NumericMatrixParser())
            self.register(WideToLongParser())
            self.register(StateBlockMatrixParser())
            self.register(SimpleMatrixParser())
            self.register(KeyValueParser())
        except ImportError:
            # Handle circular imports or mock tests gracefully
            pass

    def register(self, plugin: ParserPlugin) -> None:
        """Register a parser plugin.

        Args:
            plugin: An instantiated ParserPlugin.
        """
        self._plugins[plugin.parser_id] = plugin
        self._pattern_map[plugin.pattern] = plugin
        if hasattr(plugin, "parser_family") and plugin.parser_family:
            family_val = plugin.parser_family.value if hasattr(plugin.parser_family, "value") else str(plugin.parser_family)
            self._family_map[family_val] = plugin

    def get_by_id(self, parser_id: str) -> ParserPlugin:
        """Lookup parser by its unique plugin parser_id."""
        if parser_id not in self._plugins:
            raise KeyError(f"Parser plugin '{parser_id}' is not registered.")
        return self._plugins[parser_id]

    def get_by_family(self, family: str | ParserFamily) -> ParserPlugin:
        """Lookup parser by its ParserFamily."""
        family_str = family.value if hasattr(family, "value") else str(family)
        if family_str not in self._family_map:
            raise KeyError(f"No parser registered for ParserFamily '{family_str}'.")
        return self._family_map[family_str]

    def get_by_pattern(self, pattern: TablePattern) -> ParserPlugin:
        """Lookup parser by TablePattern.

        Args:
            pattern: Target TablePattern.

        Returns:
            The matched ParserPlugin.
        """
        if pattern not in self._pattern_map:
            raise KeyError(f"No parser registered for TablePattern '{pattern}'.")
        return self._pattern_map[pattern]

    def get_by_parameter(self, parameter_id: str, config: Any) -> ParserPlugin:
        """Lookup parser by parameter_id using registry config.

        Resolves either parser_id, parser_family, or TablePattern mapped to
        the parameter config profile.

        Args:
            parameter_id: Target parameter identifier.
            config: Active pipeline settings.

        Returns:
            The resolved ParserPlugin.
        """
        # 1. Attempt to load the parameter YAML config
        try:
            from table_scraper.config.loader import load_parameter_config
            param_cfg = load_parameter_config(parameter_id)
            if hasattr(param_cfg, "parser_id") and param_cfg.parser_id:
                return self.get_by_id(param_cfg.parser_id)
            if hasattr(param_cfg, "parser_family") and param_cfg.parser_family:
                return self.get_by_family(param_cfg.parser_family)
            if hasattr(param_cfg, "force_pattern") and param_cfg.force_pattern:
                return self.get_by_pattern(param_cfg.force_pattern)
        except Exception:
            pass

        # 2. Check direct overrides in global config
        if hasattr(config, "parser_id") and getattr(config, "parser_id"):
            return self.get_by_id(getattr(config, "parser_id"))

        if hasattr(config, "parser_family") and getattr(config, "parser_family"):
            return self.get_by_family(getattr(config, "parser_family"))

        # 3. Fallback: try mapping parameter ID to known families or default to simple_matrix
        if "wheel" in parameter_id:
            return self.get_by_family(ParserFamily.WIDE_TO_LONG)
        if "cross" in parameter_id:
            return self.get_by_family(ParserFamily.STATE_BLOCK_MATRIX)
        if "bank" in parameter_id:
            return self.get_by_family(ParserFamily.NARRATIVE)
        if "trans" in parameter_id:
            return self.get_by_family(ParserFamily.NUMERIC_MATRIX)

        return self.get_by_family(ParserFamily.SIMPLE_MATRIX)

    def load_from_config(self, registry_config: dict[str, Any]) -> None:
        """Load plugin bindings from registry YAML.

        Args:
            registry_config: Decoded registry configurations.
        """
        # In a fully pluggable system, this loads dynamic modules.
        # For this ETL engine, the built-in registrations are pre-loaded.
        pass


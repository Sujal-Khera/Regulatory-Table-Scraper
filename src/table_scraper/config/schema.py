"""Validate configuration shape and produce immutable typed settings objects.

Every YAML file under ``config/`` is parsed through functions in this module.
Validation is strict: missing keys, unknown enum values, duplicate identifiers,
and broken cross-references raise :class:`~table_scraper.domain.errors.ConfigError`
with the originating file path and field name in the message.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any

from table_scraper.domain.enums import ParserFamily, TablePattern
from table_scraper.domain.errors import ConfigError

_PARAMETER_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_ALLOWED_PAGE_RANGE_STRATEGIES = frozenset({"anchor_chain", "toc_next_start"})
_ALLOWED_TABLE_SELECTORS = frozenset({"largest_area", "first_table", "by_index"})


def _config_error(message: str, *, source: str, field: str | None = None) -> ConfigError:
    """Format a configuration error with file and optional field context."""
    if field:
        return ConfigError(f"{source}: [{field}] {message}")
    return ConfigError(f"{source}: {message}")


def _require_mapping(data: Any, *, source: str) -> dict[str, Any]:
    """Ensure ``data`` is a YAML mapping."""
    if not isinstance(data, dict):
        raise _config_error("expected a mapping at the document root", source=source)
    return data


def _require_key(
    data: Mapping[str, Any],
    key: str,
    *,
    source: str,
    expected_type: type | tuple[type, ...] | None = None,
) -> Any:
    """Return a required key or raise :class:`ConfigError`."""
    if key not in data:
        raise _config_error(f"missing required key {key!r}", source=source, field=key)
    value = data[key]
    if expected_type is not None and not isinstance(value, expected_type):
        type_name = (
            expected_type.__name__
            if isinstance(expected_type, type)
            else " or ".join(t.__name__ for t in expected_type)
        )
        raise _config_error(
            f"expected {type_name}, got {type(value).__name__}",
            source=source,
            field=key,
        )
    return value


def _optional_key(
    data: Mapping[str, Any],
    key: str,
    default: Any,
    *,
    expected_type: type | tuple[type, ...] | None = None,
) -> Any:
    """Return an optional key with a default when absent."""
    if key not in data:
        return default
    value = data[key]
    if expected_type is not None and not isinstance(value, expected_type):
        type_name = (
            expected_type.__name__
            if isinstance(expected_type, type)
            else " or ".join(t.__name__ for t in expected_type)
        )
        raise ValueError(f"{key!r}: expected {type_name}, got {type(value).__name__}")
    return value


def _parse_enum(
    value: Any,
    enum_cls: type[Enum],
    *,
    source: str,
    field: str,
) -> Enum:
    """Parse a string value into a domain enum member."""
    if not isinstance(value, str):
        raise _config_error(
            f"expected string enum value, got {type(value).__name__}",
            source=source,
            field=field,
        )
    try:
        return enum_cls(value)
    except ValueError as exc:
        allowed = ", ".join(member.value for member in enum_cls)
        raise _config_error(
            f"invalid value {value!r}; allowed: {allowed}",
            source=source,
            field=field,
        ) from exc


def _ensure_no_duplicates(
    values: list[str],
    *,
    source: str,
    label: str,
) -> None:
    """Raise when ``values`` contains duplicates."""
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    if duplicates:
        ordered = ", ".join(sorted(duplicates))
        raise _config_error(f"duplicate {label}: {ordered}", source=source)


def _validate_parameter_id(parameter_id: str, *, source: str, field: str = "parameter_id") -> str:
    """Validate snake_case parameter identifiers."""
    if not _PARAMETER_ID_PATTERN.match(parameter_id):
        raise _config_error(
            "must match ^[a-z][a-z0-9_]*$",
            source=source,
            field=field,
        )
    return parameter_id


@dataclass(frozen=True, slots=True)
class ExportConfig:
    """Excel export formatting defaults."""

    max_column_width: int
    freeze_panes: bool
    bold_headers: bool


@dataclass(frozen=True, slots=True)
class WorkspaceConfig:
    """Workspace directory layout defaults."""

    root: str


@dataclass(frozen=True, slots=True)
class DefaultsConfig:
    """Global pipeline defaults from ``config/defaults.yaml``."""

    schema_version: str
    toc_max_pages: int
    page_range_strategy: str
    table_selector: str
    pattern_confidence_threshold: float
    export: ExportConfig
    workspace: WorkspaceConfig
    debug: bool


@dataclass(frozen=True, slots=True)
class ProfileConfig:
    """PDF edition profile from ``config/pdf_profiles/*.yaml``."""

    profile_id: str
    display_name: str
    supported_parameters: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TocPatternsConfig:
    """TOC and table-title regex patterns."""

    table_title_pattern: str
    toc_entry_pattern: str


@dataclass(frozen=True, slots=True)
class ParameterAliasesConfig:
    """Natural-language search synonyms keyed by parameter ID."""

    aliases: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class DiscoveryConfig:
    """Merged discovery configuration (TOC patterns + parameter aliases)."""

    toc_patterns: TocPatternsConfig
    parameter_aliases: ParameterAliasesConfig


@dataclass(frozen=True, slots=True)
class PatternSignaturesConfig:
    """Pattern classifier feature weights keyed by pattern name."""

    signatures: Mapping[str, Mapping[str, float]]


@dataclass(frozen=True, slots=True)
class ParserRegistryEntry:
    """One registered parser plugin."""

    parser_id: str
    family: ParserFamily
    patterns: tuple[TablePattern, ...]


@dataclass(frozen=True, slots=True)
class ParameterRegistryBinding:
    """Registry binding from parameter ID to parser plugin."""

    parameter_id: str
    parser_id: str


@dataclass(frozen=True, slots=True)
class ParserRegistryConfig:
    """Parser registry and parameter routing from ``config/parsers/registry.yaml``."""

    parsers: Mapping[str, ParserRegistryEntry]
    parameters: Mapping[str, ParameterRegistryBinding]


@dataclass(frozen=True, slots=True)
class StatesCatalog:
    """Canonical Indian states and UTs."""

    states: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StateAliasesCatalog:
    """State name alias → canonical name mappings."""

    aliases: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class UtilitiesCatalog:
    """Utility/DISCOM lists keyed by state."""

    utilities: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class CatalogsConfig:
    """Reference catalogs for states, aliases, and utilities."""

    states: StatesCatalog
    state_aliases: StateAliasesCatalog
    utilities: UtilitiesCatalog


@dataclass(frozen=True, slots=True)
class OutputSchemaConfig:
    """Output column schema for a parameter."""

    columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ParameterValidationConfig:
    """Validation thresholds for a parameter."""

    min_records: int


@dataclass(frozen=True, slots=True)
class ParameterConfig:
    """Fully merged, immutable configuration for one regulatory parameter."""

    parameter_id: str
    display_name: str
    sheet_name: str
    parser_id: str
    parser_family: ParserFamily
    output_schema: OutputSchemaConfig
    validation: ParameterValidationConfig
    supported: bool = True
    calibration_phrase: str | None = None
    force_pattern: TablePattern | None = None
    extras: Mapping[str, Any] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Merged application settings for one PDF processing session."""

    pdf_path: str
    profile_id: str
    defaults: DefaultsConfig
    profile: ProfileConfig
    discovery: DiscoveryConfig
    patterns: PatternSignaturesConfig
    registry: ParserRegistryConfig
    catalogs: CatalogsConfig


def parse_defaults(data: Any, *, source: str = "defaults.yaml") -> DefaultsConfig:
    """Parse and validate ``config/defaults.yaml``."""
    root = _require_mapping(data, source=source)
    export_raw = _require_key(root, "export", source=source, expected_type=dict)
    workspace_raw = _require_key(root, "workspace", source=source, expected_type=dict)

    page_range_strategy = _require_key(
        root, "page_range_strategy", source=source, expected_type=str
    )
    if page_range_strategy not in _ALLOWED_PAGE_RANGE_STRATEGIES:
        allowed = ", ".join(sorted(_ALLOWED_PAGE_RANGE_STRATEGIES))
        raise _config_error(
            f"invalid value {page_range_strategy!r}; allowed: {allowed}",
            source=source,
            field="page_range_strategy",
        )

    table_selector = _require_key(root, "table_selector", source=source, expected_type=str)
    if table_selector not in _ALLOWED_TABLE_SELECTORS:
        allowed = ", ".join(sorted(_ALLOWED_TABLE_SELECTORS))
        raise _config_error(
            f"invalid value {table_selector!r}; allowed: {allowed}",
            source=source,
            field="table_selector",
        )

    toc_max_pages = _require_key(root, "toc_max_pages", source=source, expected_type=int)
    if toc_max_pages < 1:
        raise _config_error("must be >= 1", source=source, field="toc_max_pages")

    threshold = _require_key(
        root, "pattern_confidence_threshold", source=source, expected_type=(int, float)
    )
    if not 0.0 <= float(threshold) <= 1.0:
        raise _config_error(
            "must be in [0.0, 1.0]",
            source=source,
            field="pattern_confidence_threshold",
        )

    max_column_width = _require_key(
        export_raw, "max_column_width", source=source, expected_type=int
    )
    if max_column_width < 1:
        raise _config_error("must be >= 1", source=source, field="export.max_column_width")

    workspace_root = _require_key(workspace_raw, "root", source=source, expected_type=str)
    if not workspace_root.strip():
        raise _config_error("must be non-empty", source=source, field="workspace.root")

    return DefaultsConfig(
        schema_version=_require_key(root, "schema_version", source=source, expected_type=str),
        toc_max_pages=toc_max_pages,
        page_range_strategy=page_range_strategy,
        table_selector=table_selector,
        pattern_confidence_threshold=float(threshold),
        export=ExportConfig(
            max_column_width=max_column_width,
            freeze_panes=_require_key(
                export_raw, "freeze_panes", source=source, expected_type=bool
            ),
            bold_headers=_require_key(
                export_raw, "bold_headers", source=source, expected_type=bool
            ),
        ),
        workspace=WorkspaceConfig(root=workspace_root),
        debug=_require_key(root, "debug", source=source, expected_type=bool),
    )


def parse_profile(data: Any, *, source: str) -> ProfileConfig:
    """Parse and validate a PDF profile YAML file."""
    root = _require_mapping(data, source=source)
    profile_id = _validate_parameter_id(
        _require_key(root, "profile_id", source=source, expected_type=str),
        source=source,
        field="profile_id",
    )
    supported_raw = _require_key(
        root, "supported_parameters", source=source, expected_type=list
    )
    if not supported_raw:
        raise _config_error(
            "supported_parameters must be a non-empty list",
            source=source,
            field="supported_parameters",
        )

    supported_parameters: list[str] = []
    for index, item in enumerate(supported_raw):
        if not isinstance(item, str):
            raise _config_error(
                f"expected string at index {index}, got {type(item).__name__}",
                source=source,
                field="supported_parameters",
            )
        supported_parameters.append(_validate_parameter_id(item, source=source))

    _ensure_no_duplicates(supported_parameters, source=source, label="parameter_id")

    return ProfileConfig(
        profile_id=profile_id,
        display_name=_require_key(root, "display_name", source=source, expected_type=str),
        supported_parameters=tuple(supported_parameters),
    )


def parse_toc_patterns(data: Any, *, source: str) -> TocPatternsConfig:
    """Parse ``config/discovery/toc_patterns.yaml``."""
    root = _require_mapping(data, source=source)
    table_title_pattern = _require_key(
        root, "table_title_pattern", source=source, expected_type=str
    )
    toc_entry_pattern = _require_key(
        root, "toc_entry_pattern", source=source, expected_type=str
    )
    if not table_title_pattern.strip():
        raise _config_error("must be non-empty", source=source, field="table_title_pattern")
    if not toc_entry_pattern.strip():
        raise _config_error("must be non-empty", source=source, field="toc_entry_pattern")
    return TocPatternsConfig(
        table_title_pattern=table_title_pattern,
        toc_entry_pattern=toc_entry_pattern,
    )


def parse_parameter_aliases(data: Any, *, source: str) -> ParameterAliasesConfig:
    """Parse ``config/discovery/parameter_aliases.yaml``."""
    root = _require_mapping(data, source=source)
    aliases_raw = _require_key(root, "aliases", source=source, expected_type=dict)
    parsed: dict[str, tuple[str, ...]] = {}
    all_alias_strings: list[str] = []

    for parameter_id, alias_list in aliases_raw.items():
        _validate_parameter_id(parameter_id, source=source, field=f"aliases.{parameter_id}")
        if not isinstance(alias_list, list):
            raise _config_error(
                "expected list of alias strings",
                source=source,
                field=f"aliases.{parameter_id}",
            )
        if not alias_list:
            raise _config_error(
                "must contain at least one alias",
                source=source,
                field=f"aliases.{parameter_id}",
            )
        normalized: list[str] = []
        for index, alias in enumerate(alias_list):
            if not isinstance(alias, str) or not alias.strip():
                raise _config_error(
                    f"expected non-empty string at index {index}",
                    source=source,
                    field=f"aliases.{parameter_id}",
                )
            normalized.append(alias.strip())
        parsed[parameter_id] = tuple(normalized)
        all_alias_strings.extend(normalized)

    _ensure_no_duplicates(list(parsed.keys()), source=source, label="parameter_id")
    _ensure_no_duplicates(all_alias_strings, source=source, label="alias string")

    return ParameterAliasesConfig(aliases=MappingProxyType(parsed))


def parse_discovery(
    toc_patterns: TocPatternsConfig,
    parameter_aliases: ParameterAliasesConfig,
) -> DiscoveryConfig:
    """Combine discovery sub-configurations into a single object."""
    return DiscoveryConfig(
        toc_patterns=toc_patterns,
        parameter_aliases=parameter_aliases,
    )


def parse_pattern_signatures(data: Any, *, source: str) -> PatternSignaturesConfig:
    """Parse ``config/patterns/pattern_signatures.yaml``."""
    root = _require_mapping(data, source=source)
    signatures_raw = _require_key(root, "signatures", source=source, expected_type=dict)
    if not signatures_raw:
        raise _config_error("signatures must be non-empty", source=source, field="signatures")

    parsed: dict[str, dict[str, float]] = {}
    for pattern_name, weights in signatures_raw.items():
        _parse_enum(pattern_name, TablePattern, source=source, field=f"signatures.{pattern_name}")
        if not isinstance(weights, dict) or not weights:
            raise _config_error(
                "expected non-empty mapping of feature weights",
                source=source,
                field=f"signatures.{pattern_name}",
            )
        feature_weights: dict[str, float] = {}
        for feature, weight in weights.items():
            if not isinstance(feature, str) or not feature.strip():
                raise _config_error(
                    "feature names must be non-empty strings",
                    source=source,
                    field=f"signatures.{pattern_name}",
                )
            if not isinstance(weight, (int, float)):
                raise _config_error(
                    f"weight for {feature!r} must be numeric",
                    source=source,
                    field=f"signatures.{pattern_name}.{feature}",
                )
            if float(weight) < 0.0:
                raise _config_error(
                    f"weight for {feature!r} must be >= 0.0",
                    source=source,
                    field=f"signatures.{pattern_name}.{feature}",
                )
            feature_weights[feature] = float(weight)
        parsed[pattern_name] = feature_weights

    frozen = {key: MappingProxyType(value) for key, value in parsed.items()}
    return PatternSignaturesConfig(signatures=MappingProxyType(frozen))


def parse_registry(data: Any, *, source: str = "parsers/registry.yaml") -> ParserRegistryConfig:
    """Parse ``config/parsers/registry.yaml``."""
    root = _require_mapping(data, source=source)
    parsers_raw = _require_key(root, "parsers", source=source, expected_type=dict)
    parameters_raw = _require_key(root, "parameters", source=source, expected_type=dict)

    if not parsers_raw:
        raise _config_error("parsers must be non-empty", source=source, field="parsers")
    if not parameters_raw:
        raise _config_error("parameters must be non-empty", source=source, field="parameters")

    parsers: dict[str, ParserRegistryEntry] = {}
    for parser_id, entry in parsers_raw.items():
        if not isinstance(parser_id, str) or not parser_id.strip():
            raise _config_error("parser_id keys must be non-empty strings", source=source)
        if parser_id in parsers:
            raise _config_error(f"duplicate parser_id: {parser_id!r}", source=source)
        if not isinstance(entry, dict):
            raise _config_error(
                f"parsers.{parser_id} must be a mapping",
                source=source,
                field=f"parsers.{parser_id}",
            )
        family = _parse_enum(
            _require_key(entry, "family", source=source, expected_type=str),
            ParserFamily,
            source=source,
            field=f"parsers.{parser_id}.family",
        )
        patterns_raw = _require_key(entry, "patterns", source=source, expected_type=list)
        if not patterns_raw:
            raise _config_error(
                "patterns must be a non-empty list",
                source=source,
                field=f"parsers.{parser_id}.patterns",
            )
        patterns: list[TablePattern] = []
        for index, pattern_value in enumerate(patterns_raw):
            if not isinstance(pattern_value, str):
                raise _config_error(
                    f"expected string at index {index}",
                    source=source,
                    field=f"parsers.{parser_id}.patterns",
                )
            patterns.append(
                _parse_enum(
                    pattern_value,
                    TablePattern,
                    source=source,
                    field=f"parsers.{parser_id}.patterns[{index}]",
                )
            )
        _ensure_no_duplicates(
            [pattern.value for pattern in patterns],
            source=source,
            label=f"pattern in parsers.{parser_id}.patterns",
        )
        parsers[parser_id] = ParserRegistryEntry(
            parser_id=parser_id,
            family=family,
            patterns=tuple(patterns),
        )

    bindings: dict[str, ParameterRegistryBinding] = {}
    for parameter_id, binding in parameters_raw.items():
        _validate_parameter_id(parameter_id, source=source, field=f"parameters.{parameter_id}")
        if parameter_id in bindings:
            raise _config_error(
                f"duplicate parameter_id: {parameter_id!r}",
                source=source,
                field="parameters",
            )
        if not isinstance(binding, dict):
            raise _config_error(
                f"parameters.{parameter_id} must be a mapping",
                source=source,
                field=f"parameters.{parameter_id}",
            )
        parser_id = _require_key(
            binding, "parser_id", source=source, expected_type=str
        )
        if parser_id not in parsers:
            raise _config_error(
                f"parser_id {parser_id!r} is not defined under parsers",
                source=source,
                field=f"parameters.{parameter_id}.parser_id",
            )
        bindings[parameter_id] = ParameterRegistryBinding(
            parameter_id=parameter_id,
            parser_id=parser_id,
        )

    return ParserRegistryConfig(
        parsers=MappingProxyType(parsers),
        parameters=MappingProxyType(bindings),
    )


def parse_states_catalog(data: Any, *, source: str) -> StatesCatalog:
    """Parse ``config/catalogs/states.yaml``."""
    root = _require_mapping(data, source=source)
    states_raw = _require_key(root, "states", source=source, expected_type=list)
    if not states_raw:
        raise _config_error("states must be a non-empty list", source=source, field="states")
    states: list[str] = []
    for index, state in enumerate(states_raw):
        if not isinstance(state, str) or not state.strip():
            raise _config_error(
                f"expected non-empty string at index {index}",
                source=source,
                field="states",
            )
        states.append(state.strip())
    _ensure_no_duplicates(states, source=source, label="state name")
    return StatesCatalog(states=tuple(states))


def parse_state_aliases_catalog(data: Any, *, source: str) -> StateAliasesCatalog:
    """Parse ``config/catalogs/state_aliases.yaml``."""
    root = _require_mapping(data, source=source)
    aliases_raw = _require_key(root, "aliases", source=source, expected_type=dict)
    parsed: dict[str, str] = {}
    for alias, canonical in aliases_raw.items():
        if not isinstance(alias, str) or not alias.strip():
            raise _config_error("alias keys must be non-empty strings", source=source, field="aliases")
        if not isinstance(canonical, str) or not canonical.strip():
            raise _config_error(
                f"canonical value for alias {alias!r} must be a non-empty string",
                source=source,
                field=f"aliases.{alias}",
            )
        if alias in parsed:
            raise _config_error(f"duplicate alias key: {alias!r}", source=source, field="aliases")
        parsed[alias.strip()] = canonical.strip()
    return StateAliasesCatalog(aliases=MappingProxyType(parsed))


def parse_utilities_catalog(data: Any, *, source: str) -> UtilitiesCatalog:
    """Parse ``config/catalogs/utilities.yaml``."""
    root = _require_mapping(data, source=source)
    utilities_raw = _require_key(root, "utilities", source=source, expected_type=dict)
    parsed: dict[str, tuple[str, ...]] = {}
    for state, utility_list in utilities_raw.items():
        if not isinstance(state, str) or not state.strip():
            raise _config_error(
                "state keys must be non-empty strings",
                source=source,
                field="utilities",
            )
        if not isinstance(utility_list, list) or not utility_list:
            raise _config_error(
                f"utilities.{state} must be a non-empty list",
                source=source,
                field=f"utilities.{state}",
            )
        utilities: list[str] = []
        for index, utility in enumerate(utility_list):
            if not isinstance(utility, str) or not utility.strip():
                raise _config_error(
                    f"expected non-empty string at index {index}",
                    source=source,
                    field=f"utilities.{state}",
                )
            utilities.append(utility.strip())
        _ensure_no_duplicates(utilities, source=source, label=f"utility in {state!r}")
        parsed[state.strip()] = tuple(utilities)
    return UtilitiesCatalog(utilities=MappingProxyType(parsed))


def parse_catalogs(
    states: StatesCatalog,
    state_aliases: StateAliasesCatalog,
    utilities: UtilitiesCatalog,
    *,
    source: str = "catalogs/",
) -> CatalogsConfig:
    """Combine catalog files and validate alias targets."""
    canonical_states = set(states.states)
    for alias, canonical in state_aliases.aliases.items():
        if canonical not in canonical_states:
            raise _config_error(
                f"alias {alias!r} maps to unknown canonical state {canonical!r}",
                source=source,
                field="state_aliases.aliases",
            )
    for state in utilities.utilities:
        if state not in canonical_states:
            raise _config_error(
                f"utilities reference unknown state {state!r}",
                source=source,
                field="utilities",
            )
    return CatalogsConfig(
        states=states,
        state_aliases=state_aliases,
        utilities=utilities,
    )


_KNOWN_PARAMETER_KEYS = frozenset(
    {
        "parameter_id",
        "display_name",
        "sheet_name",
        "parser_id",
        "parser_family",
        "calibration_phrase",
        "force_pattern",
        "output_schema",
        "validation",
        "supported",
    }
)


def parse_parameter_config(
    data: Any,
    *,
    source: str,
    registry: ParserRegistryConfig | None = None,
    supported: bool = True,
) -> ParameterConfig:
    """Parse a merged parameter configuration mapping."""
    root = _require_mapping(data, source=source)
    parameter_id = _validate_parameter_id(
        _require_key(root, "parameter_id", source=source, expected_type=str),
        source=source,
    )

    parser_id = _require_key(root, "parser_id", source=source, expected_type=str)
    parser_family = _parse_enum(
        _require_key(root, "parser_family", source=source, expected_type=str),
        ParserFamily,
        source=source,
        field="parser_family",
    )

    force_pattern_raw = root.get("force_pattern")
    force_pattern: TablePattern | None = None
    if force_pattern_raw is not None:
        force_pattern = _parse_enum(
            force_pattern_raw,
            TablePattern,
            source=source,
            field="force_pattern",
        )

    output_schema_raw = _require_key(root, "output_schema", source=source, expected_type=dict)
    columns_raw = _require_key(
        output_schema_raw, "columns", source=source, expected_type=list
    )
    if not columns_raw:
        raise _config_error(
            "columns must be a non-empty list",
            source=source,
            field="output_schema.columns",
        )
    columns: list[str] = []
    for index, column in enumerate(columns_raw):
        if not isinstance(column, str) or not column.strip():
            raise _config_error(
                f"expected non-empty string at index {index}",
                source=source,
                field="output_schema.columns",
            )
        columns.append(column.strip())
    _ensure_no_duplicates(columns, source=source, label="output_schema column")

    validation_raw = _require_key(root, "validation", source=source, expected_type=dict)
    min_records = _require_key(
        validation_raw, "min_records", source=source, expected_type=int
    )
    if min_records < 0:
        raise _config_error("must be >= 0", source=source, field="validation.min_records")

    calibration_phrase = root.get("calibration_phrase")
    if calibration_phrase is not None and (
        not isinstance(calibration_phrase, str) or not calibration_phrase.strip()
    ):
        raise _config_error(
            "must be a non-empty string when set",
            source=source,
            field="calibration_phrase",
        )

    supported_value = root.get("supported", supported)
    if not isinstance(supported_value, bool):
        raise _config_error("must be a boolean", source=source, field="supported")

    extras = {
        key: value
        for key, value in root.items()
        if key not in _KNOWN_PARAMETER_KEYS
    }

    config = ParameterConfig(
        parameter_id=parameter_id,
        display_name=_require_key(root, "display_name", source=source, expected_type=str),
        sheet_name=_require_key(root, "sheet_name", source=source, expected_type=str),
        parser_id=parser_id,
        parser_family=parser_family,
        output_schema=OutputSchemaConfig(columns=tuple(columns)),
        validation=ParameterValidationConfig(min_records=min_records),
        supported=supported_value,
        calibration_phrase=calibration_phrase.strip() if calibration_phrase else None,
        force_pattern=force_pattern,
        extras=MappingProxyType(extras),
    )

    if registry is not None:
        validate_parameter_config(config, registry)

    return config


def validate_registry(registry: ParserRegistryConfig) -> None:
    """Validate cross-references inside the parser registry.

    Parsing already checks parser bindings; this function exists for explicit
    startup validation and unit tests.
    """
    parser_ids = set(registry.parsers.keys())
    if len(parser_ids) != len(registry.parsers):
        raise ConfigError("registry contains duplicate parser_id entries")

    parameter_ids = set(registry.parameters.keys())
    if len(parameter_ids) != len(registry.parameters):
        raise ConfigError("registry contains duplicate parameter_id entries")

    for binding in registry.parameters.values():
        if binding.parser_id not in registry.parsers:
            raise ConfigError(
                f"parameter {binding.parameter_id!r} references unknown parser_id "
                f"{binding.parser_id!r}"
            )


def validate_parameter_config(
    config: ParameterConfig,
    registry: ParserRegistryConfig,
) -> None:
    """Validate a parameter config against the parser registry."""
    binding = registry.parameters.get(config.parameter_id)
    if binding is None:
        raise ConfigError(
            f"parameter {config.parameter_id!r} is not registered in parsers/registry.yaml"
        )
    if binding.parser_id != config.parser_id:
        raise ConfigError(
            f"parameter {config.parameter_id!r} parser_id {config.parser_id!r} "
            f"does not match registry binding {binding.parser_id!r}"
        )

    parser_entry = registry.parsers.get(config.parser_id)
    if parser_entry is None:
        raise ConfigError(
            f"parameter {config.parameter_id!r} references unknown parser_id "
            f"{config.parser_id!r}"
        )
    if parser_entry.family is not config.parser_family:
        raise ConfigError(
            f"parameter {config.parameter_id!r} parser_family "
            f"{config.parser_family.value!r} does not match registry family "
            f"{parser_entry.family.value!r} for parser {config.parser_id!r}"
        )
    if config.force_pattern is not None and config.force_pattern not in parser_entry.patterns:
        raise ConfigError(
            f"parameter {config.parameter_id!r} force_pattern "
            f"{config.force_pattern.value!r} is not supported by parser "
            f"{config.parser_id!r} (allowed: "
            f"{', '.join(p.value for p in parser_entry.patterns)})"
        )


def validate_app_settings(settings: AppSettings) -> None:
    """Validate merged application settings and cross-file references."""
    validate_registry(settings.registry)

    if settings.profile.profile_id != settings.profile_id:
        raise ConfigError(
            f"profile_id mismatch: AppSettings.profile_id={settings.profile_id!r} "
            f"!= profile.profile_id={settings.profile.profile_id!r}"
        )

    registry_parameters = set(settings.registry.parameters.keys())
    for parameter_id in settings.profile.supported_parameters:
        if parameter_id not in registry_parameters:
            raise ConfigError(
                f"profile {settings.profile_id!r} lists unsupported parameter "
                f"{parameter_id!r} that is missing from parsers/registry.yaml"
            )

    alias_parameters = set(settings.discovery.parameter_aliases.aliases.keys())
    unknown_alias_parameters = alias_parameters - registry_parameters
    if unknown_alias_parameters:
        ordered = ", ".join(sorted(unknown_alias_parameters))
        raise ConfigError(
            f"parameter_aliases.yaml references unknown parameters: {ordered}"
        )

    signature_patterns = set(settings.patterns.signatures.keys())
    unknown_patterns = signature_patterns - {member.value for member in TablePattern}
    if unknown_patterns:
        ordered = ", ".join(sorted(unknown_patterns))
        raise ConfigError(f"pattern_signatures.yaml contains unknown patterns: {ordered}")

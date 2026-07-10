"""Load and validate YAML configuration into immutable typed settings.

Configuration is loaded from the project ``config/`` directory, validated through
``schema.py``, merged in layer order, and cached to avoid repeated disk reads.

Merge order (later layers override earlier ones)::

    defaults.yaml
        ↓
    pdf_profiles/{profile}.yaml
        ↓
    parsers/parameters/{parameter_id}.yaml
        ↓
    runtime overrides (optional)
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from table_scraper.config.schema import (
    AppSettings,
    CatalogsConfig,
    DefaultsConfig,
    DiscoveryConfig,
    ParameterConfig,
    ParserRegistryConfig,
    PatternSignaturesConfig,
    ProfileConfig,
    parse_catalogs,
    parse_defaults,
    parse_discovery,
    parse_parameter_aliases,
    parse_parameter_config,
    parse_pattern_signatures,
    parse_profile,
    parse_registry,
    parse_state_aliases_catalog,
    parse_states_catalog,
    parse_toc_patterns,
    parse_utilities_catalog,
    validate_app_settings,
    validate_parameter_config,
)
from table_scraper.domain.errors import ConfigError

DEFAULT_PROFILE_ID = "cerc_ursi_v1"

_NON_PARAMETER_MERGE_KEYS = frozenset(
    {
        "schema_version",
        "toc_max_pages",
        "page_range_strategy",
        "table_selector",
        "pattern_confidence_threshold",
        "export",
        "workspace",
        "debug",
        "profile_id",
        "supported_parameters",
        "parameter_overrides",
    }
)

_REQUIRED_FILES = (
    "defaults.yaml",
    "discovery/toc_patterns.yaml",
    "discovery/parameter_aliases.yaml",
    "patterns/pattern_signatures.yaml",
    "parsers/registry.yaml",
    "catalogs/states.yaml",
    "catalogs/state_aliases.yaml",
    "catalogs/utilities.yaml",
)


def resolve_config_root(start: Path | None = None) -> Path:
    """Locate the project ``config/`` directory.

    Resolution order:

    1. Explicit ``start`` argument when provided.
    2. ``TABLE_SCRAPER_CONFIG_ROOT`` environment variable (checked by caller via
       :class:`ConfigLoader` constructor).
    3. ``{project_root}/config`` relative to this package (``src/table_scraper/config``).

    Args:
        start: Optional directory that is or contains the config tree.

    Returns:
        Absolute path to the configuration root directory.

    Raises:
        ConfigError: When no configuration directory can be found.
    """
    candidates: list[Path] = []
    if start is not None:
        start = start.resolve()
        if (start / "defaults.yaml").is_file():
            candidates.append(start)
        nested = start / "config"
        if (nested / "defaults.yaml").is_file():
            candidates.append(nested)

    package_root = Path(__file__).resolve().parents[3]
    default_candidate = package_root / "config"
    if default_candidate not in candidates:
        candidates.append(default_candidate)

    for candidate in candidates:
        if (candidate / "defaults.yaml").is_file():
            return candidate

    searched = ", ".join(str(path) for path in candidates)
    raise ConfigError(f"configuration directory not found; searched: {searched}")


def deep_merge(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    """Deep-merge two mapping layers; ``overlay`` wins on conflicts.

    Args:
        base: Lower-precedence mapping (e.g. defaults).
        overlay: Higher-precedence mapping (e.g. profile or parameter YAML).

    Returns:
        New merged dictionary; inputs are not mutated.
    """
    result: dict[str, Any] = copy.deepcopy(dict(base))
    for key, value in overlay.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, Mapping)
        ):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _stable_mapping_hash(data: Mapping[str, Any] | None) -> str:
    """Return a deterministic hash for cache keys derived from override mappings."""
    if not data:
        return ""
    normalized = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class _YamlCacheEntry:
    """Cached YAML payload keyed by absolute path and modification time."""

    mtime_ns: int
    data: Any


class ConfigLoader:
    """Load, merge, validate, and cache project configuration.

    Instantiate with an explicit ``config_root`` in unit tests to point at fixture
    configuration trees without touching the repository ``config/`` directory.

    Example::

        loader = ConfigLoader(config_root=Path("tests/fixtures/config"))
        settings = loader.load_settings("/path/to/file.pdf", profile_name="cerc_ursi_v1")
        param_cfg = loader.load_parameter_config("banking_charges", settings=settings)
    """

    def __init__(
        self,
        config_root: Path | str | None = None,
        *,
        cache_enabled: bool = True,
    ) -> None:
        """Initialize the loader.

        Args:
            config_root: Optional explicit configuration root directory.
            cache_enabled: When ``False``, disable in-memory caching (useful in tests).
        """
        self._config_root = (
            resolve_config_root(Path(config_root)) if config_root is not None else resolve_config_root()
        )
        self._cache_enabled = cache_enabled
        self._yaml_cache: dict[Path, _YamlCacheEntry] = {}
        self._bundle_cache: dict[tuple[Any, ...], AppSettings] = {}
        self._parameter_cache: dict[tuple[Any, ...], ParameterConfig] = {}
        self._catalog_cache: CatalogsConfig | None = None

    @property
    def config_root(self) -> Path:
        """Absolute path to the active configuration directory."""
        return self._config_root

    def clear_cache(self) -> None:
        """Clear all in-memory caches (YAML, settings bundles, parameter configs)."""
        self._yaml_cache.clear()
        self._bundle_cache.clear()
        self._parameter_cache.clear()
        self._catalog_cache = None

    def _require_file(self, relative_path: str) -> Path:
        """Resolve a config-relative path and ensure the file exists."""
        path = self._config_root / relative_path
        if not path.is_file():
            raise ConfigError(f"missing configuration file: {path}")
        return path

    def _load_yaml(self, relative_path: str) -> Any:
        """Load a YAML file with mtime-aware caching."""
        path = self._require_file(relative_path)
        mtime_ns = path.stat().st_mtime_ns

        if self._cache_enabled:
            cached = self._yaml_cache.get(path)
            if cached is not None and cached.mtime_ns == mtime_ns:
                return copy.deepcopy(cached.data)

        try:
            raw_text = path.read_text(encoding="utf-8")
            data = yaml.safe_load(raw_text)
        except yaml.YAMLError as exc:
            raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
        except OSError as exc:
            raise ConfigError(f"unable to read configuration file {path}: {exc}") from exc

        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise ConfigError(f"expected mapping at root of {path}")

        if self._cache_enabled:
            self._yaml_cache[path] = _YamlCacheEntry(mtime_ns=mtime_ns, data=data)

        return copy.deepcopy(data)

    def validate_config_tree(self) -> None:
        """Ensure all required configuration files exist."""
        missing: list[str] = []
        for relative_path in _REQUIRED_FILES:
            path = self._config_root / relative_path
            if not path.is_file():
                missing.append(relative_path)
        if missing:
            joined = ", ".join(missing)
            raise ConfigError(
                f"missing required configuration files under {self._config_root}: {joined}"
            )

    def list_profile_ids(self) -> tuple[str, ...]:
        """Return available PDF profile IDs from ``config/pdf_profiles/``."""
        profiles_dir = self._config_root / "pdf_profiles"
        if not profiles_dir.is_dir():
            raise ConfigError(f"missing pdf_profiles directory: {profiles_dir}")
        return tuple(
            sorted(path.stem for path in profiles_dir.glob("*.yaml") if path.is_file())
        )

    def list_parameter_ids(self) -> tuple[str, ...]:
        """Return parameter IDs with YAML files under ``config/parsers/parameters/``."""
        parameters_dir = self._config_root / "parsers" / "parameters"
        if not parameters_dir.is_dir():
            raise ConfigError(f"missing parsers/parameters directory: {parameters_dir}")
        return tuple(
            sorted(path.stem for path in parameters_dir.glob("*.yaml") if path.is_file())
        )

    def load_defaults(self) -> DefaultsConfig:
        """Load and validate ``config/defaults.yaml``."""
        return parse_defaults(
            self._load_yaml("defaults.yaml"),
            source=str(self._config_root / "defaults.yaml"),
        )

    def load_profile(self, profile_id: str) -> ProfileConfig:
        """Load and validate ``config/pdf_profiles/{profile_id}.yaml``."""
        relative = f"pdf_profiles/{profile_id}.yaml"
        return parse_profile(
            self._load_yaml(relative),
            source=str(self._config_root / relative),
        )

    def load_registry(self) -> ParserRegistryConfig:
        """Load and validate ``config/parsers/registry.yaml``."""
        return parse_registry(
            self._load_yaml("parsers/registry.yaml"),
            source=str(self._config_root / "parsers/registry.yaml"),
        )

    def load_discovery(self) -> DiscoveryConfig:
        """Load and validate discovery configuration files."""
        toc_patterns = parse_toc_patterns(
            self._load_yaml("discovery/toc_patterns.yaml"),
            source=str(self._config_root / "discovery/toc_patterns.yaml"),
        )
        parameter_aliases = parse_parameter_aliases(
            self._load_yaml("discovery/parameter_aliases.yaml"),
            source=str(self._config_root / "discovery/parameter_aliases.yaml"),
        )
        return parse_discovery(toc_patterns, parameter_aliases)

    def load_pattern_signatures(self) -> PatternSignaturesConfig:
        """Load and validate ``config/patterns/pattern_signatures.yaml``."""
        return parse_pattern_signatures(
            self._load_yaml("patterns/pattern_signatures.yaml"),
            source=str(self._config_root / "patterns/pattern_signatures.yaml"),
        )

    def load_catalogs(self) -> CatalogsConfig:
        """Load and validate catalog reference data."""
        if self._cache_enabled and self._catalog_cache is not None:
            return self._catalog_cache
        states = parse_states_catalog(
            self._load_yaml("catalogs/states.yaml"),
            source=str(self._config_root / "catalogs/states.yaml"),
        )
        state_aliases = parse_state_aliases_catalog(
            self._load_yaml("catalogs/state_aliases.yaml"),
            source=str(self._config_root / "catalogs/state_aliases.yaml"),
        )
        utilities = parse_utilities_catalog(
            self._load_yaml("catalogs/utilities.yaml"),
            source=str(self._config_root / "catalogs/utilities.yaml"),
        )
        catalogs = parse_catalogs(
            states,
            state_aliases,
            utilities,
            source=str(self._config_root / "catalogs"),
        )
        if self._cache_enabled:
            self._catalog_cache = catalogs
        return catalogs

    def _resolve_profile_id(self, profile_name: str | None) -> str:
        """Resolve the active profile ID."""
        if profile_name is not None:
            profile_id = profile_name.strip()
            if not profile_id:
                raise ConfigError("profile_name must be non-empty when provided")
            profile_path = self._config_root / "pdf_profiles" / f"{profile_id}.yaml"
            if not profile_path.is_file():
                available = ", ".join(self.list_profile_ids()) or "(none)"
                raise ConfigError(
                    f"unknown profile {profile_id!r}; available profiles: {available}"
                )
            return profile_id

        available = self.list_profile_ids()
        if DEFAULT_PROFILE_ID in available:
            return DEFAULT_PROFILE_ID
        if len(available) == 1:
            return available[0]
        if not available:
            raise ConfigError("no pdf_profiles found in configuration directory")
        raise ConfigError(
            "profile_name is required when multiple pdf_profiles exist; "
            f"available profiles: {', '.join(available)}"
        )

    def load_settings(
        self,
        pdf_path: Path | str,
        profile_name: str | None = None,
        *,
        runtime_overrides: Mapping[str, Any] | None = None,
    ) -> AppSettings:
        """Merge defaults and profile layers into session :class:`AppSettings`.

        Args:
            pdf_path: Path to the input PDF (stored for session context only).
            profile_name: PDF profile ID; defaults to ``cerc_ursi_v1`` when present.
            runtime_overrides: Optional highest-precedence override mapping.

        Returns:
            Immutable, validated application settings bundle.
        """
        pdf_path_str = str(pdf_path)
        profile_id = self._resolve_profile_id(profile_name)
        cache_key = (
            str(self._config_root),
            pdf_path_str,
            profile_id,
            _stable_mapping_hash(runtime_overrides),
        )
        if self._cache_enabled and cache_key in self._bundle_cache:
            return self._bundle_cache[cache_key]

        self.validate_config_tree()

        defaults_raw = self._load_yaml("defaults.yaml")
        if runtime_overrides:
            defaults_raw = deep_merge(defaults_raw, runtime_overrides)

        defaults = parse_defaults(
            defaults_raw,
            source=str(self._config_root / "defaults.yaml"),
        )
        profile = self.load_profile(profile_id)
        discovery = self.load_discovery()
        patterns = self.load_pattern_signatures()
        registry = self.load_registry()
        catalogs = self.load_catalogs()

        settings = AppSettings(
            pdf_path=pdf_path_str,
            profile_id=profile.profile_id,
            defaults=defaults,
            profile=profile,
            discovery=discovery,
            patterns=patterns,
            registry=registry,
            catalogs=catalogs,
        )
        validate_app_settings(settings)

        if self._cache_enabled:
            self._bundle_cache[cache_key] = settings
        return settings

    def load_parameter_config(
        self,
        parameter_id: str,
        *,
        profile_name: str | None = None,
        settings: AppSettings | None = None,
        runtime_overrides: Mapping[str, Any] | None = None,
    ) -> ParameterConfig:
        """Load merged configuration for one parameter.

        Merge order::

            defaults.yaml → profile.yaml → parameters/{id}.yaml → runtime overrides

        Args:
            parameter_id: Stable snake_case parameter identifier.
            profile_name: Profile used to determine ``supported`` flag; inferred
                from ``settings`` or default profile when omitted.
            settings: Optional pre-loaded :class:`AppSettings` bundle.
            runtime_overrides: Optional highest-precedence override mapping.

        Returns:
            Immutable, validated :class:`ParameterConfig`.
        """
        parameter_id = parameter_id.strip()
        if not parameter_id:
            raise ConfigError("parameter_id must be non-empty")

        active_settings = settings or self.load_settings(
            pdf_path="",
            profile_name=profile_name,
        )
        profile_id = active_settings.profile_id
        cache_key = (
            str(self._config_root),
            parameter_id,
            profile_id,
            _stable_mapping_hash(runtime_overrides),
        )
        if self._cache_enabled and cache_key in self._parameter_cache:
            return self._parameter_cache[cache_key]

        relative = f"parsers/parameters/{parameter_id}.yaml"
        parameter_path = self._config_root / relative
        if not parameter_path.is_file():
            available = ", ".join(self.list_parameter_ids()) or "(none)"
            raise ConfigError(
                f"missing parameter configuration file: {parameter_path}; "
                f"available parameters: {available}"
            )

        registry = active_settings.registry
        if parameter_id not in registry.parameters:
            raise ConfigError(
                f"parameter {parameter_id!r} is not registered in parsers/registry.yaml"
            )

        defaults_raw = self._load_yaml("defaults.yaml")
        profile_raw = self._load_yaml(f"pdf_profiles/{profile_id}.yaml")
        parameter_raw = self._load_yaml(relative)

        merged: dict[str, Any] = {}
        parameter_defaults = defaults_raw.get("parameter_defaults")
        if isinstance(parameter_defaults, dict):
            merged = deep_merge(merged, parameter_defaults)

        profile_parameter_overrides = profile_raw.get("parameter_overrides", {})
        if isinstance(profile_parameter_overrides, dict):
            param_override = profile_parameter_overrides.get(parameter_id)
            if isinstance(param_override, dict):
                merged = deep_merge(merged, param_override)

        merged = deep_merge(merged, parameter_raw)

        if runtime_overrides:
            merged = deep_merge(merged, runtime_overrides)

        parameter_merged = {
            key: value
            for key, value in merged.items()
            if key not in _NON_PARAMETER_MERGE_KEYS
        }

        registry_binding = registry.parameters[parameter_id]
        parameter_merged["parameter_id"] = parameter_id
        parameter_merged["parser_id"] = registry_binding.parser_id
        parser_entry = registry.parsers[registry_binding.parser_id]
        parameter_merged.setdefault("parser_family", parser_entry.family.value)

        supported = parameter_id in active_settings.profile.supported_parameters
        config = parse_parameter_config(
            parameter_merged,
            source=str(parameter_path),
            registry=registry,
            supported=supported,
        )
        validate_parameter_config(config, registry)

        if self._cache_enabled:
            self._parameter_cache[cache_key] = config
        return config


_default_loader: ConfigLoader | None = None


def get_config_loader(config_root: Path | str | None = None) -> ConfigLoader:
    """Return a shared :class:`ConfigLoader` instance.

    Args:
        config_root: When provided, construct a fresh loader rooted at ``config_root``
            instead of returning the process-wide singleton.

    Returns:
        Config loader bound to the requested or default configuration directory.
    """
    global _default_loader
    if config_root is not None:
        return ConfigLoader(config_root=config_root)
    if _default_loader is None:
        _default_loader = ConfigLoader()
    return _default_loader


def clear_config_cache() -> None:
    """Clear cached configuration for the process-wide loader and ``lru_cache`` hooks."""
    global _default_loader
    if _default_loader is not None:
        _default_loader.clear_cache()
    _default_loader = None
    load_settings.cache_clear()
    load_parameter_config.cache_clear()


@lru_cache(maxsize=16)
def load_settings(
    pdf_path: Path | str,
    profile_name: str | None = None,
) -> AppSettings:
    """Load merged application settings using the process-wide config loader.

    See :meth:`ConfigLoader.load_settings` for details.
    """
    return get_config_loader().load_settings(pdf_path, profile_name)


@lru_cache(maxsize=64)
def load_parameter_config(parameter_id: str) -> ParameterConfig:
    """Load one parameter configuration using the process-wide config loader.

    See :meth:`ConfigLoader.load_parameter_config` for details.
    """
    return get_config_loader().load_parameter_config(parameter_id)

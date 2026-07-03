The configuration system is implemented in `schema.py` (typed models + validation) and `loader.py` (YAML I/O, merge, cache). All existing repo config files load and validate successfully.

---

## Configuration hierarchy

Configuration is split into **layers** (global → edition-specific → parameter-specific) and **domains** (shared infrastructure vs. per-parameter behavior):

```text
config/
├── defaults.yaml              ← global pipeline defaults
├── pdf_profiles/*.yaml        ← PDF edition / publisher profile
├── discovery/                 ← TOC regex, parameter aliases
├── patterns/                  ← classifier feature weights
├── parsers/
│   ├── registry.yaml          ← parser plugins + parameter routing
│   └── parameters/*.yaml      ← per-parameter schemas & thresholds
└── catalogs/                  ← states, aliases, utilities
```

**Typed objects produced:**

| Object | Source |
|--------|--------|
| `DefaultsConfig` | `defaults.yaml` |
| `ProfileConfig` | `pdf_profiles/{id}.yaml` |
| `DiscoveryConfig` | `discovery/*` |
| `PatternSignaturesConfig` | `patterns/pattern_signatures.yaml` |
| `ParserRegistryConfig` | `parsers/registry.yaml` |
| `CatalogsConfig` | `catalogs/*` |
| `AppSettings` | Bundle of all shared config for a session |
| `ParameterConfig` | Merged per-parameter config |

Everything is **frozen** (`@dataclass(frozen=True, slots=True)`) and immutable after load.

---

## Loading order

### Session settings — `load_settings(pdf_path, profile_name?)`

1. **Global defaults** — `defaults.yaml`
2. **Runtime overrides** (optional) — merged into defaults before parsing
3. **Shared bundles** loaded independently (not merged into each other):
   - PDF profile
   - Discovery
   - Pattern signatures
   - Parser registry
   - Catalogs
4. Cross-reference validation via `validate_app_settings()`

### Parameter config — `load_parameter_config(parameter_id, ...)`

Later layers override earlier ones:

```text
defaults.yaml → parameter_defaults: {…}     (optional section, future-ready)
        ↓
pdf_profiles/{profile}.yaml → parameter_overrides.{parameter_id}: {…}
        ↓
parsers/parameters/{parameter_id}.yaml
        ↓
runtime_overrides (optional)
        ↓
registry binding injects authoritative parser_id / parser_family
```

The `supported` flag is derived from the profile’s `supported_parameters` list (not from YAML alone).

---

## Validation flow

Validation runs in two stages:

**1. Per-file parsing** (`schema.parse_*`) — raises `ConfigError` with `[field]` and file path:

- Required keys and types
- Enum values (`TablePattern`, `ParserFamily`)
- Duplicate IDs (parameters, parsers, aliases, states, columns)
- Regex constraints (`parameter_id` format)
- Numeric bounds (confidence, min_records, etc.)

**2. Cross-file validation** — after assembly:

| Function | Checks |
|----------|--------|
| `validate_registry()` | Every parameter binding references a defined parser |
| `validate_parameter_config()` | Parameter `parser_id` / `parser_family` match registry; `force_pattern` is allowed for that parser |
| `validate_app_settings()` | Profile parameters exist in registry; alias keys are registered; pattern signatures use valid `TablePattern` values; state alias targets exist in `states.yaml`; utility states are canonical |

Missing files are detected early via `validate_config_tree()` and `_require_file()`.

---

## Cache strategy

Three cache layers inside `ConfigLoader`:

| Cache | Key | Invalidation |
|-------|-----|--------------|
| **YAML file cache** | Absolute path + `mtime_ns` | File modification time change |
| **Settings bundle cache** | `(config_root, pdf_path, profile_id, overrides_hash)` | Key change |
| **Parameter config cache** | `(config_root, parameter_id, profile_id, overrides_hash)` | Key change |

Additional module-level `@lru_cache` on `load_settings()` and `load_parameter_config()` for the process-wide singleton loader.

**Test hooks:**

```python
loader = ConfigLoader(config_root=fixture_path, cache_enabled=False)
loader.clear_cache()
clear_config_cache()  # resets singleton + lru_cache
```

---

## Adding future PDFs without Python changes

To support a new PDF edition or parameter, only YAML files are needed:

**New PDF edition (e.g. `cerc_ursi_v2`):**

1. Add `config/pdf_profiles/cerc_ursi_v2.yaml` with `profile_id`, `display_name`, `supported_parameters`
2. Run pipeline with `load_settings(pdf_path, profile_name="cerc_ursi_v2")`

**New parameter (e.g. `open_access_charges`):**

1. Add `config/parsers/parameters/open_access_charges.yaml`
2. Register in `config/parsers/registry.yaml` under `parsers` and `parameters`
3. Add to profile `supported_parameters`
4. Optionally add discovery aliases in `config/discovery/parameter_aliases.yaml`

**Override behavior for one parameter in one profile** (no Python):

```yaml
# pdf_profiles/cerc_ursi_v2.yaml
parameter_overrides:
  banking_charges:
    validation:
      min_records: 30
```

**Global parameter defaults** (future):

```yaml
# defaults.yaml
parameter_defaults:
  validation:
    min_records: 10
```

No code changes are required unless you introduce a **new parser family** (that needs a Python plugin). Routing existing families to new parameters is entirely YAML-driven.
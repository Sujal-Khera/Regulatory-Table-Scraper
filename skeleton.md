The project skeleton is in place per `software_architecture_design.md` and `data_contracts.md`. All Python modules compile successfully (`python -m compileall src scripts`).

## Folders created

| Area | Folders |
|------|---------|
| **Source package** | `src/table_scraper/` + 14 subpackages (`domain`, `config`, `storage`, `adapters`, `indexing`, `discovery`, `extraction`, `normalization`, `patterns`, `parsing`, `parsing/families`, `validation`, `validation/rules`, `export`, `pipeline`, `pipeline/stages`, `interfaces`, `interfaces/cli`, `interfaces/api`) |
| **Config (YAML)** | `config/`, `config/pdf_profiles/`, `config/discovery/`, `config/patterns/`, `config/parsers/`, `config/parsers/parameters/`, `config/catalogs/` |
| **Tests** | `tests/`, `tests/unit/`, `tests/integration/`, `tests/fixtures/sample_pages/`, `tests/fixtures/golden/` |
| **Runtime** | `workspaces/` |
| **Scripts** | `scripts/` |

## Files created

| Category | Count | Notable files |
|----------|-------|---------------|
| **Python modules** | 70 | Full package under `src/table_scraper/` |
| **Config YAML** | 14 | `defaults.yaml`, profile, discovery, patterns, registry, 5 parameter configs, 3 catalogs |
| **Project meta** | 5 | `pyproject.toml`, `ARCHITECTURE.md`, `README.md`, `.gitignore`, `workspaces/.gitkeep` |
| **Scripts** | 2 | `inspect_parameter.py`, `validate_workspace.py` |
| **Test stubs** | 3 | `tests/__init__.py`, `unit/__init__.py`, `integration/__init__.py` |
| **Fixture placeholders** | 2 | `.gitkeep` in `sample_pages/`, `golden/` |

## Modules created (by package)

| Package | Modules |
|---------|---------|
| **domain** | `enums.py`, `errors.py`, `models.py`, `protocols.py` |
| **config** | `loader.py`, `schema.py` |
| **storage** | `workspace.py`, `artifact_store.py`, `sqlite_index.py` |
| **adapters** | `pdf_reader.py`, `excel_writer.py` |
| **indexing** | `page_indexer.py`, `title_detector.py` |
| **discovery** | `toc_extractor.py`, `parameter_catalog.py`, `page_range_resolver.py`, `page_offset_calibrator.py` |
| **extraction** | `table_extractor.py`, `table_selector.py`, `table_merger.py` |
| **normalization** | `geometry.py`, `text_cleanup.py`, `hierarchy.py`, `block_segmentation.py` |
| **patterns** | `classifier.py`, `features.py`, `signatures.py` |
| **parsing** | `base.py`, `registry.py`, `router.py` |
| **parsing/families** | `narrative.py`, `numeric_matrix.py`, `wide_to_long.py`, `state_block_matrix.py`, `simple_matrix.py`, `key_value.py` |
| **validation** | `runner.py`, `rules/base.py` |
| **export** | `dataframe_builder.py`, `excel_exporter.py`, `formatter.py` |
| **pipeline** | `session.py`, `runner.py` |
| **pipeline/stages** | `index_stage.py`, `discover_stage.py`, `extract_stage.py`, `parse_stage.py`, `export_stage.py` |
| **interfaces/cli** | `app.py`, `prompts.py` |
| **interfaces/api** | `__init__.py` (stub) |

Every module has TODO docstrings; stub functions/methods use `raise NotImplementedError` or `pass` only.

## Dataclass placeholders (`domain/models.py`)

All 18 data contracts plus auxiliary types:

`PDFDocument`, `TableTitle`, `PageRecord`, `PageIndex`, `PageRange`, `ParameterDefinition`, `ParameterCatalog`, `UserSelection`, `RawTable`, `MergedTable`, `NormalizedTable`, `PatternClassification`, `StateBlock`, `ParsedRecord`, `ParseResult`, `ValidationCheck`, `ValidationReport`, `ExcelSheetInfo`, `ExcelWorkbook`, `StageRecord`, `WorkspaceManifest`, plus `TocEntry`, `PageIndexResult`, `ExportResult`, `PipelineResult`.

## Enums (`domain/enums.py`)

`TablePattern`, `ParserFamily`, `ArtifactKind`, `SessionStage`, `StageStatus`, `TitleSource`, `PageRangeSource`, `SelectionMode`, `RowLabel`, `RoutingSource`, `ParseStatus`, `BlockParserHint`, `ExportMode`, `DiscoverySource`, `ValidationSeverity`.

## Protocols / interfaces (`domain/protocols.py`)

| Protocol | Role |
|----------|------|
| `PdfReader` | PDF text/table extraction adapter |
| `ParserPlugin` | Semantic parser plugin contract |
| `PatternClassifier` | Table pattern scoring |
| `ArtifactStore` | Workspace artifact I/O |
| `ExcelExporter` | Multi-sheet Excel export |
| `PageSearchIndex` | FTS5 page search |
| `ValidationRule` | Pluggable validation check |

## Abstract base classes

| Class | Module |
|-------|--------|
| `BaseParser` | `parsing/base.py` |
| `BaseValidationRule` | `validation/rules/base.py` |
| `NarrativeParser`, `NumericMatrixParser`, `WideToLongParser`, `StateBlockMatrixParser`, `SimpleMatrixParser`, `KeyValueParser` | `parsing/families/*` |
| `PdfPlumberReader` | `adapters/pdf_reader.py` |
| `OpenpyxlExcelWriter` | `adapters/excel_writer.py` |
| `Workspace`, `ArtifactStore`, `PageSearchIndex`, `ParserRegistry`, `PipelineSession` | respective modules |

## Exceptions (`domain/errors.py`)

`TableScraperError`, `DiscoveryError`, `ExtractionError`, `NormalizationError`, `PatternUnknownError`, `ParserNotFoundError`, `ValidationError`, `ConfigError`, `WorkspaceError`.

## Verify locally

```bash
pip install -e .
python -m compileall src scripts
```

Recommended next step (when you're ready): implement `domain/` validation helpers, `config/loader.py`, and `storage/workspace.py` — everything else hangs off those three.
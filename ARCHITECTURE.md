# Table Scraper — Architecture Index

Short index for the regulatory PDF table extraction pipeline. Full design: `software_architecture_design.md`. Data contracts: `data_contracts.md`.

## Layers (dependency flows inward)

```
interfaces → pipeline → stage packages → storage/config/adapters → domain
```

## Stage packages

| Package | Responsibility |
|---------|----------------|
| `indexing/` | Full-PDF page index |
| `discovery/` | TOC, parameter catalog, page ranges |
| `extraction/` | Raw table pull and merge |
| `normalization/` | Geometry and text cleanup |
| `patterns/` | Table pattern classification |
| `parsing/` | Plugin parsers (families in `parsing/families/`) |
| `validation/` | Post-parse quality gates |
| `export/` | Excel warehouse output |

## Forbidden imports

- `domain/` must not import pdfplumber, openpyxl, or SQLite
- `parsing/families/*` must not import `interfaces/` or `adapters/`
- `patterns/` must not import `parsing/`
- `discovery/` must not import `extraction/`
- `export/` must not import PDF adapters or `discovery/`

## Adding a parameter

1. Add `config/parsers/parameters/{parameter_id}.yaml`
2. Register in `config/parsers/registry.yaml`
3. Reuse an existing parser family or extend one in `parsing/families/`

## Config (repo root `config/`)

Behavior varies via YAML — not Python. Profiles in `config/pdf_profiles/`.

## Workspaces

Runtime artifacts under `workspaces/{pdf_content_hash}/` (gitignored).

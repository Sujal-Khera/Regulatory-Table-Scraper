The Workspace and Artifact Management layer is implemented in:

- `src/table_scraper/storage/workspace.py`
- `src/table_scraper/storage/artifact_store.py`

## What was implemented

### Workspace (`workspace.py`)
- **`Workspace.open(pdf_path)`** — creates or resumes a workspace from a PDF
- **`Workspace.load(workspace_id)`** — reopens a session without the PDF path
- **Workspace ID** — first 16 hex chars of SHA-256 PDF bytes
- **Manifest** — initial `WorkspaceManifest` with all stages `pending`
- **Stage tracking** — `mark_stage_complete()`, `invalidate_stage()`, `invalidate_downstream()`
- **Paths** — `get_artifact_path()` / `path_for()` aligned with `data_contracts.md`
- **Cache helpers** — `artifact_exists()`, `is_stage_stale()`, `stage_status()`
- **Thread safety** — `threading.RLock` on manifest mutations
- **Layout** — auto-creates `index/`, `discovery/`, `extraction/`, `parsing/`, `export/`

### Artifact Store (`artifact_store.py`)
- **`write()` / `read()` / `exists()` / `delete()` / `list_artifacts()`**
- **Formats** — JSON (typed domain models), CSV, binary (`.db`, `.xlsx`)
- **Atomic writes** — temp file + `os.replace()` + `fsync`
- **Manifest sync** — each write registers the artifact path on the mapped stage
- **`ArtifactCodec`** — enum-aware serialization/deserialization with `get_type_hints()`

---

## Workspace lifecycle

```text
PDF file
   │
   ▼
Workspace.open(pdf_path)
   │
   ├─ Compute SHA-256 → workspace_id = hash[:16]
   ├─ workspaces/{workspace_id}/ + stage directories
   └─ manifest.json (PDFDocument embedded, all stages pending)
   │
   ▼
Pipeline stages run → ArtifactStore.write() → manifest tracks paths
   │
   ▼
mark_stage_complete(stage, input_hash=...) → stage = complete
   │
   ▼
Workspace.load(workspace_id) or Workspace.open(same pdf) → resume session
```

**Reopen behavior:** Same PDF bytes → same `workspace_id` → existing manifest loaded. PDF path/size updates are reflected in the manifest. Different PDF bytes → different hash prefix → new workspace directory (isolation per document).

---

## Artifact lifecycle

```text
Stage produces domain object (e.g. PageIndex)
   │
   ▼
store.write(ArtifactKind.PAGE_INDEX, page_index)
   │
   ├─ Resolve path via get_artifact_path()
   ├─ Serialize (JSON / CSV / bytes)
   ├─ Atomic write to disk
   └─ manifest.stages[index].artifact_paths += path
   │
   ▼
store.read(ArtifactKind.PAGE_INDEX) → typed PageIndex
   │
   ▼
store.delete(...) → file removed, manifest bumped
```

Each `ArtifactKind` maps to a fixed path under the workspace root (e.g. `index/page_index.json`, `extraction/{param}/normalized.json`).

---

## Cache invalidation flow

```text
Upstream input changes
   │
   ├─ invalidate_stage(stage)
   │     → stage.status = stale
   │     → added to manifest.invalidated_stages
   │
   └─ invalidate_downstream(stage, parameter_id?)
         → all later global stages marked stale
         → if parameter_id set: parameter_status[param][stage] = stale
```

**Examples (from `data_contracts.md`):**

| Event | Call |
|-------|------|
| Page index rebuilt | `invalidate_downstream(SessionStage.INDEX)` |
| User confirms new page range | `invalidate_downstream(SessionStage.SELECT, parameter_id="banking_charges")` |
| Parser config change | `invalidate_downstream(SessionStage.PARSE, parameter_id=...)` |

Stages check `workspace.is_stage_stale(stage)` before running and skip when artifacts are still valid (once pipeline stages are implemented).

---

## How future stages will use this layer

```python
workspace = Workspace.open(pdf_path, profile_name="cerc_ursi_v1")
store = ArtifactStore(workspace)

# Index stage
if workspace.is_stage_stale(SessionStage.INDEX) or not store.exists(ArtifactKind.PAGE_INDEX):
    page_index = build_page_index(...)  # indexing/page_indexer.py
    store.write(ArtifactKind.PAGE_INDEX, page_index)
    workspace.mark_stage_complete(SessionStage.INDEX, input_hash=index_input_hash)

# Extract stage (per parameter)
if workspace.is_stage_stale(SessionStage.EXTRACT) or not store.exists(ArtifactKind.RAW_MERGED, param_id):
    merged = extract_and_merge(...)
    store.write(ArtifactKind.RAW_MERGED, merged, parameter_id=param_id)
    workspace.mark_stage_complete(SessionStage.EXTRACT, input_hash=range_hash)
```

Future pipeline stages should:
1. **Only** persist through `ArtifactStore` (not ad-hoc file I/O)
2. Use **`get_artifact_path()`** for path inspection/debugging
3. Call **`mark_stage_complete()`** with an **`input_hash`** for idempotent reruns
4. Call **`invalidate_downstream()`** when upstream inputs change (e.g. confirmed page range)
5. Use **`Workspace.load()`** in CLI/tools to resume without the original PDF path

No domain, config, PDF reader, SQLite, or pipeline code was modified — only the two storage modules above.
"""Workspace layout and lifecycle for PDF-scoped artifact storage.

Each regulatory PDF receives an isolated workspace directory keyed by the first
16 hex characters of the PDF content SHA-256 hash. The workspace root holds a
:class:`~table_scraper.domain.models.WorkspaceManifest` plus stage-scoped artifact
directories (``index/``, ``discovery/``, ``extraction/``, ``parsing/``, ``export/``).

Thread safety
-------------
Manifest mutations are guarded by a re-entrant lock. Callers should perform
artifact I/O through :class:`~table_scraper.storage.artifact_store.ArtifactStore`,
which acquires the same lock when updating the manifest.
"""

from __future__ import annotations

import hashlib
import re
import threading
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from table_scraper.config.loader import load_settings
from table_scraper.domain.enums import ArtifactKind, SessionStage, StageStatus
from table_scraper.domain.errors import WorkspaceError
from table_scraper.domain.models import PDFDocument, StageRecord, WorkspaceManifest

MANIFEST_SCHEMA_VERSION = "1.0.0"
"""Semver contract version written to ``manifest.json``."""

MANIFEST_FILENAME = "manifest.json"
"""Manifest file name relative to the workspace root."""

WORKSPACE_ID_HEX_LENGTH = 16
"""Number of hex characters used for ``workspace_id`` (PDF hash prefix)."""

_PARAMETER_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

_STAGE_ORDER: tuple[SessionStage, ...] = (
    SessionStage.INDEX,
    SessionStage.DISCOVER,
    SessionStage.SELECT,
    SessionStage.EXTRACT,
    SessionStage.NORMALIZE,
    SessionStage.CLASSIFY,
    SessionStage.PARSE,
    SessionStage.VALIDATE,
    SessionStage.EXPORT,
)

_PARAMETER_SCOPED_STAGES: frozenset[SessionStage] = frozenset(
    {
        SessionStage.EXTRACT,
        SessionStage.NORMALIZE,
        SessionStage.CLASSIFY,
        SessionStage.PARSE,
        SessionStage.VALIDATE,
        SessionStage.EXPORT,
    }
)

_ARTIFACT_KINDS_REQUIRING_PARAMETER: frozenset[ArtifactKind] = frozenset(
    {
        ArtifactKind.CONFIRMED_RANGE,
        ArtifactKind.PAGE_PREVIEW,
        ArtifactKind.RAW_PAGES,
        ArtifactKind.RAW_MERGED,
        ArtifactKind.NORMALIZED,
        ArtifactKind.STATE_BLOCKS,
        ArtifactKind.PATTERN,
        ArtifactKind.RECORDS,
        ArtifactKind.VALIDATION,
    }
)

_ARTIFACT_STAGE_MAP: dict[ArtifactKind, SessionStage] = {
    ArtifactKind.PAGE_INDEX: SessionStage.INDEX,
    ArtifactKind.PAGE_INDEX_CSV: SessionStage.INDEX,
    ArtifactKind.PAGE_INDEX_DB: SessionStage.INDEX,
    ArtifactKind.TOC_RAW: SessionStage.DISCOVER,
    ArtifactKind.PARAMETER_CATALOG: SessionStage.DISCOVER,
    ArtifactKind.PARAMETER_RANGES: SessionStage.DISCOVER,
    ArtifactKind.CONFIRMED_RANGE: SessionStage.SELECT,
    ArtifactKind.USER_SELECTION: SessionStage.SELECT,
    ArtifactKind.PAGE_PREVIEW: SessionStage.SELECT,
    ArtifactKind.RAW_PAGES: SessionStage.EXTRACT,
    ArtifactKind.RAW_MERGED: SessionStage.EXTRACT,
    ArtifactKind.NORMALIZED: SessionStage.NORMALIZE,
    ArtifactKind.STATE_BLOCKS: SessionStage.NORMALIZE,
    ArtifactKind.PATTERN: SessionStage.CLASSIFY,
    ArtifactKind.RECORDS: SessionStage.PARSE,
    ArtifactKind.VALIDATION: SessionStage.VALIDATE,
    ArtifactKind.EXCEL: SessionStage.EXPORT,
}

_STAGE_DIRECTORIES: tuple[str, ...] = (
    "index",
    "discovery",
    "extraction",
    "parsing",
    "export",
)


def _utc_now_iso() -> str:
    """Return the current UTC timestamp as an ISO 8601 string."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _project_root() -> Path:
    """Return the repository root (parent of ``src/``)."""
    return Path(__file__).resolve().parents[3]


def _resolve_workspace_root(root: Path | str, *, base: Path | None = None) -> Path:
    """Resolve a workspace root path, allowing repository-relative values."""
    path = Path(root)
    if not path.is_absolute():
        anchor = base or _project_root()
        path = anchor / path
    return path.resolve()


def _compute_pdf_hash(pdf_path: Path) -> str:
    """Compute the SHA-256 hex digest of a PDF file's bytes."""
    digest = hashlib.sha256()
    try:
        with pdf_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise WorkspaceError(f"unable to read PDF for hashing: {pdf_path}: {exc}") from exc
    return digest.hexdigest()


def _workspace_id_from_hash(content_hash: str) -> str:
    """Derive the workspace identifier from a full content hash."""
    return content_hash[:WORKSPACE_ID_HEX_LENGTH]


def _validate_parameter_id(parameter_id: str, *, context: str) -> str:
    """Validate a snake_case parameter identifier."""
    if not _PARAMETER_ID_PATTERN.match(parameter_id):
        raise WorkspaceError(
            f"{context}: parameter_id must match ^[a-z][a-z0-9_]*$, got {parameter_id!r}"
        )
    return parameter_id


def _initial_stage_records() -> dict[str, StageRecord]:
    """Create pending stage records for every pipeline stage."""
    return {
        stage.value: StageRecord(status=StageStatus.PENDING)
        for stage in SessionStage
    }


def _stage_index(stage: SessionStage) -> int:
    """Return the ordinal index of a pipeline stage."""
    try:
        return _STAGE_ORDER.index(stage)
    except ValueError as exc:
        raise WorkspaceError(f"unknown pipeline stage: {stage!r}") from exc


def _downstream_stages(stage: SessionStage) -> tuple[SessionStage, ...]:
    """Return all stages strictly after ``stage`` in pipeline order."""
    index = _stage_index(stage)
    return _STAGE_ORDER[index + 1 :]


class Workspace:
    """PDF-scoped workspace keyed by content hash.

    Use :meth:`open` to create or resume a workspace for a PDF path, or
    :meth:`load` to reopen a previous session by workspace identifier alone.

    Attributes:
        root: Absolute filesystem path to the workspace directory.
        manifest: Current :class:`~table_scraper.domain.models.WorkspaceManifest`.
    """

    def __init__(self, root: Path, manifest: WorkspaceManifest) -> None:
        self.root = root.resolve()
        self.manifest = manifest
        self._lock = threading.RLock()

    @property
    def workspace_id(self) -> str:
        """Return the PDF-scoped workspace identifier."""
        return self.manifest.workspace_id

    @classmethod
    def open(
        cls,
        pdf_path: Path | str,
        profile_name: str | None = None,
        *,
        workspace_root: Path | str | None = None,
        page_count: int = 1,
    ) -> Workspace:
        """Open an existing workspace or create a new one for ``pdf_path``.

        The workspace directory name is derived from the PDF content hash prefix.
        When a manifest already exists, the on-disk PDF hash must match the
        current file bytes or a :class:`~table_scraper.domain.errors.WorkspaceError`
        is raised (PDF content changed — create a new workspace or invalidate).

        Args:
            pdf_path: Path to the input regulatory PDF.
            profile_name: Optional PDF profile identifier (defaults via config).
            workspace_root: Override for the configured workspace root directory.
            page_count: Provisional page count stored in a **new** manifest until
                the PDF adapter validates the real value during indexing.

        Returns:
            Initialized :class:`Workspace` with directories and manifest ready.

        Raises:
            WorkspaceError: When the PDF is missing, unreadable, or hash-mismatched.
        """
        resolved_pdf = Path(pdf_path).expanduser().resolve()
        if not resolved_pdf.is_file():
            raise WorkspaceError(f"PDF file not found: {resolved_pdf}")

        settings = load_settings(resolved_pdf, profile_name)
        root_base = _resolve_workspace_root(
            workspace_root or settings.defaults.workspace.root,
        )
        content_hash = _compute_pdf_hash(resolved_pdf)
        workspace_id = _workspace_id_from_hash(content_hash)
        workspace_dir = root_base / workspace_id
        manifest_path = workspace_dir / MANIFEST_FILENAME

        if manifest_path.is_file():
            workspace = cls._load_from_disk(workspace_dir)
            if workspace.manifest.pdf.content_hash != content_hash:
                raise WorkspaceError(
                    f"PDF content hash mismatch for workspace {workspace_id!r} at "
                    f"{workspace_dir}: manifest expects "
                    f"{workspace.manifest.pdf.content_hash!r}, "
                    f"file has {content_hash!r}. The PDF bytes changed; invalidate "
                    f"the workspace or process the file as a new document."
                )
            workspace._refresh_pdf_reference(resolved_pdf, settings.profile_id)
            return workspace

        if page_count < 1:
            raise WorkspaceError("page_count must be >= 1 when creating a workspace")

        opened_at = _utc_now_iso()
        pdf_document = PDFDocument(
            path=str(resolved_pdf),
            content_hash=content_hash,
            page_count=page_count,
            file_size_bytes=resolved_pdf.stat().st_size,
            profile_id=settings.profile_id,
            opened_at=opened_at,
            filename=resolved_pdf.name,
        )
        timestamp = opened_at
        manifest = WorkspaceManifest(
            schema_version=MANIFEST_SCHEMA_VERSION,
            workspace_id=workspace_id,
            pdf=pdf_document,
            created_at=timestamp,
            updated_at=timestamp,
            profile_id=settings.profile_id,
            stages=_initial_stage_records(),
            version=1,
        )
        workspace = cls(workspace_dir, manifest)
        workspace._ensure_layout()
        workspace._persist_manifest()
        return workspace

    @classmethod
    def load(
        cls,
        workspace_id: str,
        *,
        workspace_root: Path | str | None = None,
    ) -> Workspace:
        """Reopen a workspace by identifier without supplying the PDF path.

        Args:
            workspace_id: PDF hash prefix (first 16 hex characters).
            workspace_root: Override for the configured workspace root directory.

        Returns:
            Loaded :class:`Workspace`.

        Raises:
            WorkspaceError: When the workspace directory or manifest is missing.
        """
        if len(workspace_id) != WORKSPACE_ID_HEX_LENGTH:
            raise WorkspaceError(
                f"workspace_id must be {WORKSPACE_ID_HEX_LENGTH} hex characters, "
                f"got {workspace_id!r}"
            )
        if not re.fullmatch(r"[0-9a-fA-F]+", workspace_id):
            raise WorkspaceError(
                f"workspace_id must be hexadecimal, got {workspace_id!r}"
            )

        if workspace_root is None:
            settings = load_settings("", profile_name=None)
            root_base = _resolve_workspace_root(settings.defaults.workspace.root)
        else:
            root_base = _resolve_workspace_root(workspace_root)

        workspace_dir = root_base / workspace_id.lower()
        if not workspace_dir.is_dir():
            raise WorkspaceError(f"workspace directory not found: {workspace_dir}")
        return cls._load_from_disk(workspace_dir)

    @classmethod
    def _load_from_disk(cls, workspace_dir: Path) -> Workspace:
        """Load a workspace manifest from ``workspace_dir``."""
        manifest_path = workspace_dir / MANIFEST_FILENAME
        if not manifest_path.is_file():
            raise WorkspaceError(
                f"workspace manifest missing at {manifest_path}; "
                f"expected {MANIFEST_FILENAME} under {workspace_dir}"
            )
        from table_scraper.storage.artifact_store import ArtifactCodec
        import json

        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest = ArtifactCodec.decode_manifest(payload)
        except WorkspaceError:
            raise
        except Exception as exc:
            raise WorkspaceError(
                f"unable to read workspace manifest at {manifest_path}: {exc}"
            ) from exc

        workspace = cls(workspace_dir, manifest)
        workspace._ensure_layout()
        return workspace

    def _refresh_pdf_reference(self, pdf_path: Path, profile_id: str) -> None:
        """Update manifest PDF metadata when reopening from a new path."""
        with self._lock:
            current = self.manifest.pdf
            if (
                current.path == str(pdf_path)
                and current.file_size_bytes == pdf_path.stat().st_size
                and self.manifest.profile_id == profile_id
            ):
                return
            updated_pdf = replace(
                current,
                path=str(pdf_path),
                file_size_bytes=pdf_path.stat().st_size,
                filename=pdf_path.name,
                opened_at=_utc_now_iso(),
            )
            self.manifest = replace(
                self.manifest,
                pdf=updated_pdf,
                profile_id=profile_id,
                updated_at=_utc_now_iso(),
            )
            self._persist_manifest()

    def _ensure_layout(self) -> None:
        """Create workspace root and standard stage directories."""
        self.root.mkdir(parents=True, exist_ok=True)
        for directory in _STAGE_DIRECTORIES:
            (self.root / directory).mkdir(parents=True, exist_ok=True)

    def get_artifact_path(
        self,
        kind: ArtifactKind,
        parameter_id: str | None = None,
    ) -> Path:
        """Return the absolute filesystem path for an artifact kind.

        This is the canonical path resolver used by
        :class:`~table_scraper.storage.artifact_store.ArtifactStore`. Paths
        follow the persistence matrix in ``data_contracts.md``.

        Args:
            kind: Artifact type determining directory and file name.
            parameter_id: Required for parameter-scoped artifact kinds.

        Returns:
            Absolute :class:`pathlib.Path` to the artifact file.

        Raises:
            WorkspaceError: When ``parameter_id`` is missing or invalid.
        """
        relative = self.get_artifact_relative_path(kind, parameter_id)
        return self.root / relative

    def get_artifact_relative_path(
        self,
        kind: ArtifactKind,
        parameter_id: str | None = None,
    ) -> str:
        """Return the workspace-relative artifact path string.

        Args:
            kind: Artifact type determining directory and file name.
            parameter_id: Required for parameter-scoped artifact kinds.

        Returns:
            Path relative to the workspace root using forward slashes.

        Raises:
            WorkspaceError: When ``parameter_id`` is missing or invalid.
        """
        if kind in _ARTIFACT_KINDS_REQUIRING_PARAMETER:
            if parameter_id is None:
                raise WorkspaceError(
                    f"parameter_id is required for artifact kind {kind.value!r}"
                )
            parameter_id = _validate_parameter_id(
                parameter_id,
                context=f"artifact kind {kind.value}",
            )

        if kind is ArtifactKind.MANIFEST:
            return MANIFEST_FILENAME
        if kind is ArtifactKind.PAGE_INDEX:
            return "index/page_index.json"
        if kind is ArtifactKind.PAGE_INDEX_CSV:
            return "index/page_index.csv"
        if kind is ArtifactKind.PAGE_INDEX_DB:
            return "index/page_index.db"
        if kind is ArtifactKind.TOC_RAW:
            return "discovery/toc_raw.json"
        if kind is ArtifactKind.PARAMETER_CATALOG:
            return "discovery/parameter_catalog.json"
        if kind is ArtifactKind.PARAMETER_RANGES:
            return "discovery/parameter_ranges.json"
        if kind is ArtifactKind.USER_SELECTION:
            return "discovery/user_selection.json"
        if kind is ArtifactKind.CONFIRMED_RANGE:
            return f"discovery/{parameter_id}/confirmed_range.json"
        if kind is ArtifactKind.PAGE_PREVIEW:
            return f"discovery/{parameter_id}/preview.json"
        if kind is ArtifactKind.RAW_PAGES:
            return f"extraction/{parameter_id}/raw_pages.json"
        if kind is ArtifactKind.RAW_MERGED:
            return f"extraction/{parameter_id}/raw_merged.json"
        if kind is ArtifactKind.NORMALIZED:
            return f"extraction/{parameter_id}/normalized.json"
        if kind is ArtifactKind.STATE_BLOCKS:
            return f"extraction/{parameter_id}/state_blocks.json"
        if kind is ArtifactKind.PATTERN:
            return f"parsing/{parameter_id}/pattern.json"
        if kind is ArtifactKind.RECORDS:
            return f"parsing/{parameter_id}/records.json"
        if kind is ArtifactKind.VALIDATION:
            return f"parsing/{parameter_id}/validation.json"
        if kind is ArtifactKind.EXCEL:
            if parameter_id is None:
                return "export/Regulatory_Parameter_Warehouse.xlsx"
            return f"export/{parameter_id}.xlsx"

        raise WorkspaceError(f"unsupported artifact kind: {kind!r}")

    def path_for(
        self,
        kind: ArtifactKind,
        parameter_id: str | None = None,
    ) -> Path:
        """Alias for :meth:`get_artifact_path` (architecture-facing API)."""
        return self.get_artifact_path(kind, parameter_id)

    def artifact_exists(
        self,
        kind: ArtifactKind,
        parameter_id: str | None = None,
    ) -> bool:
        """Return whether the artifact file exists on disk.

        Args:
            kind: Artifact type to check.
            parameter_id: Parameter scope when required by ``kind``.

        Returns:
            ``True`` when the resolved artifact path is a regular file.
        """
        return self.get_artifact_path(kind, parameter_id).is_file()

    def mark_stage_complete(
        self,
        stage: SessionStage,
        *,
        input_hash: str | None = None,
        artifact_paths: list[str] | None = None,
    ) -> None:
        """Mark a pipeline stage complete in the manifest.

        Updates the stage record to :attr:`~StageStatus.COMPLETE`, records the
        completion timestamp, and optionally stores input lineage and artifact
        paths for idempotency checks.

        Args:
            stage: Pipeline stage that finished successfully.
            input_hash: Hash of direct inputs used for stale detection.
            artifact_paths: Workspace-relative artifact paths produced by the stage.
        """
        with self._lock:
            stages = dict(self.manifest.stages)
            key = stage.value
            existing = stages.get(key, StageRecord(status=StageStatus.PENDING))
            stages[key] = StageRecord(
                status=StageStatus.COMPLETE,
                completed_at=_utc_now_iso(),
                artifact_paths=list(artifact_paths or existing.artifact_paths),
                input_hash=input_hash if input_hash is not None else existing.input_hash,
            )
            invalidated = [
                item for item in self.manifest.invalidated_stages if item != key
            ]
            self.manifest = replace(
                self.manifest,
                stages=stages,
                invalidated_stages=invalidated,
                updated_at=_utc_now_iso(),
                version=(self.manifest.version or 0) + 1,
            )
            self._persist_manifest()

    def invalidate_stage(self, stage: SessionStage) -> None:
        """Mark a single stage as stale and queue it for rerun.

        Args:
            stage: Pipeline stage whose outputs are no longer valid.
        """
        with self._lock:
            stages = dict(self.manifest.stages)
            key = stage.value
            existing = stages.get(key, StageRecord(status=StageStatus.PENDING))
            stages[key] = StageRecord(
                status=StageStatus.STALE,
                completed_at=existing.completed_at,
                artifact_paths=list(existing.artifact_paths),
                input_hash=existing.input_hash,
            )
            invalidated = list(self.manifest.invalidated_stages)
            if key not in invalidated:
                invalidated.append(key)
            self.manifest = replace(
                self.manifest,
                stages=stages,
                invalidated_stages=invalidated,
                updated_at=_utc_now_iso(),
                version=(self.manifest.version or 0) + 1,
            )
            self._persist_manifest()

    def invalidate_downstream(
        self,
        stage: SessionStage,
        *,
        parameter_id: str | None = None,
    ) -> None:
        """Mark all stages after ``stage`` as stale.

        Global stages (``index``, ``discover``, ``select``) invalidate the entire
        downstream pipeline. When ``parameter_id`` is supplied and ``stage`` is
        parameter-scoped (or upstream of parameter work), only that parameter's
        downstream status entries are marked stale.

        Args:
            stage: Stage whose downstream dependents should be invalidated.
            parameter_id: Optional parameter scope for extraction→export stages.
        """
        downstream = _downstream_stages(stage)
        if not downstream:
            return

        with self._lock:
            stages = dict(self.manifest.stages)
            invalidated = list(self.manifest.invalidated_stages)
            parameter_status = dict(self.manifest.parameter_status)

            for downstream_stage in downstream:
                key = downstream_stage.value
                existing = stages.get(key, StageRecord(status=StageStatus.PENDING))
                stages[key] = StageRecord(
                    status=StageStatus.STALE,
                    completed_at=existing.completed_at,
                    artifact_paths=list(existing.artifact_paths),
                    input_hash=existing.input_hash,
                )
                if key not in invalidated:
                    invalidated.append(key)

            if parameter_id is not None:
                parameter_id = _validate_parameter_id(
                    parameter_id,
                    context="invalidate_downstream",
                )
                entry = dict(parameter_status.get(parameter_id, {}))
                for downstream_stage in downstream:
                    if downstream_stage in _PARAMETER_SCOPED_STAGES:
                        entry[downstream_stage.value] = {
                            "status": StageStatus.STALE.value,
                            "invalidated_at": _utc_now_iso(),
                        }
                parameter_status[parameter_id] = entry

            self.manifest = replace(
                self.manifest,
                stages=stages,
                invalidated_stages=invalidated,
                parameter_status=parameter_status,
                updated_at=_utc_now_iso(),
                version=(self.manifest.version or 0) + 1,
            )
            self._persist_manifest()

    def register_artifact_write(
        self,
        kind: ArtifactKind,
        relative_path: str,
        *,
        parameter_id: str | None = None,
    ) -> None:
        """Record an artifact write in the manifest (called by ArtifactStore).

        Appends the path to the mapped stage's ``artifact_paths`` list and bumps
        the manifest revision without marking the stage complete.

        Args:
            kind: Written artifact kind.
            relative_path: Workspace-relative path returned by the store.
            parameter_id: Parameter scope when applicable.
        """
        stage = _ARTIFACT_STAGE_MAP.get(kind)
        if stage is None:
            return

        with self._lock:
            stages = dict(self.manifest.stages)
            key = stage.value
            existing = stages.get(key, StageRecord(status=StageStatus.PENDING))
            paths = list(existing.artifact_paths)
            if relative_path not in paths:
                paths.append(relative_path)
            stages[key] = StageRecord(
                status=existing.status,
                completed_at=existing.completed_at,
                artifact_paths=paths,
                input_hash=existing.input_hash,
            )

            parameter_status = dict(self.manifest.parameter_status)
            if parameter_id is not None and stage in _PARAMETER_SCOPED_STAGES:
                parameter_id = _validate_parameter_id(
                    parameter_id,
                    context="register_artifact_write",
                )
                entry = dict(parameter_status.get(parameter_id, {}))
                entry[stage.value] = {
                    "status": existing.status.value,
                    "artifact_paths": paths,
                    "updated_at": _utc_now_iso(),
                }
                parameter_status[parameter_id] = entry

            self.manifest = replace(
                self.manifest,
                stages=stages,
                parameter_status=parameter_status,
                updated_at=_utc_now_iso(),
                version=(self.manifest.version or 0) + 1,
            )
            self._persist_manifest()

    def _persist_manifest(self) -> None:
        """Atomically write ``manifest.json`` from the current in-memory manifest."""
        from table_scraper.storage.artifact_store import ArtifactCodec

        manifest_path = self.root / MANIFEST_FILENAME
        payload = ArtifactCodec.encode_manifest(self.manifest)
        ArtifactCodec.write_json_atomic(manifest_path, payload)

    def stage_status(self, stage: SessionStage) -> StageStatus:
        """Return the current status recorded for a pipeline stage."""
        record = self.manifest.stages.get(stage.value)
        if record is None:
            return StageStatus.PENDING
        return record.status

    def is_stage_stale(self, stage: SessionStage) -> bool:
        """Return whether a stage is marked stale or listed for invalidation."""
        if stage.value in self.manifest.invalidated_stages:
            return True
        return self.stage_status(stage) is StageStatus.STALE

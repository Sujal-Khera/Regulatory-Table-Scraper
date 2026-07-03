"""Read/write JSON, CSV, and binary workspace artifacts.

:class:`ArtifactStore` is the typed persistence layer for pipeline stages. It
maps :class:`~table_scraper.domain.enums.ArtifactKind` values to canonical
workspace paths, performs atomic writes, and keeps the workspace manifest in
sync whenever artifacts are written.

Thread safety
-------------
All public methods acquire the parent :class:`~table_scraper.storage.workspace.Workspace`
lock so manifest updates remain consistent with artifact I/O.
"""

from __future__ import annotations

import csv
import json
import os
import tempfile
from dataclasses import fields, is_dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from io import StringIO
from pathlib import Path
from types import UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

from table_scraper.domain.enums import ArtifactKind
from table_scraper.domain.errors import WorkspaceError
from table_scraper.domain.models import (
    MergedTable,
    NormalizedTable,
    PageIndex,
    PageRange,
    ParameterCatalog,
    ParseResult,
    PatternClassification,
    RawTable,
    StateBlock,
    UserSelection,
    ValidationReport,
    WorkspaceManifest,
)
from table_scraper.storage.workspace import MANIFEST_SCHEMA_VERSION, Workspace

_BINARY_KINDS: frozenset[ArtifactKind] = frozenset(
    {
        ArtifactKind.PAGE_INDEX_DB,
        ArtifactKind.EXCEL,
    }
)

_CSV_KINDS: frozenset[ArtifactKind] = frozenset({ArtifactKind.PAGE_INDEX_CSV})


class ArtifactCodec:
    """Serialize and deserialize domain models for artifact persistence."""

    @staticmethod
    def encode_value(value: Any) -> Any:
        """Convert a domain value into a JSON-serializable structure."""
        if value is None:
            return None
        if isinstance(value, Enum):
            return value.value
        if is_dataclass(value):
            return {
                field.name: ArtifactCodec.encode_value(getattr(value, field.name))
                for field in fields(value)
            }
        if isinstance(value, dict):
            return {str(key): ArtifactCodec.encode_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [ArtifactCodec.encode_value(item) for item in value]
        return value

    @staticmethod
    def decode_value(annotation: Any, value: Any) -> Any:
        """Convert a JSON value back to a typed domain value."""
        if value is None:
            return None

        origin = get_origin(annotation)
        if origin is list:
            (item_type,) = get_args(annotation) or (Any,)
            if not isinstance(value, list):
                raise WorkspaceError(f"expected list, got {type(value).__name__}")
            return [ArtifactCodec.decode_value(item_type, item) for item in value]

        if origin is dict:
            args = get_args(annotation)
            value_type = args[1] if len(args) == 2 else Any
            if not isinstance(value, dict):
                raise WorkspaceError(f"expected dict, got {type(value).__name__}")
            return {
                str(key): ArtifactCodec.decode_value(value_type, item)
                for key, item in value.items()
            }

        if origin in (Union, UnionType):
            for arg in get_args(annotation):
                if arg is type(None):
                    continue
                try:
                    return ArtifactCodec.decode_value(arg, value)
                except (WorkspaceError, ValueError, KeyError, TypeError):
                    continue
            return value

        if isinstance(annotation, type) and issubclass(annotation, Enum):
            return annotation(value)

        if isinstance(annotation, type) and is_dataclass(annotation):
            if not isinstance(value, dict):
                raise WorkspaceError(
                    f"expected mapping for {annotation.__name__}, got {type(value).__name__}"
                )
            return ArtifactCodec.decode_dataclass(annotation, value)

        return value

    @staticmethod
    def decode_dataclass(cls: type[Any], data: dict[str, Any]) -> Any:
        """Construct a dataclass from a JSON mapping."""
        type_hints = get_type_hints(cls)
        kwargs: dict[str, Any] = {}
        for field in fields(cls):
            if field.name not in data:
                continue
            annotation = type_hints.get(field.name, field.type)
            kwargs[field.name] = ArtifactCodec.decode_value(annotation, data[field.name])
        return cls(**kwargs)

    @classmethod
    def encode_manifest(cls, manifest: WorkspaceManifest) -> dict[str, Any]:
        """Encode a workspace manifest for JSON persistence."""
        payload = cls.encode_value(manifest)
        assert isinstance(payload, dict)
        payload["schema_version"] = manifest.schema_version
        return payload

    @classmethod
    def decode_manifest(cls, payload: dict[str, Any]) -> WorkspaceManifest:
        """Decode a workspace manifest from JSON."""
        return cls.decode_dataclass(WorkspaceManifest, payload)

    @classmethod
    def decode_artifact(cls, kind: ArtifactKind, payload: Any) -> Any:
        """Decode a persisted artifact payload into a domain type when known."""
        if kind is ArtifactKind.PAGE_INDEX:
            return cls.decode_dataclass(PageIndex, payload)
        if kind is ArtifactKind.PARAMETER_CATALOG:
            return cls.decode_dataclass(ParameterCatalog, payload)
        if kind is ArtifactKind.CONFIRMED_RANGE:
            return cls.decode_dataclass(PageRange, payload)
        if kind is ArtifactKind.USER_SELECTION:
            return cls.decode_dataclass(UserSelection, payload)
        if kind is ArtifactKind.RAW_MERGED:
            return cls.decode_dataclass(MergedTable, payload)
        if kind is ArtifactKind.NORMALIZED:
            return cls.decode_dataclass(NormalizedTable, payload)
        if kind is ArtifactKind.PATTERN:
            return cls.decode_dataclass(PatternClassification, payload)
        if kind is ArtifactKind.RECORDS:
            return cls.decode_dataclass(ParseResult, payload)
        if kind is ArtifactKind.VALIDATION:
            return cls.decode_dataclass(ValidationReport, payload)
        if kind is ArtifactKind.STATE_BLOCKS:
            if not isinstance(payload, list):
                raise WorkspaceError("state_blocks artifact must be a JSON array")
            return [cls.decode_dataclass(StateBlock, item) for item in payload]
        if kind is ArtifactKind.RAW_PAGES:
            if not isinstance(payload, list):
                raise WorkspaceError("raw_pages artifact must be a JSON array")
            return [cls.decode_dataclass(RawTable, item) for item in payload]
        return payload

    @staticmethod
    def write_json_atomic(path: Path, payload: Any) -> None:
        """Write JSON atomically via a temporary file and ``os.replace``."""
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(payload, indent=2, sort_keys=True)
        encoded = encoded + "\n"
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        finally:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)

    @staticmethod
    def write_bytes_atomic(path: Path, payload: bytes) -> None:
        """Write binary data atomically via a temporary file and ``os.replace``."""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        finally:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)


class ArtifactStore:
    """Typed artifact persistence with cache invalidation by stage.

    Implements the :class:`~table_scraper.domain.protocols.ArtifactStore` protocol.
    Each write updates the workspace manifest with the artifact path so pipeline
    stages can implement idempotent skip logic.

    Example::

        workspace = Workspace.open("/path/to/report.pdf")
        store = ArtifactStore(workspace)
        store.write(ArtifactKind.PAGE_INDEX, page_index)
        if workspace.is_stage_stale(SessionStage.DISCOVER):
            ...
    """

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    def write(
        self,
        kind: ArtifactKind,
        data: Any,
        parameter_id: str | None = None,
    ) -> str:
        """Persist an artifact to the workspace.

        JSON artifacts receive a ``schema_version`` field when the payload is a
        mapping that omits one. Writes are atomic (temp file + replace) and parent
        directories are created automatically.

        Args:
            kind: Artifact type determining path and serialization format.
            data: Domain object, mapping, list, CSV rows, or bytes (binary kinds).
            parameter_id: Parameter scope for per-parameter artifacts.

        Returns:
            Workspace-relative path to the written artifact.

        Raises:
            WorkspaceError: On unsupported payloads or I/O failures.
        """
        path = self.workspace.get_artifact_path(kind, parameter_id)
        relative_path = self.workspace.get_artifact_relative_path(kind, parameter_id)

        with self.workspace._lock:
            try:
                if kind in _BINARY_KINDS:
                    self._write_binary(path, data)
                elif kind in _CSV_KINDS:
                    self._write_csv(path, data)
                else:
                    self._write_json(path, data)
            except WorkspaceError:
                raise
            except Exception as exc:
                raise WorkspaceError(
                    f"failed to write artifact {kind.value!r} to {path}: {exc}"
                ) from exc

            if kind is not ArtifactKind.MANIFEST:
                self.workspace.register_artifact_write(
                    kind,
                    relative_path,
                    parameter_id=parameter_id,
                )
        return relative_path

    def read(self, kind: ArtifactKind, parameter_id: str | None = None) -> Any:
        """Load a typed artifact from the workspace.

        Args:
            kind: Artifact type determining path and deserialization.
            parameter_id: Parameter scope for per-parameter artifacts.

        Returns:
            Deserialized domain object, mapping, list, or bytes depending on kind.

        Raises:
            WorkspaceError: When the artifact is missing or corrupt.
        """
        path = self.workspace.get_artifact_path(kind, parameter_id)
        if not path.is_file():
            raise WorkspaceError(
                f"artifact not found: {kind.value!r} at {path} "
                f"(workspace {self.workspace.workspace_id!r})"
            )

        with self.workspace._lock:
            try:
                if kind in _BINARY_KINDS:
                    return self._read_binary(path)
                if kind in _CSV_KINDS:
                    return self._read_csv(path)
                return self._read_json(kind, path)
            except WorkspaceError:
                raise
            except Exception as exc:
                raise WorkspaceError(
                    f"failed to read artifact {kind.value!r} from {path}: {exc}"
                ) from exc

    def exists(self, kind: ArtifactKind, parameter_id: str | None = None) -> bool:
        """Return whether an artifact file exists for ``kind``."""
        return self.workspace.artifact_exists(kind, parameter_id)

    def delete(self, kind: ArtifactKind, parameter_id: str | None = None) -> bool:
        """Delete an artifact file if it exists.

        Args:
            kind: Artifact type to remove.
            parameter_id: Parameter scope when required by ``kind``.

        Returns:
            ``True`` when a file was deleted, ``False`` when nothing existed.
        """
        path = self.workspace.get_artifact_path(kind, parameter_id)
        with self.workspace._lock:
            if not path.is_file():
                return False
            try:
                path.unlink()
            except OSError as exc:
                raise WorkspaceError(f"failed to delete artifact at {path}: {exc}") from exc
            self.workspace.manifest = replace(
                self.workspace.manifest,
                updated_at=datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat(),
                version=(self.workspace.manifest.version or 0) + 1,
            )
            self.workspace._persist_manifest()
            return True

    def list_artifacts(
        self,
        *,
        kind: ArtifactKind | None = None,
        parameter_id: str | None = None,
    ) -> list[str]:
        """List workspace-relative artifact paths.

        When ``kind`` is provided, only paths matching that artifact template are
        returned. When ``parameter_id`` is provided, results are limited to paths
        containing ``/{parameter_id}/`` or ``export/{parameter_id}.``.

        Args:
            kind: Optional artifact kind filter.
            parameter_id: Optional parameter scope filter.

        Returns:
            Sorted list of workspace-relative file paths.
        """
        if kind is not None:
            if self.exists(kind, parameter_id):
                return [self.workspace.get_artifact_relative_path(kind, parameter_id)]
            return []

        matches: list[str] = []
        for file_path in sorted(self.workspace.root.rglob("*")):
            if not file_path.is_file():
                continue
            if file_path.name == "manifest.json":
                continue
            relative = file_path.relative_to(self.workspace.root).as_posix()
            if parameter_id is not None:
                scoped = f"/{relative}/"
                if f"/{parameter_id}/" not in scoped and not relative.startswith(
                    f"export/{parameter_id}."
                ):
                    continue
            matches.append(relative)
        return matches

    def _write_json(self, path: Path, data: Any) -> None:
        payload = ArtifactCodec.encode_value(data)
        if not isinstance(payload, (dict, list)):
            raise WorkspaceError(
                f"JSON artifact write expects dataclass, dict, or list; "
                f"got {type(data).__name__}"
            )

        if isinstance(payload, dict) and "schema_version" not in payload:
            payload["schema_version"] = MANIFEST_SCHEMA_VERSION

        ArtifactCodec.write_json_atomic(path, payload)


    def _read_json(self, kind: ArtifactKind, path: Path) -> Any:
        try:
            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise WorkspaceError(f"invalid JSON in artifact {path}: {exc}") from exc
        except OSError as exc:
            raise WorkspaceError(f"unable to read artifact {path}: {exc}") from exc
        return ArtifactCodec.decode_artifact(kind, payload)

    def _write_csv(self, path: Path, data: Any) -> None:
        if not isinstance(data, list):
            raise WorkspaceError(
                f"CSV artifact write expects list of rows; got {type(data).__name__}"
            )
        rows = data

        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                if rows and isinstance(rows[0], dict):
                    fieldnames = list(rows[0].keys())
                    writer = csv.DictWriter(handle, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
                else:
                    writer = csv.writer(handle)
                    writer.writerows(rows)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        finally:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)

    def _read_csv(self, path: Path) -> list[dict[str, str]] | list[list[str]]:
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise WorkspaceError(f"unable to read CSV artifact {path}: {exc}") from exc

        if not raw.strip():
            return []

        buffer = StringIO(raw)
        sample = raw.splitlines()
        if sample and "," in sample[0]:
            reader = csv.DictReader(buffer)
            return [dict(row) for row in reader]
        buffer.seek(0)
        return list(csv.reader(buffer))

    def _write_binary(self, path: Path, data: Any) -> None:
        if isinstance(data, (bytes, bytearray)):
            payload = bytes(data)
        elif isinstance(data, Path):
            payload = data.read_bytes()
        else:
            raise WorkspaceError(
                f"binary artifact write expects bytes, bytearray, or Path; "
                f"got {type(data).__name__}"
            )
        ArtifactCodec.write_bytes_atomic(path, payload)

    def _read_binary(self, path: Path) -> bytes:
        try:
            return path.read_bytes()
        except OSError as exc:
            raise WorkspaceError(f"unable to read binary artifact {path}: {exc}") from exc

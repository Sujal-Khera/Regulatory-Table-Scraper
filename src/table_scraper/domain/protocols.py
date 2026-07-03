"""Domain protocols — structural typing contracts for adapters and plugins.

Protocols define the boundaries between the pure domain layer and
infrastructure implementations. They use ``typing.Protocol`` with
``@runtime_checkable`` where isinstance checks are useful in tests.

No protocol in this module performs I/O directly; concrete implementations
live in ``adapters/``, ``storage/``, ``parsing/``, ``patterns/``, and
``validation/``.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from table_scraper.domain.enums import ArtifactKind, TablePattern
from table_scraper.domain.models import (
    ExcelWorkbook,
    NormalizedTable,
    PageIndex,
    ParseResult,
    PatternClassification,
    StateBlock,
    ValidationReport,
)


@runtime_checkable
class PdfReader(Protocol):
    """Thin wrapper around a PDF library for text and table extraction.

    Implementations (e.g. ``adapters/pdf_reader.py``) isolate pdfplumber or
    future OCR backends from pipeline logic. Callers use this as a context
    manager to guarantee resource cleanup.

    Canonical page numbering is **1-based** throughout the pipeline.
    """

    @property
    def page_count(self) -> int:
        """Return total number of pages in the opened PDF."""
        ...

    def extract_text(self, page: int) -> str:
        """Extract plain text from a 1-based PDF page index.

        Args:
            page: 1-based page number in ``[1, page_count]``.

        Returns:
            Extracted plain text, or ``""`` for image-only pages.
        """
        ...

    def extract_tables(self, page: int) -> list[list[list[str]]]:
        """Extract all tables from a page as row grids of string cells.

        Args:
            page: 1-based page number.

        Returns:
            List of tables; each table is ``list[list[str]]``. Adapters must
            convert library-native cell types to strings at this boundary.
        """
        ...

    def __enter__(self) -> PdfReader:
        """Open the PDF resource and return self."""
        ...

    def __exit__(self, *args: Any) -> None:
        """Close the PDF resource and release handles."""
        ...


@runtime_checkable
class ParserPlugin(Protocol):
    """Semantic parser plugin registered by pattern or parameter ID.

    Each plugin converts a :class:`~table_scraper.domain.models.NormalizedTable`
    (and optional :class:`~table_scraper.domain.models.StateBlock` list) into
    a :class:`~table_scraper.domain.models.ParseResult`. Plugins are discovered
    via ``config/parsers/registry.yaml`` and must not perform PDF I/O.
    """

    @property
    def parser_id(self) -> str:
        """Unique parser plugin identifier (e.g. ``narrative_v1``)."""
        ...

    @property
    def pattern(self) -> TablePattern:
        """Primary :class:`~TablePattern` this plugin handles."""
        ...

    def parse(
        self,
        table: NormalizedTable,
        blocks: list[StateBlock] | None,
        config: Any,
    ) -> ParseResult:
        """Parse a normalized table into canonical records.

        Args:
            table: Cleaned table grid ready for semantic parsing.
            blocks: Optional state blocks for block-level parser families;
                ``None`` when segmentation was not run or not applicable.
            config: Parameter-specific configuration object loaded from YAML.

        Returns:
            Complete :class:`ParseResult` including records and parse metadata.
        """
        ...


@runtime_checkable
class PatternClassifier(Protocol):
    """Scores normalized tables against configurable pattern signatures.

    Implementations live in ``patterns/classifier.py``. The classifier must
    not invoke parsers — it only returns a :class:`PatternClassification`
    for routing decisions.
    """

    def classify(
        self,
        table: NormalizedTable,
        config: Any,
    ) -> PatternClassification:
        """Return pattern classification with confidence and feature signals.

        Args:
            table: Normalized table to classify.
            config: Pattern signature configuration and thresholds.

        Returns:
            :class:`PatternClassification` including pattern, confidence,
            and optional runner-up for low-confidence confirmation flows.
        """
        ...


@runtime_checkable
class ArtifactStore(Protocol):
    """Read/write persisted workspace artifacts.

    Implementations in ``storage/artifact_store.py`` map :class:`ArtifactKind`
    values to canonical paths under ``workspaces/{workspace_id}/`` and handle
    JSON serialization of domain models.
    """

    def read(self, kind: ArtifactKind, parameter_id: str | None = None) -> Any:
        """Load a typed artifact from the workspace.

        Args:
            kind: Artifact type determining path resolution.
            parameter_id: Parameter scope for per-parameter artifacts; ``None``
                for workspace-global artifacts (e.g. page index, manifest).

        Returns:
            Deserialized domain object or primitive matching ``kind``.
        """
        ...

    def write(
        self,
        kind: ArtifactKind,
        data: Any,
        parameter_id: str | None = None,
    ) -> str:
        """Persist an artifact to the workspace.

        Args:
            kind: Artifact type determining path resolution.
            data: Domain object or serializable payload to persist.
            parameter_id: Parameter scope for per-parameter artifacts.

        Returns:
            Written file path relative to workspace root.
        """
        ...


@runtime_checkable
class ExcelExporter(Protocol):
    """Multi-sheet Excel warehouse export.

    Implementations in ``export/excel_exporter.py`` write formatted workbooks
    via the Excel adapter and return an :class:`ExcelWorkbook` metadata
    envelope. Export consumes parsed records only — never PDF or raw tables.
    """

    def export(
        self,
        sheets: dict[str, Any],
        path: str,
        format_config: dict[str, Any],
    ) -> ExcelWorkbook:
        """Write sheets to an Excel file and return metadata.

        Args:
            sheets: Mapping of sheet name → tabular data (typically DataFrames
                built by ``export/dataframe_builder.py``).
            path: Output ``.xlsx`` file path.
            format_config: Formatting spec (freeze panes, column widths, etc.).

        Returns:
            :class:`ExcelWorkbook` metadata envelope for manifest tracking.
        """
        ...


@runtime_checkable
class PageSearchIndex(Protocol):
    """FTS5-backed full-text search over a :class:`PageIndex`.

    Optional infrastructure written during indexing and read during discovery
    for phrase-based offset calibration and query resolution.
    """

    def query(self, text: str, limit: int = 20) -> list[int]:
        """Return matching 1-based PDF page numbers ranked by relevance.

        Args:
            text: Search query string.
            limit: Maximum number of page numbers to return.

        Returns:
            Sorted or relevance-ordered list of ``pdf_page`` values.
        """
        ...

    def build(self, page_index: PageIndex) -> None:
        """Build or rebuild the search index from a :class:`PageIndex`.

        Args:
            page_index: Complete page index to index for FTS queries.
        """
        ...


@runtime_checkable
class ValidationRule(Protocol):
    """Pluggable post-parse validation check.

    Individual rules are composed by ``validation/runner.py`` into a full
    :class:`ValidationReport`. Each rule inspects a :class:`ParseResult`
    against parameter-specific thresholds from YAML configuration.
    """

    @property
    def rule_id(self) -> str:
        """Unique rule identifier matching configuration keys."""
        ...

    def check(self, result: ParseResult, config: Any) -> ValidationReport:
        """Run this validation rule against a parse result.

        Args:
            result: Complete parse output to validate.
            config: Parameter-specific validation thresholds and schema.

        Returns:
            :class:`ValidationReport` contribution (may be partial; the runner
            merges checks from all rules into one report).
        """
        ...

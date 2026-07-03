"""Domain data models — canonical contracts from data_contracts.md.

Every dataclass in this module is a pure value object with no I/O or pipeline
logic. Cross-stage communication uses only these types (plus enums and protocols).

Simple field invariants are enforced in ``__post_init__`` via ``ValueError``;
business-rule failures at runtime use the exception hierarchy in ``errors.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from table_scraper.domain.enums import (
    BlockParserHint,
    DiscoverySource,
    ExportMode,
    PageRangeSource,
    ParseStatus,
    ParserFamily,
    RowLabel,
    RoutingSource,
    SelectionMode,
    StageStatus,
    TablePattern,
    TitleSource,
    ValidationSeverity,
)

Scalar = str | int | float | bool

_CONTENT_HASH_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_PARAMETER_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_TABLE_NUMBER_PATTERN = re.compile(r"^\d+(?:\([a-zA-Z]\))?$")


def _max_row_width(rows: list[list[str]]) -> int:
    """Return the widest row length in a cell grid."""
    if not rows:
        return 0
    return max(len(row) for row in rows)


def _assert_all_string_cells(rows: list[list[str]], context: str) -> None:
    """Ensure every cell in a table grid is a string."""
    for row_index, row in enumerate(rows):
        for col_index, cell in enumerate(row):
            if not isinstance(cell, str):
                raise ValueError(
                    f"{context}: cell at row {row_index}, col {col_index} "
                    f"must be str, got {type(cell).__name__}"
                )


def _assert_contiguous_pages(pages: list[int], *, label: str) -> None:
    """Ensure page numbers are contiguous starting at 1 with no gaps or duplicates."""
    if not pages:
        return
    expected = list(range(1, len(pages) + 1))
    if pages != expected:
        raise ValueError(
            f"{label}: pages must be contiguous 1..N with no gaps or duplicates, "
            f"got {pages}"
        )


@dataclass
class PDFDocument:
    """Immutable reference to an input PDF for one pipeline session.

    Represents identity and metadata only; page content is read on demand via
    the :class:`~table_scraper.domain.protocols.PdfReader` adapter.

    Attributes:
        path: Absolute or workspace-relative path to the PDF file.
        content_hash: SHA-256 hex digest of file bytes (64 characters).
        page_count: Total pages in the document (≥ 1).
        file_size_bytes: File size in bytes (≥ 0).
        profile_id: Active PDF profile identifier (e.g. ``cerc_ursi_v1``).
        title: PDF metadata title, if available.
        created_at: PDF metadata creation date, if available.
        opened_at: ISO 8601 UTC timestamp when the pipeline opened the document.
        filename: Basename of the file for display purposes.
    """

    path: str
    content_hash: str
    page_count: int
    file_size_bytes: int
    profile_id: str
    title: str | None = None
    created_at: str | None = None
    opened_at: str | None = None
    filename: str | None = None

    def __post_init__(self) -> None:
        if not self.path.strip():
            raise ValueError("path must be non-empty")
        if not _CONTENT_HASH_PATTERN.match(self.content_hash):
            raise ValueError("content_hash must be a 64-character hexadecimal string")
        if self.page_count < 1:
            raise ValueError("page_count must be >= 1")
        if self.file_size_bytes < 0:
            raise ValueError("file_size_bytes must be >= 0")
        if not self.profile_id.strip():
            raise ValueError("profile_id must be non-empty")


@dataclass
class TableTitle:
    """Structured regulatory table heading anchor.

    Captures a detected or TOC-parsed table heading such as
    ``Table-5(a): Cross Subsidy Surcharge`` for section boundary detection
    and parameter matching.

    Attributes:
        raw_text: Exact matched substring from source text.
        table_number: Normalized table ID (e.g. ``5``, ``5(a)``, ``3``).
        title_text: Human-readable title after the table number prefix.
        pdf_page: 1-based PDF page where the title was found (when standalone).
        printed_page: Printed page number from a TOC entry (required when
            ``source`` is :attr:`~TitleSource.TOC`).
        source: Origin mechanism (:attr:`~TitleSource.PAGE_SCAN`,
            :attr:`~TitleSource.TOC`, or :attr:`~TitleSource.FTS`).
        match_start: Character offset of the match start in page text.
        match_end: Character offset of the match end in page text.
        confidence: Match quality score in ``[0.0, 1.0]``.
        parameter_id: Resolved parameter identifier if already mapped.
    """

    raw_text: str
    table_number: str
    title_text: str
    pdf_page: int | None = None
    printed_page: int | None = None
    source: TitleSource | None = None
    match_start: int | None = None
    match_end: int | None = None
    confidence: float | None = None
    parameter_id: str | None = None

    def __post_init__(self) -> None:
        if not _TABLE_NUMBER_PATTERN.match(self.table_number):
            raise ValueError(
                "table_number must match pattern ^\\d+(?:\\([a-zA-Z]\\))?$ "
                f"after normalization, got {self.table_number!r}"
            )
        if not self.title_text.strip():
            raise ValueError("title_text must be non-empty after trim")
        if self.table_number not in self.raw_text:
            raise ValueError("raw_text must contain table_number")
        if self.title_text not in self.raw_text:
            raise ValueError("raw_text must contain title_text")
        if self.source is TitleSource.TOC and self.printed_page is None:
            raise ValueError("printed_page is required when source is 'toc'")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0.0, 1.0]")
        if self.pdf_page is not None and self.pdf_page < 1:
            raise ValueError("pdf_page must be >= 1 when set")
        if self.printed_page is not None and self.printed_page < 1:
            raise ValueError("printed_page must be >= 1 when set")


@dataclass
class PageRecord:
    """Indexed snapshot of one PDF page.

    Produced during the index stage; consumed by discovery, FTS search, and
    CLI page previews.

    Attributes:
        pdf_page: 1-based PDF page index.
        page_text: Full extracted plain text (may be empty for image-only pages).
        table_titles: Zero or more detected table headings on this page.
        contains_table: Whether any table geometry was detected on the page.
        text_length: Character count of ``page_text`` (must equal ``len(page_text)``).
        printed_page: Printed page number from footer/header, if detectable.
        table_count: Number of tables detected on the page.
        language_hint: Language hint (e.g. ``en``, ``hi``, ``mixed``).
        extraction_warnings: Non-fatal indexing issues for this page.
        indexed_at: ISO 8601 UTC timestamp when this record was created.
    """

    pdf_page: int
    page_text: str
    table_titles: list[TableTitle]
    contains_table: bool
    text_length: int
    printed_page: int | None = None
    table_count: int | None = None
    language_hint: str | None = None
    extraction_warnings: list[str] = field(default_factory=list)
    indexed_at: str | None = None

    def __post_init__(self) -> None:
        if self.pdf_page < 1:
            raise ValueError("pdf_page must be >= 1")
        if self.text_length != len(self.page_text):
            raise ValueError(
                f"text_length ({self.text_length}) must equal len(page_text) "
                f"({len(self.page_text)})"
            )
        if self.table_count is not None and self.table_count > 0 and not self.contains_table:
            raise ValueError("contains_table must be true when table_count > 0")
        if self.table_count is not None and self.table_count < 0:
            raise ValueError("table_count must be >= 0 when set")
        if self.printed_page is not None and self.printed_page < 1:
            raise ValueError("printed_page must be >= 1 when set")


@dataclass
class PageIndex:
    """Aggregate index of all pages for one PDF workspace.

    Primary discovery input and backing data for the FTS5 page search index.

    Attributes:
        schema_version: Semver contract version for persisted JSON.
        workspace_id: PDF content hash prefix (first 16 hex chars).
        pdf_hash: Full content hash matching :attr:`PDFDocument.content_hash`.
        page_count: Total number of pages indexed.
        pages: One :class:`PageRecord` per page, ordered by ``pdf_page``.
        indexed_at: ISO 8601 UTC timestamp when the index was built.
        index_version: Monotonic rebuild counter for cache invalidation.
        pages_with_titles: Count of pages having at least one table title.
        pages_with_tables: Count of pages with ``contains_table == true``.
        title_anchor_pages: Sorted list of ``pdf_page`` values anchoring sections.
        build_duration_ms: Indexing duration in milliseconds.
        config_snapshot_hash: Hash of discovery regex config used for this build.
    """

    schema_version: str
    workspace_id: str
    pdf_hash: str
    page_count: int
    pages: list[PageRecord]
    indexed_at: str
    index_version: int
    pages_with_titles: int | None = None
    pages_with_tables: int | None = None
    title_anchor_pages: list[int] = field(default_factory=list)
    build_duration_ms: int | None = None
    config_snapshot_hash: str | None = None

    def __post_init__(self) -> None:
        if self.page_count < 1:
            raise ValueError("page_count must be >= 1")
        if len(self.pages) != self.page_count:
            raise ValueError(
                f"len(pages) ({len(self.pages)}) must equal page_count ({self.page_count})"
            )
        page_numbers = [record.pdf_page for record in self.pages]
        _assert_contiguous_pages(page_numbers, label="PageIndex.pages")
        if not _CONTENT_HASH_PATTERN.match(self.pdf_hash):
            raise ValueError("pdf_hash must be a 64-character hexadecimal string")
        if self.index_version < 1:
            raise ValueError("index_version must be >= 1")
        if self.title_anchor_pages != sorted(set(self.title_anchor_pages)):
            raise ValueError("title_anchor_pages must be sorted with no duplicates")


@dataclass
class PageRange:
    """Inclusive page span for extraction of one parameter.

    Carries provenance so suggested versus user-confirmed ranges remain auditable.

    Attributes:
        start_page: First PDF page (inclusive, 1-based).
        end_page: Last PDF page (inclusive, 1-based).
        source: How this range was determined.
        parameter_id: Parameter this range applies to, if known.
        page_list: Explicit page list for rare non-contiguous extraction.
        boundary_rule: Human-readable rule used to compute the end boundary.
        anchor_start_title: Table title that opened the range.
        anchor_end_title: Next table title that closed the range.
        confirmed_at: ISO 8601 UTC timestamp when the user approved the range.
        confirmed_by: Confirmation channel (``cli``, ``api``, or ``auto``).
    """

    start_page: int
    end_page: int
    source: PageRangeSource
    parameter_id: str | None = None
    page_list: list[int] | None = None
    boundary_rule: str | None = None
    anchor_start_title: TableTitle | None = None
    anchor_end_title: TableTitle | None = None
    confirmed_at: str | None = None
    confirmed_by: str | None = None

    def __post_init__(self) -> None:
        if self.start_page < 1:
            raise ValueError("start_page must be >= 1")
        if self.end_page < self.start_page:
            raise ValueError("end_page must be >= start_page")
        if self.source is PageRangeSource.USER_CONFIRMED and not self.confirmed_at:
            raise ValueError("confirmed_at is required when source is 'user_confirmed'")
        if self.page_list is not None:
            if len(self.page_list) != len(set(self.page_list)):
                raise ValueError("page_list must not contain duplicates")
            if self.page_list != sorted(self.page_list):
                raise ValueError("page_list must be sorted ascending")


@dataclass
class ParameterDefinition:
    """One discoverable regulatory parameter.

    Bundles identity, display metadata, suggested location, and parsing hints
    produced during the discovery stage.

    Attributes:
        parameter_id: Stable snake_case key (e.g. ``banking_charges``).
        display_name: User-facing label shown in the CLI.
        table_title: Primary anchor :class:`TableTitle` for this parameter.
        supported: Whether v1 can extract and parse this parameter.
        suggested_range: Auto-computed inclusive PDF page span.
        toc_start_page: Printed TOC start page before offset calibration.
        pdf_start_page: Calibrated PDF start page (redundant with range when set).
        parser_id: Registry parser identifier (e.g. ``narrative_v1``).
        parser_family: Recommended :class:`~ParserFamily` implementation.
        pattern_override: Force a :class:`~TablePattern` when classifier is uncertain.
        calibration_phrase: Unique phrase for TOC→PDF offset calibration.
        aliases: Search synonyms for query resolution.
        parent_parameter_id: Parent parameter for nested sub-tables.
        discovery_source: Mechanism that surfaced this parameter.
        notes: Human-readable notes (e.g. unsupported reason).
    """

    parameter_id: str
    display_name: str
    table_title: TableTitle
    supported: bool
    suggested_range: PageRange
    toc_start_page: int | None = None
    pdf_start_page: int | None = None
    parser_id: str | None = None
    parser_family: ParserFamily | None = None
    pattern_override: TablePattern | None = None
    calibration_phrase: str | None = None
    aliases: list[str] = field(default_factory=list)
    parent_parameter_id: str | None = None
    discovery_source: DiscoverySource | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        if not _PARAMETER_ID_PATTERN.match(self.parameter_id):
            raise ValueError(
                "parameter_id must match ^[a-z][a-z0-9_]*$, "
                f"got {self.parameter_id!r}"
            )
        if not self.display_name.strip():
            raise ValueError("display_name must be non-empty")


@dataclass
class ParameterCatalog:
    """Complete list of parameters discovered for one PDF.

    Attributes:
        schema_version: Semver contract version for persisted JSON.
        workspace_id: PDF workspace identifier.
        generated_at: ISO 8601 UTC build timestamp.
        parameters: All discovered parameters, sorted by ``suggested_range.start_page``.
        parameter_count: ``len(parameters)`` — denormalized for quick inspection.
        supported_count: Count of parameters where ``supported == true``.
        toc_page_offset: Calibrated ``pdf_page - printed_page`` delta.
        offset_calibration_method: Method used (e.g. ``phrase_search``, ``manual``).
        offset_calibration_phrases: Audit trail of calibration phrase matches.
        discovery_sources: Mechanisms that contributed to this catalog.
        filtered_spurious: Rejected TOC matches with rejection reasons.
        input_index_version: :attr:`PageIndex.index_version` used to build this catalog.
    """

    schema_version: str
    workspace_id: str
    generated_at: str
    parameters: list[ParameterDefinition]
    parameter_count: int
    supported_count: int
    toc_page_offset: int | None = None
    offset_calibration_method: str | None = None
    offset_calibration_phrases: list[dict[str, Any]] = field(default_factory=list)
    discovery_sources: list[str] = field(default_factory=list)
    filtered_spurious: list[dict[str, Any]] = field(default_factory=list)
    input_index_version: int | None = None

    def __post_init__(self) -> None:
        if self.parameter_count != len(self.parameters):
            raise ValueError(
                f"parameter_count ({self.parameter_count}) must equal "
                f"len(parameters) ({len(self.parameters)})"
            )
        if self.supported_count > self.parameter_count:
            raise ValueError("supported_count must be <= parameter_count")
        if self.supported_count < 0:
            raise ValueError("supported_count must be >= 0")

        seen_ids: set[str] = set()
        previous_start = 0
        for param in self.parameters:
            if param.parameter_id in seen_ids:
                raise ValueError(f"duplicate parameter_id: {param.parameter_id!r}")
            seen_ids.add(param.parameter_id)
            start = param.suggested_range.start_page
            if start < previous_start:
                raise ValueError(
                    "parameters must be sorted ascending by suggested_range.start_page"
                )
            previous_start = start

        actual_supported = sum(1 for param in self.parameters if param.supported)
        if self.supported_count != actual_supported:
            raise ValueError(
                f"supported_count ({self.supported_count}) must equal count of "
                f"supported parameters ({actual_supported})"
            )


@dataclass
class UserSelection:
    """User intent for one pipeline run.

    Captures selected parameters, confirmed page ranges, optional pattern
    overrides, and export preferences. Persisted as a session checkpoint.

    Attributes:
        selection_id: UUID identifying this selection event.
        created_at: ISO 8601 UTC timestamp.
        selection_mode: How parameters were chosen.
        parameter_ids: Parameters to extract, parse, and export.
        confirmed_ranges: One confirmed :class:`PageRange` per ``parameter_id``.
        query_text: Natural-language query when mode is :attr:`~SelectionMode.QUERY`.
        query_resolution: Query match metadata (parameter, score, pages).
        confirmed_patterns: User-confirmed :class:`~TablePattern` per parameter.
        export_mode: Excel packaging preference.
        export_path: User-specified output path override.
        skip_validation: When ``True``, bypass the validation gate.
        force_reextract: When ``True``, bypass extraction cache.
    """

    selection_id: str
    created_at: str
    selection_mode: SelectionMode
    parameter_ids: list[str]
    confirmed_ranges: dict[str, PageRange]
    query_text: str | None = None
    query_resolution: dict[str, Any] | None = None
    confirmed_patterns: dict[str, TablePattern] | None = None
    export_mode: ExportMode | None = None
    export_path: str | None = None
    skip_validation: bool = False
    force_reextract: bool = False

    def __post_init__(self) -> None:
        if not self.selection_id.strip():
            raise ValueError("selection_id must be non-empty")
        if self.selection_mode is SelectionMode.QUERY and not self.query_text:
            raise ValueError("query_text is required when selection_mode is 'query'")
        missing_ranges = set(self.parameter_ids) - set(self.confirmed_ranges)
        if missing_ranges:
            raise ValueError(
                f"confirmed_ranges missing entries for: {sorted(missing_ranges)!r}"
            )
        extra_ranges = set(self.confirmed_ranges) - set(self.parameter_ids)
        if extra_ranges:
            raise ValueError(
                f"confirmed_ranges contains unknown parameter_ids: {sorted(extra_ranges)!r}"
            )


@dataclass
class RawTable:
    """Unprocessed table data from a single PDF page.

    Preserves pdfplumber output faithfully for debugging and merge input.

    Attributes:
        parameter_id: Owning parameter identifier.
        pdf_page: Source 1-based PDF page.
        rows: Selected primary table cells (all strings, no null cells).
        row_count: ``len(rows)``.
        column_count: Maximum row width (≥ 1 when rows is non-empty).
        selected_table_index: 0-based index of the chosen candidate table.
        candidate_tables: Metadata for all tables detected on the page.
        selection_heuristic: Heuristic name (e.g. ``largest_area``).
        bbox: Table bounding box ``[x0, y0, x1, y1]`` when available.
        extracted_at: ISO 8601 UTC extraction timestamp.
        extraction_warnings: Non-fatal extraction notes.
        page_range_id: Hash of the confirmed range used as a cache key.
    """

    parameter_id: str
    pdf_page: int
    rows: list[list[str]]
    row_count: int
    column_count: int
    selected_table_index: int
    candidate_tables: list[dict[str, Any]] = field(default_factory=list)
    selection_heuristic: str | None = None
    bbox: list[float] | None = None
    extracted_at: str | None = None
    extraction_warnings: list[str] = field(default_factory=list)
    page_range_id: str | None = None

    def __post_init__(self) -> None:
        if self.pdf_page < 1:
            raise ValueError("pdf_page must be >= 1")
        if self.row_count != len(self.rows):
            raise ValueError(
                f"row_count ({self.row_count}) must equal len(rows) ({len(self.rows)})"
            )
        _assert_all_string_cells(self.rows, "RawTable.rows")
        expected_cols = _max_row_width(self.rows)
        if self.rows and self.column_count != expected_cols:
            raise ValueError(
                f"column_count ({self.column_count}) must equal max row width "
                f"({expected_cols})"
            )
        if self.rows and self.column_count < 1:
            raise ValueError("column_count must be >= 1 when rows is non-empty")
        if not self.rows and not self.extraction_warnings:
            raise ValueError("extraction_warnings must be non-empty when rows is empty")
        if self.selected_table_index < 0:
            raise ValueError("selected_table_index must be >= 0")


@dataclass
class MergedTable:
    """Multi-page concatenation of :class:`RawTable` instances.

    Input to normalization after primary-table selection and repeated-header
    removal across pages.

    Attributes:
        parameter_id: Owning parameter identifier.
        source_pages: PDF pages merged in ascending order (no duplicates).
        rows: Concatenated cell grid after header stripping.
        row_count: Total row count.
        column_count: Normalized column width across all rows.
        headers_stripped_count: Number of repeated header blocks removed.
        header_signature: Detected header row text for audit.
        merge_log: Per-page merge audit entries.
        page_range: :class:`PageRange` that produced this merge.
        merged_at: ISO 8601 UTC merge timestamp.
        input_raw_table_hashes: Per-page :class:`RawTable` content hashes.
    """

    parameter_id: str
    source_pages: list[int]
    rows: list[list[str]]
    row_count: int
    column_count: int
    headers_stripped_count: int
    header_signature: list[str] = field(default_factory=list)
    merge_log: list[dict[str, Any]] = field(default_factory=list)
    page_range: PageRange | None = None
    merged_at: str | None = None
    input_raw_table_hashes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.source_pages != sorted(set(self.source_pages)):
            raise ValueError("source_pages must be sorted ascending with no duplicates")
        if self.row_count != len(self.rows):
            raise ValueError(
                f"row_count ({self.row_count}) must equal len(rows) ({len(self.rows)})"
            )
        _assert_all_string_cells(self.rows, "MergedTable.rows")
        if self.rows:
            widths = {len(row) for row in self.rows}
            if len(widths) > 1:
                raise ValueError(
                    "all rows must have equal width (pad with empty strings)"
                )
            if self.column_count != _max_row_width(self.rows):
                raise ValueError("column_count must match row width")
        if self.headers_stripped_count < 0:
            raise ValueError("headers_stripped_count must be >= 0")


@dataclass
class NormalizedTable:
    """Structurally and lexically cleaned table ready for parsing.

    Produced after geometry cleanup, text normalization, and optional hierarchy
    propagation.

    Attributes:
        parameter_id: Owning parameter identifier.
        rows: Cleaned cell grid with no completely empty rows or columns.
        row_count: Row count.
        column_count: Column count.
        normalization_steps: Ordered list of steps applied (non-empty).
        row_labels: Optional per-row :class:`~RowLabel` classifications.
        source_merged_table_hash: Lineage hash from the source :class:`MergedTable`.
        normalized_at: ISO 8601 UTC normalization timestamp.
        cleanup_stats: Counts of removed empty rows/cols and CID tokens.
        wide_format: Hint that wide-to-long parsing may be required.
    """

    parameter_id: str
    rows: list[list[str]]
    row_count: int
    column_count: int
    normalization_steps: list[str]
    row_labels: list[RowLabel] | None = None
    source_merged_table_hash: str | None = None
    normalized_at: str | None = None
    cleanup_stats: dict[str, Any] | None = None
    wide_format: bool | None = None

    def __post_init__(self) -> None:
        if not self.normalization_steps:
            raise ValueError("normalization_steps must be non-empty")
        if self.row_count != len(self.rows):
            raise ValueError(
                f"row_count ({self.row_count}) must equal len(rows) ({len(self.rows)})"
            )
        _assert_all_string_cells(self.rows, "NormalizedTable.rows")
        if self.row_labels is not None and len(self.row_labels) != self.row_count:
            raise ValueError("len(row_labels) must equal row_count when row_labels is set")


@dataclass
class PatternClassification:
    """Structural pattern assignment for parser routing.

    Attributes:
        parameter_id: Owning parameter identifier.
        pattern: Assigned :class:`~TablePattern`.
        confidence: Classifier confidence in ``[0.0, 1.0]``.
        classified_at: ISO 8601 UTC classification timestamp.
        routing_source: How the route was chosen.
        parser_family: Recommended :class:`~ParserFamily`.
        parser_id: Specific parser plugin to invoke.
        signals: Feature score map from the classifier.
        runner_up_pattern: Second-best pattern candidate.
        runner_up_confidence: Second-best confidence score.
        requires_user_confirmation: ``True`` when confidence is below threshold.
        input_table_hash: Hash of the source :class:`NormalizedTable`.
    """

    parameter_id: str
    pattern: TablePattern
    confidence: float
    classified_at: str
    routing_source: RoutingSource
    parser_family: ParserFamily | None = None
    parser_id: str | None = None
    signals: dict[str, float] = field(default_factory=dict)
    runner_up_pattern: TablePattern | None = None
    runner_up_confidence: float | None = None
    requires_user_confirmation: bool | None = None
    input_table_hash: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0.0, 1.0]")
        if self.runner_up_confidence is not None and not (
            0.0 <= self.runner_up_confidence <= 1.0
        ):
            raise ValueError("runner_up_confidence must be in [0.0, 1.0]")
        if self.pattern is TablePattern.UNKNOWN and self.requires_user_confirmation is not True:
            raise ValueError(
                "requires_user_confirmation must be true when pattern is 'unknown'"
            )


@dataclass
class StateBlock:
    """Segment of a normalized matrix table belonging to one Indian state/UT.

    Enables state-scoped parsing for block-level parser families.

    Attributes:
        block_id: Stable identifier (e.g. ``andhra_pradesh_50_12``).
        parameter_id: Owning parameter identifier.
        state: Canonical state or UT name.
        start_row: 0-based inclusive start index into :class:`NormalizedTable.rows`.
        end_row: 0-based inclusive end index.
        rows: Row slice for this block.
        start_page: 1-based PDF page where the block begins.
        end_page: 1-based PDF page where the block ends.
        year_label: Detected financial year (e.g. ``2023-24``).
        block_parser_hint: Suggested block-level parser type.
        utility_columns: Detected utility column headers.
        sections: HT/LT/EHT section names within the block.
        row_count: ``len(rows)`` when denormalized.
    """

    block_id: str
    parameter_id: str
    state: str
    start_row: int
    end_row: int
    rows: list[list[str]]
    start_page: int
    end_page: int | None = None
    year_label: str | None = None
    block_parser_hint: BlockParserHint | None = None
    utility_columns: list[str] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)
    row_count: int | None = None

    def __post_init__(self) -> None:
        if not self.block_id.strip():
            raise ValueError("block_id must be non-empty")
        if not self.state.strip():
            raise ValueError("state must be non-empty")
        if self.start_row < 0 or self.end_row < 0:
            raise ValueError("start_row and end_row must be >= 0")
        if self.start_row > self.end_row:
            raise ValueError("start_row must be <= end_row")
        expected_row_count = self.end_row - self.start_row + 1
        if len(self.rows) != expected_row_count:
            raise ValueError(
                f"len(rows) ({len(self.rows)}) must equal "
                f"end_row - start_row + 1 ({expected_row_count})"
            )
        _assert_all_string_cells(self.rows, "StateBlock.rows")
        if self.start_page < 1:
            raise ValueError("start_page must be >= 1")
        if self.end_page is not None and self.end_page < 1:
            raise ValueError("end_page must be >= 1 when set")
        if self.row_count is not None and self.row_count != len(self.rows):
            raise ValueError("row_count must equal len(rows) when set")


@dataclass
class ParsedRecord:
    """One canonical semantic output row for warehouse storage.

    Uniform unit emitted by parser plugins regardless of source table shape.
    Column contracts live in parameter YAML; validation enforces required keys.

    Attributes:
        record_id: UUID or deterministic hash unique within the parse run.
        parameter_id: Source parameter identifier.
        fields: Schema-defined payload mapping column names to scalar values.
        source_pages: PDF pages contributing to this record.
        source_rows: Row indices in the :class:`NormalizedTable`.
        parser_id: Parser plugin that emitted this record.
        parser_version: Plugin version string.
        confidence: Per-record parse confidence in ``[0.0, 1.0]``.
        warnings: Non-fatal parse notes for this record.
        provenance: Trace keys (``block_id``, ``state``, ``discom``, etc.).
    """

    record_id: str
    parameter_id: str
    fields: dict[str, Scalar]
    source_pages: list[int] = field(default_factory=list)
    source_rows: list[int] = field(default_factory=list)
    parser_id: str | None = None
    parser_version: str | None = None
    confidence: float | None = None
    warnings: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.record_id.strip():
            raise ValueError("record_id must be non-empty")
        if not _PARAMETER_ID_PATTERN.match(self.parameter_id):
            raise ValueError(
                "parameter_id must match ^[a-z][a-z0-9_]*$, "
                f"got {self.parameter_id!r}"
            )
        for key, value in self.fields.items():
            if not isinstance(value, (str, int, float, bool)):
                raise ValueError(
                    f"fields[{key!r}] must be a scalar (str, int, float, bool), "
                    f"got {type(value).__name__}"
                )
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0.0, 1.0]")


@dataclass
class ParseResult:
    """Complete output of parsing one parameter.

    Attributes:
        parameter_id: Parsed parameter identifier.
        records: All emitted :class:`ParsedRecord` instances.
        record_count: ``len(records)``.
        parser_id: Parser plugin used.
        pattern: :class:`~TablePattern` that routed the parse.
        parsed_at: ISO 8601 UTC parse timestamp.
        status: Outcome :class:`~ParseStatus`.
        parser_family: Parser family name.
        parse_metadata: Row/block counts and duration metrics.
        classification: Copy of :class:`PatternClassification` for audit.
        input_table_hash: Hash of the source :class:`NormalizedTable`.
        state_blocks_used: Block IDs when block parsers ran.
        errors: Fatal parse issues as ``{code, message, row}`` objects.
        warnings: Aggregate non-fatal warnings.
    """

    parameter_id: str
    records: list[ParsedRecord]
    record_count: int
    parser_id: str
    pattern: TablePattern
    parsed_at: str
    status: ParseStatus
    parser_family: ParserFamily | None = None
    parse_metadata: dict[str, Any] | None = None
    classification: PatternClassification | None = None
    input_table_hash: str | None = None
    state_blocks_used: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.record_count != len(self.records):
            raise ValueError(
                f"record_count ({self.record_count}) must equal "
                f"len(records) ({len(self.records)})"
            )
        for record in self.records:
            if record.parameter_id != self.parameter_id:
                raise ValueError(
                    f"record {record.record_id!r} parameter_id "
                    f"({record.parameter_id!r}) must match parent "
                    f"({self.parameter_id!r})"
                )
        if self.status is ParseStatus.FAILED:
            if self.record_count != 0:
                raise ValueError("record_count must be 0 when status is 'failed'")
            if not self.errors:
                raise ValueError("errors must be non-empty when status is 'failed'")
        if self.status is ParseStatus.SUCCESS and self.errors:
            raise ValueError("errors must be empty when status is 'success'")


@dataclass
class ValidationCheck:
    """Single validation rule outcome within a :class:`ValidationReport`.

    Attributes:
        rule_id: Unique rule identifier from configuration.
        severity: :class:`~ValidationSeverity` level.
        passed: Whether this check passed.
        message: Human-readable outcome message.
        details: Structured detail payload for debugging.
    """

    rule_id: str
    severity: ValidationSeverity
    passed: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise ValueError("rule_id must be non-empty")
        if not self.message.strip():
            raise ValueError("message must be non-empty")


@dataclass
class ValidationReport:
    """Quality gate results after parsing.

    Attributes:
        parameter_id: Validated parameter identifier.
        validated_at: ISO 8601 UTC validation timestamp.
        passed: ``True`` when no blocking errors exist.
        error_count: Count of checks with severity ``error`` that failed.
        warning_count: Count of checks with severity ``warning`` that failed.
        checks: Individual :class:`ValidationCheck` outcomes.
        parse_result_hash: Input lineage hash.
        summary: Aggregate metrics (record count, state coverage, null rates).
        expected_thresholds: Thresholds from parameter YAML.
        export_allowed: Computed export gate decision.
    """

    parameter_id: str
    validated_at: str
    passed: bool
    error_count: int
    warning_count: int
    checks: list[ValidationCheck]
    parse_result_hash: str | None = None
    summary: dict[str, Any] | None = None
    expected_thresholds: dict[str, Any] | None = None
    export_allowed: bool | None = None

    def __post_init__(self) -> None:
        actual_errors = sum(
            1
            for check in self.checks
            if check.severity is ValidationSeverity.ERROR and not check.passed
        )
        actual_warnings = sum(
            1
            for check in self.checks
            if check.severity is ValidationSeverity.WARNING and not check.passed
        )
        if self.error_count != actual_errors:
            raise ValueError(
                f"error_count ({self.error_count}) must match failed error checks "
                f"({actual_errors})"
            )
        if self.warning_count != actual_warnings:
            raise ValueError(
                f"warning_count ({self.warning_count}) must match failed warning checks "
                f"({actual_warnings})"
            )
        has_blocking_failure = any(
            check.severity is ValidationSeverity.ERROR and not check.passed
            for check in self.checks
        )
        if self.passed != (not has_blocking_failure):
            raise ValueError(
                "passed must be true iff no check has severity 'error' and passed false"
            )


@dataclass
class ExcelSheetInfo:
    """Metadata for one sheet in an :class:`ExcelWorkbook`.

    Attributes:
        sheet_name: Unique sheet tab name.
        parameter_id: Parameter whose records populate this sheet.
        row_count: Data row count (excluding header row).
        column_names: Ordered column names matching the parameter schema.
    """

    sheet_name: str
    parameter_id: str
    row_count: int
    column_names: list[str]

    def __post_init__(self) -> None:
        if not self.sheet_name.strip():
            raise ValueError("sheet_name must be non-empty")
        if self.row_count < 0:
            raise ValueError("row_count must be >= 0")


@dataclass
class ExcelWorkbook:
    """Metadata envelope for a formatted Excel warehouse deliverable.

    The binary ``.xlsx`` file lives at ``path``; this object tracks export
    metadata for manifest and audit purposes.

    Attributes:
        workbook_id: UUID for this export.
        path: Output file path.
        created_at: ISO 8601 UTC export timestamp.
        sheets: Per-sheet metadata entries.
        sheet_count: ``len(sheets)``.
        source_workspace_id: PDF workspace that produced the data.
        format_spec: Applied formatting options (freeze panes, column widths).
        validation_summary: Per-parameter pass/fail from validation.
        export_mode: Packaging mode used for this export.
        file_size_bytes: Output file size in bytes.
    """

    workbook_id: str
    path: str
    created_at: str
    sheets: list[ExcelSheetInfo]
    sheet_count: int
    source_workspace_id: str
    format_spec: dict[str, Any] | None = None
    validation_summary: dict[str, bool] | None = None
    export_mode: ExportMode | None = None
    file_size_bytes: int | None = None

    def __post_init__(self) -> None:
        if self.sheet_count != len(self.sheets):
            raise ValueError(
                f"sheet_count ({self.sheet_count}) must equal len(sheets) ({len(self.sheets)})"
            )
        sheet_names = [sheet.sheet_name for sheet in self.sheets]
        if len(sheet_names) != len(set(sheet_names)):
            raise ValueError("sheet names must be unique")
        if self.file_size_bytes is not None and self.file_size_bytes < 0:
            raise ValueError("file_size_bytes must be >= 0 when set")


@dataclass
class StageRecord:
    """Per-stage completion metadata stored in :class:`WorkspaceManifest`.

    Attributes:
        status: Current :class:`~StageStatus`.
        completed_at: ISO 8601 UTC completion timestamp when finished.
        artifact_paths: Paths written by this stage relative to workspace root.
        input_hash: Hash of direct inputs for stale detection.
    """

    status: StageStatus
    completed_at: str | None = None
    artifact_paths: list[str] = field(default_factory=list)
    input_hash: str | None = None


@dataclass
class WorkspaceManifest:
    """Root index for a PDF-scoped workspace.

    Tracks stage completion, artifact pointers, and cache invalidation state.

    Attributes:
        schema_version: Manifest contract semver.
        workspace_id: PDF content hash prefix (derived from ``pdf.content_hash``).
        pdf: Embedded :class:`PDFDocument` reference.
        created_at: ISO 8601 UTC workspace creation time.
        updated_at: ISO 8601 UTC last mutation time (≥ ``created_at``).
        profile_id: Active PDF profile identifier.
        stages: Map of stage name → :class:`StageRecord`.
        user_selection: Latest :class:`UserSelection` checkpoint.
        parameter_status: Per-parameter downstream completion metadata.
        config_hashes: Hashes of config files used for this workspace.
        invalidated_stages: Stages marked needing rerun.
        version: Monotonic manifest revision counter.
    """

    schema_version: str
    workspace_id: str
    pdf: PDFDocument
    created_at: str
    updated_at: str
    profile_id: str
    stages: dict[str, StageRecord]
    user_selection: UserSelection | None = None
    parameter_status: dict[str, dict[str, Any]] = field(default_factory=dict)
    config_hashes: dict[str, str] = field(default_factory=dict)
    invalidated_stages: list[str] = field(default_factory=list)
    version: int | None = None

    def __post_init__(self) -> None:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must be >= created_at")
        if not self.profile_id.strip():
            raise ValueError("profile_id must be non-empty")


@dataclass
class TocEntry:
    """Raw table-of-contents row extracted from PDF front matter.

    Attributes:
        table_title: Parsed :class:`TableTitle` for this TOC line.
        printed_page: Printed page number from the TOC entry.
        raw_line: Original TOC line text.
    """

    table_title: TableTitle
    printed_page: int
    raw_line: str

    def __post_init__(self) -> None:
        if self.printed_page < 1:
            raise ValueError("printed_page must be >= 1")
        if not self.raw_line.strip():
            raise ValueError("raw_line must be non-empty")


@dataclass
class PageIndexResult:
    """Summary returned after the indexing stage completes.

    Attributes:
        page_index: Built :class:`PageIndex` artifact.
        pages_indexed: Number of pages indexed (equals ``page_index.page_count``).
        pages_with_titles: Count of pages containing at least one table title.
    """

    page_index: PageIndex
    pages_indexed: int
    pages_with_titles: int

    def __post_init__(self) -> None:
        if self.pages_indexed != self.page_index.page_count:
            raise ValueError(
                f"pages_indexed ({self.pages_indexed}) must equal "
                f"page_index.page_count ({self.page_index.page_count})"
            )
        if self.pages_with_titles < 0:
            raise ValueError("pages_with_titles must be >= 0")
        if self.pages_with_titles > self.pages_indexed:
            raise ValueError("pages_with_titles must be <= pages_indexed")


@dataclass
class ExportResult:
    """Summary returned after Excel export completes.

    Attributes:
        workbook: :class:`ExcelWorkbook` metadata for the written file.
    """

    workbook: ExcelWorkbook


@dataclass
class PipelineResult:
    """Summary returned after a full or partial pipeline run completes.

    Attributes:
        manifest: Updated :class:`WorkspaceManifest` after the run.
        parameters_processed: Parameter IDs that completed processing.
        export_results: One :class:`ExportResult` per exported workbook.
    """

    manifest: WorkspaceManifest
    parameters_processed: list[str]
    export_results: list[ExportResult] = field(default_factory=list)

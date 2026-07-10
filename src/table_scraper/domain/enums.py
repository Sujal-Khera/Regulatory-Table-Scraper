"""Domain enumerations for the regulatory PDF table extraction pipeline.

String-valued enums serialize directly to JSON artifact fields defined in
``data_contracts.md``.
"""

from __future__ import annotations

from enum import Enum


class TablePattern(str, Enum):
    """Structural table patterns used for parser routing.

    Values correspond to layout families detected by the pattern classifier
    or forced via parameter configuration overrides.
    """

    SIMPLE_FLAT = "simple_flat"
    """Single-level rows without parent/child hierarchy."""

    HIERARCHICAL_PARENT_CHILD = "hierarchical_parent_child"
    """Rows with explicit master/child relationships (e.g. state → DISCOM)."""

    CONTINUATION_ROWS = "continuation_rows"
    """Data rows that continue a prior master without repeating the label."""

    REPEATED_HEADERS = "repeated_headers"
    """Header blocks that repeat across page or section boundaries."""

    MULTI_PAGE = "multi_page"
    """Table logically spans multiple PDF pages (pre-merge signal)."""

    NUMERIC_MATRIX = "numeric_matrix"
    """Category × utility numeric charge grid."""

    WIDE_TABLE = "wide_table"
    """Many columns representing dimensions that should melt to long format."""

    STATE_BLOCK_MATRIX = "state_block_matrix"
    """State-scoped matrix blocks within one normalized table."""

    SIMPLE_MATRIX = "simple_matrix"
    """Flat category × utility grid without block segmentation."""

    KEY_VALUE = "key_value"
    """Two-column metric tables (label → value)."""

    UNKNOWN = "unknown"
    """Classifier could not assign a pattern; requires user confirmation."""


class ParserFamily(str, Enum):
    """Parser plugin families registered in ``config/parsers/registry.yaml``.

    Each family implements a reusable parsing strategy shared across multiple
    regulatory parameters.
    """

    NARRATIVE = "narrative"
    """Policy/narrative tables (e.g. banking charges)."""

    NUMERIC_MATRIX = "numeric_matrix"
    """Standard numeric charge matrices (e.g. transmission)."""

    WIDE_TO_LONG = "wide_to_long"
    """Wide voltage/category grids melted to long records (e.g. wheeling)."""

    STATE_BLOCK_MATRIX = "state_block_matrix"
    """Block-segmented state matrices (e.g. cross-subsidy open access)."""

    SIMPLE_MATRIX = "simple_matrix"
    """Simple category × utility flat grids."""

    KEY_VALUE = "key_value"
    """Two-column key/value metric extraction."""


class ArtifactKind(str, Enum):
    """Persisted artifact types under a PDF workspace.

    Used by :class:`~table_scraper.domain.protocols.ArtifactStore` to resolve
    canonical paths beneath ``workspaces/{workspace_id}/``.
    """

    MANIFEST = "manifest"
    PAGE_INDEX = "page_index"
    PAGE_INDEX_CSV = "page_index_csv"
    PAGE_INDEX_DB = "page_index_db"
    TOC_RAW = "toc_raw"
    PARAMETER_CATALOG = "parameter_catalog"
    PARAMETER_RANGES = "parameter_ranges"
    CONFIRMED_RANGE = "confirmed_range"
    USER_SELECTION = "user_selection"
    PAGE_PREVIEW = "page_preview"
    RAW_PAGES = "raw_pages"
    RAW_MERGED = "raw_merged"
    NORMALIZED = "normalized"
    STATE_BLOCKS = "state_blocks"
    PATTERN = "pattern"
    RECORDS = "records"
    VALIDATION = "validation"
    EXCEL = "excel"


class SessionStage(str, Enum):
    """Pipeline stage identifiers tracked in :class:`~table_scraper.domain.models.WorkspaceManifest`.

    Stage keys map to artifact directories and idempotency checkpoints.
    """

    INDEX = "index"
    DISCOVER = "discover"
    SELECT = "select"
    EXTRACT = "extract"
    NORMALIZE = "normalize"
    CLASSIFY = "classify"
    PARSE = "parse"
    VALIDATE = "validate"
    EXPORT = "export"


class StageStatus(str, Enum):
    """Completion status for a single pipeline stage in the workspace manifest."""

    PENDING = "pending"
    """Stage has not run or is waiting on upstream inputs."""

    COMPLETE = "complete"
    """Stage finished successfully; artifacts are current."""

    STALE = "stale"
    """Upstream input hash changed; stage must rerun."""

    FAILED = "failed"
    """Stage terminated with an error; downstream stages are blocked."""


class TitleSource(str, Enum):
    """Origin of a detected :class:`~table_scraper.domain.models.TableTitle`."""

    PAGE_SCAN = "page_scan"
    """Matched by regex during full-page text scan."""

    TOC = "toc"
    """Parsed from table-of-contents front matter."""

    FTS = "fts"
    """Discovered via full-text search index query."""


class PageRangeSource(str, Enum):
    """Provenance for how a :class:`~table_scraper.domain.models.PageRange` was computed."""

    ANCHOR_CHAIN = "anchor_chain"
    """Boundaries derived from consecutive table-title anchors in the page index."""

    TOC_NEXT_START = "toc_next_start"
    """End boundary is the next TOC entry start page."""

    USER_CONFIRMED = "user_confirmed"
    """User accepted the suggested range via CLI or API."""

    USER_OVERRIDE = "user_override"
    """User manually edited start/end pages."""

    QUERY_RESOLVED = "query_resolved"
    """Range inferred from a natural-language query match."""


class SelectionMode(str, Enum):
    """How the user chose parameters to process in :class:`~table_scraper.domain.models.UserSelection`."""

    CATALOG = "catalog"
    """Pick from the discovered parameter catalog."""

    QUERY = "query"
    """Resolve parameters from a natural-language query."""

    BATCH = "batch"
    """Process a predefined batch of parameter IDs."""

    SINGLE = "single"
    """Process exactly one parameter."""


class RowLabel(str, Enum):
    """Per-row classification applied during table normalization."""

    HEADER = "header"
    SECTION_HEADER = "section_header"
    MASTER = "master"
    CHILD = "child"
    CONTINUATION = "continuation"
    DATA = "data"
    GARBAGE = "garbage"



class RoutingSource(str, Enum):
    """How :class:`~table_scraper.domain.models.PatternClassification` chose a parser route."""

    CONFIG_OVERRIDE = "config_override"
    """Pattern forced by parameter YAML (``pattern_override``)."""

    CLASSIFIER = "classifier"
    """Automatic scoring from pattern signatures."""

    USER_CONFIRMED = "user_confirmed"
    """User confirmed a low-confidence classification."""


class ParseStatus(str, Enum):
    """Outcome status for :class:`~table_scraper.domain.models.ParseResult`."""

    SUCCESS = "success"
    """All rows parsed without fatal errors."""

    PARTIAL = "partial"
    """Some records emitted but non-fatal issues were recorded."""

    FAILED = "failed"
    """Parse failed; no records emitted."""


class BlockParserHint(str, Enum):
    """Suggested block-level parser for a :class:`~table_scraper.domain.models.StateBlock`."""

    MATRIX = "matrix"
    SIMPLE_MATRIX = "simple_matrix"
    KEY_VALUE = "key_value"


class ExportMode(str, Enum):
    """Excel export packaging mode for warehouse deliverables."""

    SINGLE_WORKBOOK = "single_workbook"
    """All parameters in one multi-sheet workbook."""

    PER_PARAMETER = "per_parameter"
    """One XLSX file per parameter."""


class DiscoverySource(str, Enum):
    """How a :class:`~table_scraper.domain.models.ParameterDefinition` was discovered."""

    TOC = "toc"
    INDEX = "index"
    MERGED = "merged"


class ValidationSeverity(str, Enum):
    """Severity level for individual :class:`~table_scraper.domain.models.ValidationCheck` entries."""

    ERROR = "error"
    """Blocking issue; fails the validation gate."""

    WARNING = "warning"
    """Non-blocking issue; recorded but export may proceed."""

    INFO = "info"
    """Informational check outcome."""

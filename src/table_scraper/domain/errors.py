"""Domain exception hierarchy for the regulatory PDF table extraction pipeline.

All pipeline failures that propagate to callers should inherit from
:class:`TableScraperError`. Stage-specific subclasses allow callers to catch
narrow failure modes without coupling to implementation details.
"""

from __future__ import annotations


class TableScraperError(Exception):
    """Base exception for all pipeline errors.

    Catch this type at application boundaries (CLI, API) to handle any
    recoverable or fatal pipeline failure with a single handler.
    """


class DiscoveryError(TableScraperError):
    """Raised when TOC extraction, parameter cataloging, or page-range resolution fails.

    Typical causes include missing TOC pages, no matching table titles in the
    page index, failed offset calibration, or an empty parameter catalog after
    filtering spurious matches.
    """


class ExtractionError(TableScraperError):
    """Raised when raw table extraction from the PDF fails.

    Typical causes include no tables detected on a confirmed page range, table
    selector ambiguity, or adapter failures when reading page geometry.
    """


class NormalizationError(TableScraperError):
    """Raised when structural or lexical table normalization fails.

    Typical causes include empty merged tables that cannot be cleaned, invalid
    geometry after cleanup, or hierarchy propagation conflicts.
    """


class PatternUnknownError(TableScraperError):
    """Raised when pattern classification cannot route a table to a parser.

    Emitted when the classifier returns :attr:`~TablePattern.UNKNOWN` with
    insufficient confidence and no user override is available.
    """


class ParserNotFoundError(TableScraperError):
    """Raised when no parser plugin matches the pattern or parameter identifier.

    Typical causes include a missing registry entry, a disabled parser family,
    or a mismatch between classified pattern and registered plugins.
    """


class ValidationError(TableScraperError):
    """Raised when post-parse validation fails with blocking errors.

    Distinct from dataclass ``ValueError`` invariant checks: this exception
    represents business-rule failures (minimum record count, state coverage,
    required field null rates) after a parse completes.
    """


class ConfigError(TableScraperError):
    """Raised when configuration loading or schema validation fails.

    Typical causes include unknown parser IDs, invalid YAML shape, missing
    profile files, or unresolved parameter references at startup.
    """


class WorkspaceError(TableScraperError):
    """Raised when workspace lifecycle or artifact I/O fails.

    Typical causes include unreadable PDF paths, corrupt manifest JSON, missing
    artifacts required for stage idempotency, or hash mismatches on cache read.
    """

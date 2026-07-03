"""Pipeline session state container."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from table_scraper.domain.models import ParameterCatalog, UserSelection
from table_scraper.storage.workspace import Workspace


@dataclass
class PipelineSession:
    """
    Holds workspace, config, user selections, and confirmed page ranges.

    TODO: Wire session lifecycle across pipeline stages.
    """

    workspace: Workspace
    settings: Any = None
    catalog: ParameterCatalog | None = None
    user_selection: UserSelection | None = None
    registry: Any = field(default=None, repr=False)

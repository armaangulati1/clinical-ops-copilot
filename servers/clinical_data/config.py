"""Server configuration for clinical-data MCP."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

DEFAULT_CHART_ROOT = Path("data/charts")
CHART_ROOT_ENV = "CLINICAL_DATA_CHART_ROOT"
DATA_SOURCE_ENV = "CLINICAL_DATA_SOURCE"
DataSource = Literal["mock", "fhir"]


@dataclass(frozen=True)
class ServerConfig:
    """Runtime configuration for the clinical-data server."""

    chart_roots: tuple[Path, ...]
    data_source: DataSource = "mock"


def _parse_data_source(raw: str) -> DataSource:
    if raw not in ("mock", "fhir"):
        msg = f"Unsupported {DATA_SOURCE_ENV}={raw!r}; expected 'mock' or 'fhir'"
        raise ValueError(msg)
    return raw  # type: ignore[return-value]


def load_config(chart_root: str | Path | None = None) -> ServerConfig:
    """Load chart roots and data source from CLI arg or environment."""
    if chart_root is not None:
        roots: tuple[Path, ...] = (Path(chart_root),)
    else:
        raw = os.environ.get(CHART_ROOT_ENV, str(DEFAULT_CHART_ROOT))
        roots = tuple(Path(part.strip()) for part in raw.split(",") if part.strip())
    data_source = _parse_data_source(os.environ.get(DATA_SOURCE_ENV, "mock"))
    return ServerConfig(chart_roots=roots, data_source=data_source)

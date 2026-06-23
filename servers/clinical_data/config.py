"""Server configuration for clinical-data MCP."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CHART_ROOT = Path("data/charts")
CHART_ROOT_ENV = "CLINICAL_DATA_CHART_ROOT"


@dataclass(frozen=True)
class ServerConfig:
    """Runtime configuration for the clinical-data server."""

    chart_roots: tuple[Path, ...]


def load_config(chart_root: str | Path | None = None) -> ServerConfig:
    """Load chart roots from CLI arg or environment."""
    if chart_root is not None:
        roots: tuple[Path, ...] = (Path(chart_root),)
    else:
        raw = os.environ.get(CHART_ROOT_ENV, str(DEFAULT_CHART_ROOT))
        roots = tuple(Path(part.strip()) for part in raw.split(",") if part.strip())
    return ServerConfig(chart_roots=roots)

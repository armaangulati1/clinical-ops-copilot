"""Eval-only dataset access (held-out labels read here for measurement)."""

from __future__ import annotations

from pathlib import Path

from schemas.loader import DatasetEntry
from schemas.loader import load_dataset as _load_dataset

DEFAULT_CASES_DIR = Path("data/cases")
DEFAULT_LABELS_PATH = Path("data/labels/labels.json")


def load_eval_dataset(
    *,
    cases_dir: Path = DEFAULT_CASES_DIR,
    labels_path: Path = DEFAULT_LABELS_PATH,
) -> list[DatasetEntry]:
    """Load cases paired with held-out labels for evaluation only."""
    return _load_dataset(cases_dir=cases_dir, labels_path=labels_path)

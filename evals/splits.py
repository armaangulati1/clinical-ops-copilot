"""Load evaluation case-ID splits (dev vs locked test)."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from schemas.decisions import DecisionAction
from schemas.loader import load_labels


class EvalSplit(BaseModel):
    """A stratified subset of labeled cases for evaluation."""

    name: str
    description: str
    algorithm: str
    case_ids: list[str] = Field(..., min_length=1)
    class_counts: dict[str, int] = Field(default_factory=dict)


def load_eval_split(path: Path) -> EvalSplit:
    return EvalSplit.model_validate_json(path.read_text(encoding="utf-8"))


def class_counts_for_split(
    case_ids: list[str],
    *,
    labels_path: Path = Path("data/labels/labels.json"),
) -> dict[str, int]:
    labels = load_labels(labels_path)
    counts = {action.value: 0 for action in DecisionAction}
    for case_id in case_ids:
        counts[labels.get(case_id).correct_action.value] += 1
    return counts


def filter_case_ids(case_ids: list[str], allowed: set[str]) -> list[str]:
    """Preserve split file order while restricting to allowed IDs."""
    return [case_id for case_id in case_ids if case_id in allowed]

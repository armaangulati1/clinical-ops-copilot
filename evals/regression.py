"""CI regression gate for decision macro-F1."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from evals.metrics.classification import compute_classification_metrics
from schemas.loader import DatasetEntry

REGRESSION_FIXTURE_PATH = Path("evals/regression/fixtures/predictions.json")
REGRESSION_THRESHOLD_PATH = Path("evals/regression/threshold.json")


class RegressionThreshold(BaseModel):
    macro_f1_min: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Minimum macro-F1 on the regression subset.",
    )
    rationale: str = Field(..., min_length=10)
    case_ids: list[str] = Field(..., min_length=1)


class RegressionFixture(BaseModel):
    case_ids: list[str]
    predictions: dict[str, str]
    source: str = Field(
        default="stub-planner-offline-baseline",
        description="How fixture predictions were produced.",
    )


class RegressionGateResult(BaseModel):
    passed: bool
    macro_f1: float
    threshold: float
    n_cases: int


def load_regression_threshold(
    path: Path = REGRESSION_THRESHOLD_PATH,
) -> RegressionThreshold:
    return RegressionThreshold.model_validate_json(path.read_text(encoding="utf-8"))


def load_regression_fixture(path: Path = REGRESSION_FIXTURE_PATH) -> RegressionFixture:
    return RegressionFixture.model_validate_json(path.read_text(encoding="utf-8"))


def evaluate_regression_gate(
    entries: list[DatasetEntry],
    fixture: RegressionFixture,
    threshold: RegressionThreshold,
) -> RegressionGateResult:
    labels_by_id = {entry.case.case_id: entry.label for entry in entries}
    missing = [case_id for case_id in fixture.case_ids if case_id not in labels_by_id]
    if missing:
        msg = f"Regression fixture references unknown case_ids: {missing}"
        raise ValueError(msg)

    y_true: list[str] = []
    y_pred: list[str] = []
    for case_id in fixture.case_ids:
        prediction = fixture.predictions.get(case_id)
        if prediction is None:
            msg = f"Missing prediction for regression case {case_id}"
            raise ValueError(msg)
        y_true.append(labels_by_id[case_id].correct_action.value)
        y_pred.append(prediction)

    metrics = compute_classification_metrics(y_true, y_pred)
    passed = metrics.macro_f1 >= threshold.macro_f1_min
    return RegressionGateResult(
        passed=passed,
        macro_f1=metrics.macro_f1,
        threshold=threshold.macro_f1_min,
        n_cases=len(fixture.case_ids),
    )


def write_regression_fixture(fixture: RegressionFixture, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(fixture.model_dump_json(indent=2), encoding="utf-8")


def write_regression_threshold(threshold: RegressionThreshold, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(threshold.model_dump_json(indent=2), encoding="utf-8")

"""Regression gate and label-integrity tests for the eval harness."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.llm import StubPlanner
from evals.aggregate import human_judge_agreement
from evals.dataset import load_eval_dataset
from evals.human_ratings import load_human_ratings
from evals.judge import FixtureEmailJudge, load_fixture_judge_scores
from evals.regression import (
    RegressionFixture,
    evaluate_regression_gate,
    load_regression_fixture,
    load_regression_threshold,
)
from evals.runner import build_mock_host, run_dataset_eval

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGRESSION_FIXTURE = PROJECT_ROOT / "evals/regression/fixtures/predictions.json"
REGRESSION_THRESHOLD = PROJECT_ROOT / "evals/regression/threshold.json"
LABELS_PATH = PROJECT_ROOT / "data/labels/labels.json"
CASES_DIR = PROJECT_ROOT / "data/cases"
FIXTURE_JUDGE = PROJECT_ROOT / "evals/fixtures/judge_scores.json"
HUMAN_RATINGS = PROJECT_ROOT / "evals/human_email_ratings.json"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_labels_only_loaded_from_eval_paths() -> None:
    """Held-out labels must not be read by agent runtime modules."""
    offenders: list[str] = []
    for path in PROJECT_ROOT.rglob("*.py"):
        if path.name == "loader.py" and path.parent.name == "schemas":
            continue
        if path.parent.name == "__pycache__":
            continue
        rel = path.relative_to(PROJECT_ROOT)
        if rel.parts[0] in {"agent", "servers", "ui"}:
            source = path.read_text(encoding="utf-8")
            if "load_labels" in source or "labels.json" in source:
                offenders.append(str(rel))
    assert offenders == [], f"labels referenced outside eval tooling: {offenders}"


def test_regression_gate_passes_with_committed_fixture() -> None:
    entries = load_eval_dataset(cases_dir=CASES_DIR, labels_path=LABELS_PATH)
    fixture = load_regression_fixture(REGRESSION_FIXTURE)
    threshold = load_regression_threshold(REGRESSION_THRESHOLD)
    result = evaluate_regression_gate(entries, fixture, threshold)
    assert result.passed is True
    assert result.macro_f1 >= threshold.macro_f1_min


def test_regression_gate_fails_when_predictions_degraded() -> None:
    entries = load_eval_dataset(cases_dir=CASES_DIR, labels_path=LABELS_PATH)
    fixture = load_regression_fixture(REGRESSION_FIXTURE)
    threshold = load_regression_threshold(REGRESSION_THRESHOLD)
    degraded = RegressionFixture(
        case_ids=fixture.case_ids,
        predictions=dict.fromkeys(fixture.case_ids, "submit"),
        source="degraded-test-fixture",
    )
    result = evaluate_regression_gate(entries, degraded, threshold)
    assert result.passed is False
    assert result.macro_f1 < threshold.macro_f1_min


@pytest.mark.anyio
async def test_stub_eval_produces_judge_agreement_with_fixtures() -> None:
    entries = load_eval_dataset(cases_dir=CASES_DIR, labels_path=LABELS_PATH)
    subset = [
        entry for entry in entries if entry.case.case_id in {"case-007", "case-008"}
    ]
    planner = StubPlanner()
    results = await run_dataset_eval(
        subset,
        planner,
        host_factory=lambda entry: build_mock_host(entry),
    )
    judge = FixtureEmailJudge(load_fixture_judge_scores(FIXTURE_JUDGE))
    for result in results:
        if result.drafted_email is None:
            continue
        score = await judge.score_email(
            case_id=result.case_id,
            subject=result.email_subject or "",
            body=result.drafted_email,
            missing_fields=result.missing_fields,
        )
        result.judge_email_score = score.overall_score

    human = load_human_ratings(HUMAN_RATINGS)
    agreement = human_judge_agreement(human.scores_by_case(), results)
    assert agreement is not None
    assert agreement.exact_agreement_rate >= 0.5

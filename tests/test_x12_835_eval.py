"""Eval wire-in: denial-triage exact-match + precision/recall on the fixture set."""

from __future__ import annotations

from edi.eval_triage import run_triage_eval


def test_triage_eval_is_exact_match() -> None:
    report = run_triage_eval()
    assert report.total >= 8
    assert report.correct == report.total
    assert report.accuracy == 1.0


def test_every_recommendation_class_has_support() -> None:
    report = run_triage_eval()
    stats = report.precision_recall()
    # all four triage outcomes should appear in the golden set
    for cls in (
        "no-action",
        "resubmit-with-documentation",
        "correct-and-rebill",
        "needs-human-review",
    ):
        assert stats[cls]["support"] >= 1


def test_precision_recall_perfect_on_fixture_set() -> None:
    report = run_triage_eval()
    for cls, s in report.precision_recall().items():
        assert s["precision"] == 1.0, cls
        assert s["recall"] == 1.0, cls

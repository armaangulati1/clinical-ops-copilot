"""Eval wire-in: eligibility exact-match + precision/recall on the fixture set."""

from __future__ import annotations

from edi.eligibility_271 import BenefitOutcome, RejectReason
from edi.eval_eligibility import run_eligibility_eval


def test_eligibility_eval_is_exact_match() -> None:
    report = run_eligibility_eval()
    assert report.total >= 11
    assert report.correct == report.total
    assert report.accuracy == 1.0


def test_every_outcome_class_has_support() -> None:
    stats = run_eligibility_eval().precision_recall()
    for outcome in BenefitOutcome:
        assert stats[outcome.value]["support"] >= 1, outcome


def test_every_reject_reason_has_support() -> None:
    stats = run_eligibility_eval().precision_recall()
    for reason in RejectReason:
        assert stats[reason.value]["support"] >= 1, reason


def test_precision_recall_perfect_on_fixture_set() -> None:
    for cls, s in run_eligibility_eval().precision_recall().items():
        assert s["precision"] == 1.0, cls
        assert s["recall"] == 1.0, cls

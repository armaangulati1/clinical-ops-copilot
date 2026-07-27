"""Eval wire-in: claim-status exact-match + precision/recall on the fixture set."""

from __future__ import annotations

from edi.claim_status_277 import ClaimStatus
from edi.eval_claim_status import run_claim_status_eval


def test_claim_status_eval_is_exact_match() -> None:
    report = run_claim_status_eval()
    assert report.total >= 10
    assert report.correct == report.total
    assert report.accuracy == 1.0


def test_every_status_class_has_support() -> None:
    stats = run_claim_status_eval().precision_recall()
    for status in ClaimStatus:
        assert stats[status.value]["support"] >= 1, status


def test_precision_recall_perfect_on_fixture_set() -> None:
    for cls, s in run_claim_status_eval().precision_recall().items():
        assert s["precision"] == 1.0, cls
        assert s["recall"] == 1.0, cls

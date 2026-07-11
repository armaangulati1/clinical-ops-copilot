"""Eval wire-in: 278-ingested path vs native path decision agreement.

Runs the locked held-out split's cases through the 278 ingestion path and the
native path and asserts the offline decision agrees. The locked split file is
read-only here and its labels are never consulted.
"""

from __future__ import annotations

from pathlib import Path

from edi.eval_agreement import run_agreement

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCKED_SPLIT = PROJECT_ROOT / "evals" / "splits" / "locked_test.json"


def test_locked_split_still_has_sixteen_cases() -> None:
    # Guard that the wire-in did not perturb the locked split.
    import json

    payload = json.loads(LOCKED_SPLIT.read_text(encoding="utf-8"))
    assert len(payload["case_ids"]) == 16


def test_278_path_agrees_with_native_path() -> None:
    report = run_agreement()
    assert report.total == 16
    # The EDI ingestion layer must not change any decision.
    assert report.agree_count == report.total, [
        (row.case_id, row.native_action.value, row.edi_action.value)
        for row in report.per_case
        if not row.agrees
    ]
    assert report.rate == 1.0

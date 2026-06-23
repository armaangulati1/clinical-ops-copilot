"""Tests for eval case-ID splits."""

from __future__ import annotations

from pathlib import Path

from evals.splits import load_eval_split

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_dev_and_locked_splits_are_disjoint_and_cover_all_labeled_cases() -> None:
    dev = load_eval_split(PROJECT_ROOT / "evals/splits/dev.json")
    locked = load_eval_split(PROJECT_ROOT / "evals/splits/locked_test.json")
    assert len(dev.case_ids) == 32
    assert len(locked.case_ids) == 16
    assert set(dev.case_ids).isdisjoint(locked.case_ids)
    assert set(dev.case_ids) | set(locked.case_ids) == {
        f"case-{index:03d}" for index in range(1, 49)
    }
    assert dev.class_counts == {
        "submit": 11,
        "request-more-info": 11,
        "deny-risk": 10,
    }
    assert locked.class_counts == {
        "submit": 6,
        "request-more-info": 5,
        "deny-risk": 5,
    }

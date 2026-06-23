"""Tests for the synthetic prior-auth dataset."""

import json

from schemas.cases import Case
from schemas.decisions import DecisionAction
from schemas.loader import (
    DEFAULT_CASES_DIR,
    DEFAULT_LABELS_PATH,
    decision_class_counts,
    load_cases,
    load_dataset,
    load_labels,
)

MIN_CASE_COUNT = 40


def test_at_least_forty_cases_load_and_validate() -> None:
    cases = load_cases()
    assert len(cases) >= MIN_CASE_COUNT
    for case in cases:
        assert isinstance(case, Case)


def test_every_case_has_matching_label() -> None:
    dataset = load_dataset()
    case_ids = {entry.case.case_id for entry in dataset}
    label_ids = set(load_labels().labels.keys())
    assert case_ids == label_ids


def test_all_three_decision_classes_represented() -> None:
    counts = decision_class_counts(load_labels())
    for action in DecisionAction:
        assert counts[action] > 0, f"Missing decision class: {action.value}"


def test_case_inputs_contain_no_labels() -> None:
    forbidden = {
        "correct_action",
        "required_fields_present",
        "fields_missing",
        "label_rationale",
        "difficulty",
        "labels",
    }
    for path in DEFAULT_CASES_DIR.glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert forbidden.isdisjoint(payload.keys()), f"{path.name} contains label keys"


def test_labels_file_structure() -> None:
    payload = json.loads(DEFAULT_LABELS_PATH.read_text(encoding="utf-8"))
    assert "labels" in payload
    assert len(payload["labels"]) >= MIN_CASE_COUNT


def test_seed_specs_are_balanced() -> None:
    from schemas.seed_data import SEED_SPECS

    assert len(SEED_SPECS) >= MIN_CASE_COUNT

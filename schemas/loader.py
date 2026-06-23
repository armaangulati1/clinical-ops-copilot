"""Load and validate case inputs and held-out labels."""

import json
from pathlib import Path

from schemas.cases import Case, CaseLabel, CaseLabelsFile
from schemas.decisions import DecisionAction

DEFAULT_CASES_DIR = Path("data/cases")
DEFAULT_LABELS_PATH = Path("data/labels/labels.json")

FORBIDDEN_LABEL_KEYS = frozenset(
    {
        "correct_action",
        "required_fields_present",
        "fields_missing",
        "label_rationale",
        "difficulty",
        "proposed_action",
        "proposed_rationale",
        "review_status",
        "labels",
    }
)


def _validate_case_input_has_no_labels(
    payload: dict[str, object],
    source: Path,
) -> None:
    for key in FORBIDDEN_LABEL_KEYS:
        if key in payload:
            msg = f"{source} must not contain label key {key!r}"
            raise ValueError(msg)


def load_case_file(path: Path) -> Case:
    """Load and validate a single case JSON file."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        msg = f"{path} must contain a JSON object"
        raise TypeError(msg)
    _validate_case_input_has_no_labels(payload, path)
    return Case.model_validate(payload)


def load_cases(cases_dir: Path = DEFAULT_CASES_DIR) -> list[Case]:
    """Load all case inputs from ``data/cases/*.json`` sorted by case_id."""
    if not cases_dir.is_dir():
        msg = f"Cases directory not found: {cases_dir}"
        raise FileNotFoundError(msg)

    cases: list[Case] = []
    for path in sorted(cases_dir.glob("*.json")):
        cases.append(load_case_file(path))
    return cases


def load_labels(labels_path: Path = DEFAULT_LABELS_PATH) -> CaseLabelsFile:
    """Load held-out ground-truth labels."""
    payload = json.loads(labels_path.read_text(encoding="utf-8"))
    return CaseLabelsFile.model_validate(payload)


class DatasetEntry:
    """A validated case paired with its held-out label."""

    def __init__(self, case: Case, label: CaseLabel) -> None:
        self.case = case
        self.label = label


def load_dataset(
    cases_dir: Path = DEFAULT_CASES_DIR,
    labels_path: Path = DEFAULT_LABELS_PATH,
) -> list[DatasetEntry]:
    """Load cases and labels, ensuring every case_id has a matching label."""
    cases = load_cases(cases_dir)
    labels_file = load_labels(labels_path)

    case_ids = {case.case_id for case in cases}
    label_ids = set(labels_file.labels.keys())

    missing_labels = sorted(case_ids - label_ids)
    if missing_labels:
        msg = f"Missing labels for case_ids: {', '.join(missing_labels)}"
        raise ValueError(msg)

    orphan_labels = sorted(label_ids - case_ids)
    if orphan_labels:
        msg = f"Labels without matching cases: {', '.join(orphan_labels)}"
        raise ValueError(msg)

    entries: list[DatasetEntry] = []
    for case in cases:
        entries.append(DatasetEntry(case, labels_file.get(case.case_id)))
    return entries


def decision_class_counts(labels: CaseLabelsFile) -> dict[DecisionAction, int]:
    """Count labels by decision class."""
    counts = {action: 0 for action in DecisionAction}
    for label in labels.labels.values():
        counts[label.correct_action] += 1
    return counts

"""Write approved case inputs and labels from curated seed specs."""

from __future__ import annotations

import json
from pathlib import Path

from schemas.cases import CaseLabel, CaseLabelsFile, ReviewCandidate
from schemas.seed_data import SEED_SPECS, spec_to_case, spec_to_review_candidate


def write_review_candidates(
    output_path: Path = Path("data/_review/candidates.json"),
) -> list[ReviewCandidate]:
    """Write proposed cases to the human-review queue."""
    candidates = [spec_to_review_candidate(spec) for spec in SEED_SPECS]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [candidate.model_dump(mode="json") for candidate in candidates]
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return candidates


def write_approved_dataset(
    cases_dir: Path = Path("data/cases"),
    labels_path: Path = Path("data/labels/labels.json"),
) -> tuple[int, CaseLabelsFile]:
    """Write human-curated seed data as approved inputs and labels."""
    cases_dir.mkdir(parents=True, exist_ok=True)
    labels_path.parent.mkdir(parents=True, exist_ok=True)

    labels: dict[str, CaseLabel] = {}
    for spec in SEED_SPECS:
        case = spec_to_case(spec)
        case_path = cases_dir / f"{case.case_id}.json"
        case_path.write_text(
            case.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        labels[case.case_id] = CaseLabel(
            correct_action=spec.correct_action,
            required_fields_present=spec.required_fields_present,
            fields_missing=spec.fields_missing,
            label_rationale=spec.label_rationale,
            difficulty=spec.difficulty,
        )

    labels_file = CaseLabelsFile(labels=labels)
    labels_path.write_text(
        labels_file.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return len(SEED_SPECS), labels_file

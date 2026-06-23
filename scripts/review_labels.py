#!/usr/bin/env python3
"""Interactively review proposed labels and write approved ground truth."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from schemas.cases import Case, CaseLabel, CaseLabelsFile, Difficulty, ReviewCandidate
from schemas.decisions import DecisionAction
from schemas.loader import DEFAULT_CASES_DIR, DEFAULT_LABELS_PATH

DEFAULT_CANDIDATES = Path("data/_review/candidates.json")
VALID_ACTIONS = {action.value for action in DecisionAction}


def load_candidates(path: Path) -> list[ReviewCandidate]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [ReviewCandidate.model_validate(item) for item in payload]


def save_candidates(path: Path, candidates: list[ReviewCandidate]) -> None:
    data = [candidate.model_dump(mode="json") for candidate in candidates]
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load_existing_labels(path: Path) -> CaseLabelsFile:
    if not path.exists():
        return CaseLabelsFile(labels={})
    return CaseLabelsFile.model_validate(json.loads(path.read_text(encoding="utf-8")))


def write_case_input(case: Case, cases_dir: Path) -> None:
    cases_dir.mkdir(parents=True, exist_ok=True)
    case_path = cases_dir / f"{case.case_id}.json"
    case_path.write_text(case.model_dump_json(indent=2) + "\n", encoding="utf-8")


def write_labels(labels_file: CaseLabelsFile, labels_path: Path) -> None:
    labels_path.parent.mkdir(parents=True, exist_ok=True)
    labels_path.write_text(
        labels_file.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )


def prompt_action(current: DecisionAction) -> DecisionAction:
    while True:
        raw = input(
            f"Action [{current.value}] (submit/request-more-info/deny-risk): "
        ).strip()
        if not raw:
            return current
        if raw in VALID_ACTIONS:
            return DecisionAction(raw)
        print("Invalid action. Try again.")


def review_candidate(candidate: ReviewCandidate) -> CaseLabel | None:
    case = candidate.case
    print("\n" + "=" * 72)
    print(f"Case ID: {case.case_id}")
    print(f"Drug: {case.drug} | Condition: {case.condition}")
    print(f"Difficulty (proposed): {candidate.difficulty.value}")
    print(f"Proposed action: {candidate.proposed_action.value}")
    print(f"Proposed rationale: {candidate.proposed_rationale}")
    print(f"Fields missing (proposed): {', '.join(candidate.fields_missing) or 'none'}")
    print("-" * 72)
    print(case.clinical_note)
    print("-" * 72)
    print("Policy rules:", case.payer_policy.rules)
    print("Required fields:", ", ".join(case.payer_policy.required_criteria_fields))

    while True:
        choice = input("Approve? [y]es / [e]dit / [s]kip / [q]uit: ").strip().lower()
        if choice in {"", "y", "yes"}:
            return CaseLabel(
                correct_action=candidate.proposed_action,
                required_fields_present=candidate.required_fields_present,
                fields_missing=candidate.fields_missing,
                label_rationale=candidate.proposed_rationale,
                difficulty=candidate.difficulty,
            )
        if choice in {"s", "skip"}:
            return None
        if choice in {"q", "quit"}:
            raise KeyboardInterrupt
        if choice in {"e", "edit"}:
            action = prompt_action(candidate.proposed_action)
            rationale = (
                input(f"Rationale [{candidate.proposed_rationale}]: ").strip()
                or candidate.proposed_rationale
            )
            difficulty_raw = input(
                f"Difficulty [{candidate.difficulty.value}] (easy/medium/hard): "
            ).strip()
            difficulty = candidate.difficulty
            if difficulty_raw:
                difficulty = Difficulty(difficulty_raw)
            missing_raw = input(
                "Missing fields (comma-separated) "
                f"[{', '.join(candidate.fields_missing)}]: "
            ).strip()
            fields_missing = (
                [part.strip() for part in missing_raw.split(",") if part.strip()]
                if missing_raw
                else candidate.fields_missing
            )
            present: dict[str, bool] = {}
            for field in case.payer_policy.required_criteria_fields:
                default = str(candidate.required_fields_present.get(field, False))
                raw_present = input(f"  {field} present? [{default}] (y/n): ").strip()
                if not raw_present:
                    present[field] = candidate.required_fields_present.get(field, False)
                else:
                    present[field] = raw_present.lower() in {"y", "yes", "true", "1"}
            return CaseLabel(
                correct_action=action,
                required_fields_present=present,
                fields_missing=fields_missing,
                label_rationale=rationale,
                difficulty=difficulty,
            )
        print("Invalid choice.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidates",
        type=Path,
        default=DEFAULT_CANDIDATES,
        help="Path to candidates.json from generate_cases.py",
    )
    parser.add_argument(
        "--cases-dir",
        type=Path,
        default=DEFAULT_CASES_DIR,
        help="Directory for approved case inputs",
    )
    parser.add_argument(
        "--labels-path",
        type=Path,
        default=DEFAULT_LABELS_PATH,
        help="Path for approved ground-truth labels",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Review only the first N pending candidates",
    )
    args = parser.parse_args()

    if not args.candidates.exists():
        print(f"No candidates file at {args.candidates}", file=sys.stderr)
        print("Run: uv run python scripts/generate_cases.py", file=sys.stderr)
        sys.exit(1)

    candidates = load_candidates(args.candidates)
    labels_file = load_existing_labels(args.labels_path)
    reviewed = 0

    try:
        for candidate in candidates:
            if candidate.review_status != "pending":
                continue
            if args.limit is not None and reviewed >= args.limit:
                break

            label = review_candidate(candidate)
            if label is None:
                continue

            write_case_input(candidate.case, args.cases_dir)
            labels_file.labels[candidate.case.case_id] = label
            write_labels(labels_file, args.labels_path)
            candidate.review_status = "approved"
            save_candidates(args.candidates, candidates)
            reviewed += 1
            print(f"Approved {candidate.case.case_id} -> {label.correct_action.value}")
    except KeyboardInterrupt:
        print("\nReview stopped. Progress saved for approved cases.")

    print(f"Approved {reviewed} case(s). Labels at {args.labels_path}")


if __name__ == "__main__":
    main()

"""Generate FHIR eval case files and held-out labels from Synthea (run once)."""

from __future__ import annotations

import json
from pathlib import Path

from evals.fhir.label_derivation import (
    scan_patient_candidates,
)
from fhir_client.client import FhirClient
from schemas.seed_data import POLICIES

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CASES_DIR = PROJECT_ROOT / "evals/fhir/cases"
LABELS_PATH = PROJECT_ROOT / "evals/fhir/labels.json"

# Curated selection (see LABEL_REVIEW.md). Re-run scanner to regenerate proposals.
CURATED_PATIENTS: list[tuple[str, str]] = [
    ("case-049", "110998"),
    ("case-050", "103214"),
    ("case-051", "104093"),
    ("case-052", "105572"),
    ("case-053", "106151"),
    ("case-054", "130513"),
    ("case-055", "132087"),
    ("case-056", "160804"),
    ("case-057", "78748"),
    ("case-058", "10619"),
    ("case-059", "106652"),
    ("case-060", "79440"),
]

SPARSE_NOTE = (
    "Endocrinology prior-auth request for semaglutide (Ozempic) in type 2 diabetes. "
    "Structured EHR data is available for this member. "
    "Free-text note intentionally omits numeric A1C, BMI, and medication trial details."
)


def main() -> None:
    client = FhirClient()
    if not client.is_reachable():
        raise SystemExit("HAPI not reachable — run make fhir-up")

    candidates = {c.patient_id: c for c in scan_patient_candidates(client)}
    CASES_DIR.mkdir(parents=True, exist_ok=True)
    labels_payload: dict[str, dict[str, object]] = {"labels": {}}
    policy = POLICIES["t2d"]

    for case_id, patient_id in CURATED_PATIENTS:
        if patient_id not in candidates:
            msg = f"Patient {patient_id} not in candidate set"
            raise ValueError(msg)
        derived = candidates[patient_id].derived
        case_path = CASES_DIR / f"{case_id}.json"
        case_payload = {
            "case_id": case_id,
            "clinical_note": SPARSE_NOTE,
            "payer_policy": policy.model_dump(mode="json"),
            "drug": policy.drug,
            "condition": policy.condition,
            "patient_id": patient_id,
        }
        case_path.write_text(
            json.dumps(case_payload, indent=2) + "\n",
            encoding="utf-8",
        )
        labels_payload["labels"][case_id] = derived.label.model_dump(mode="json")

    LABELS_PATH.write_text(
        json.dumps(labels_payload, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(CURATED_PATIENTS)} cases to {CASES_DIR}")
    print(f"Wrote labels to {LABELS_PATH}")


if __name__ == "__main__":
    main()

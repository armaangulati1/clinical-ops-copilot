"""Eval-only loader for the FHIR-backed labeled dataset."""

from __future__ import annotations

import json
from pathlib import Path

from schemas.cases import CaseLabel, CaseLabelsFile
from schemas.loader import DatasetEntry, load_case_file

FHIR_CASES_DIR = Path("evals/fhir/cases")
FHIR_LABELS_PATH = Path("evals/fhir/labels.json")
FHIR_MANIFEST_PATH = Path("evals/fhir/manifest.json")


def load_fhir_eval_dataset(
    project_root: Path,
) -> tuple[list[DatasetEntry], dict[str, object]]:
    """Load FHIR eval cases + held-out labels (evals/ only)."""
    cases_dir = project_root / FHIR_CASES_DIR
    labels_path = project_root / FHIR_LABELS_PATH
    manifest_path = project_root / FHIR_MANIFEST_PATH

    if not cases_dir.is_dir():
        msg = f"FHIR cases directory not found: {cases_dir}"
        raise FileNotFoundError(msg)

    cases = [load_case_file(path) for path in sorted(cases_dir.glob("*.json"))]
    labels_file = CaseLabelsFile.model_validate(
        json.loads(labels_path.read_text(encoding="utf-8"))
    )
    manifest: dict[str, object] = {}
    if manifest_path.exists():
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            manifest = loaded

    case_ids = {case.case_id for case in cases}
    label_ids = set(labels_file.labels.keys())
    missing = sorted(case_ids - label_ids)
    if missing:
        msg = f"Missing FHIR labels for: {', '.join(missing)}"
        raise ValueError(msg)
    orphans = sorted(label_ids - case_ids)
    if orphans:
        msg = f"Orphan FHIR labels without cases: {', '.join(orphans)}"
        raise ValueError(msg)

    entries = [DatasetEntry(case, labels_file.get(case.case_id)) for case in cases]
    return entries, manifest


def fhir_label_metadata(labels_path: Path) -> dict[str, CaseLabel]:
    """Return held-out labels keyed by case_id (eval measurement only)."""
    labels_file = CaseLabelsFile.model_validate(
        json.loads(labels_path.read_text(encoding="utf-8"))
    )
    return dict(labels_file.labels.items())

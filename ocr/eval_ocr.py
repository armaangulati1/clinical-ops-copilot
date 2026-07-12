"""Field-level accuracy of the OCR pipeline vs known ground truth.

Ground truth comes from the generator (we render the letters ourselves, so the
reference values are exact). This reports per-field and overall accuracy over
all fixtures. The number reported is the real measured number, whatever it is.

Run:
    uv run python -m ocr.eval_ocr
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ocr.generate_fixtures import FIXTURES_DIR, GROUND_TRUTH_PATH
from ocr.reader import LetterRecord, read_letter

_FIELDS = [
    "case_id",
    "patient_name",
    "decision",
    "drug",
    "condition",
    "auth_number",
    "decision_date",
    "valid_through",
]


def _norm(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip().upper()


def _matches(field: str, expected: str | None, got: str | None) -> bool:
    return _norm(expected) == _norm(got)


@dataclass(frozen=True)
class FieldStats:
    field: str
    correct: int
    total: int

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0


@dataclass(frozen=True)
class OcrEvalResult:
    per_field: list[FieldStats]
    overall_correct: int
    overall_total: int

    @property
    def overall_accuracy(self) -> float:
        return self.overall_correct / self.overall_total if self.overall_total else 0.0


def _load_ground_truth() -> list[dict[str, str | None]]:
    if not GROUND_TRUTH_PATH.exists():
        raise FileNotFoundError(
            f"{GROUND_TRUTH_PATH} missing; run: uv run python -m ocr.generate_fixtures"
        )
    data: list[dict[str, str | None]] = json.loads(
        GROUND_TRUTH_PATH.read_text(encoding="utf-8")
    )
    return data


def evaluate(fixtures_dir: Path = FIXTURES_DIR) -> OcrEvalResult:
    """OCR every fixture, parse, and score fields against ground truth."""
    ground_truth = _load_ground_truth()
    counts: dict[str, list[int]] = {f: [0, 0] for f in _FIELDS}

    for gt in ground_truth:
        image_name = gt["image"]
        assert image_name is not None
        record: LetterRecord = read_letter(fixtures_dir / image_name)
        for field in _FIELDS:
            expected = gt[field]
            got = getattr(record, field)
            counts[field][1] += 1
            if _matches(field, expected, got):
                counts[field][0] += 1

    per_field = [FieldStats(f, counts[f][0], counts[f][1]) for f in _FIELDS]
    overall_correct = sum(fs.correct for fs in per_field)
    overall_total = sum(fs.total for fs in per_field)
    return OcrEvalResult(per_field, overall_correct, overall_total)


def format_report(result: OcrEvalResult) -> str:
    lines = ["OCR field-level accuracy (synthetic fixtures)", ""]
    lines.append(f"{'field':<16}{'correct':>9}{'total':>7}{'accuracy':>11}")
    lines.append("-" * 43)
    for fs in result.per_field:
        lines.append(f"{fs.field:<16}{fs.correct:>9}{fs.total:>7}{fs.accuracy:>10.1%}")
    lines.append("-" * 43)
    lines.append(
        f"{'OVERALL':<16}{result.overall_correct:>9}"
        f"{result.overall_total:>7}{result.overall_accuracy:>10.1%}"
    )
    return "\n".join(lines)


def main() -> None:
    result = evaluate()
    print(format_report(result))


if __name__ == "__main__":
    main()

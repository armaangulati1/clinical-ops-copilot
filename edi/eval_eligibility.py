"""Eval harness: 271 eligibility outcomes on the self-authored 270 fixture set.

Parses every well-formed 270 fixture, resolves it against the demo coverage
table, and compares each per-service-type outcome (or the inquiry-level reject)
to the committed golden file. Reports exact-match plus per-outcome precision and
recall, and prints a table. Fully offline and reproducible (no LLM, no network,
no API keys): resolution is a pure function of the parsed inquiry and the table.

Framing: the score is on this N-row self-authored set. It measures that the
rules-driven responder reproduces the intended outcome for hand-authored
synthetic inquiries; it is not a claim of accuracy against real payer
eligibility responses, and the ``SRV-*``, ``EB-*``, and ``RJ-*`` vocabularies are
invented for this demo rather than real X12 code lists.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from edi.eligibility_271 import BenefitOutcome, RejectReason, resolve_eligibility
from edi.x12_270 import parse_270_inquiry

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "x270"
GOLDEN_FILE = FIXTURES / "golden.json"

# A reject is inquiry-level, so its golden row carries this placeholder key.
REJECT_KEY = "-"

_CLASSES = [outcome.value for outcome in BenefitOutcome] + [
    reason.value for reason in RejectReason
]


@dataclass(frozen=True)
class OutcomeResult:
    """One requested service type's predicted vs golden outcome."""

    fixture: str
    service_type: str
    predicted: str
    expected: str

    @property
    def correct(self) -> bool:
        return self.predicted == self.expected


@dataclass(frozen=True)
class EligibilityEvalReport:
    """Aggregate report over the fixture set."""

    results: list[OutcomeResult]

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def correct(self) -> int:
        return sum(1 for r in self.results if r.correct)

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    def precision_recall(self) -> dict[str, dict[str, float]]:
        """Per-class precision/recall/support over the fixture set."""
        stats: dict[str, dict[str, float]] = {}
        for cls in _CLASSES:
            tp = sum(
                1 for r in self.results if r.predicted == cls and r.expected == cls
            )
            fp = sum(
                1 for r in self.results if r.predicted == cls and r.expected != cls
            )
            fn = sum(
                1 for r in self.results if r.predicted != cls and r.expected == cls
            )
            support = sum(1 for r in self.results if r.expected == cls)
            precision = tp / (tp + fp) if (tp + fp) else 1.0
            recall = tp / (tp + fn) if (tp + fn) else 1.0
            stats[cls] = {
                "precision": precision,
                "recall": recall,
                "support": float(support),
            }
        return stats


def run_eligibility_eval(
    *, fixtures_dir: Path = FIXTURES, golden_file: Path = GOLDEN_FILE
) -> EligibilityEvalReport:
    """Parse + resolve every well-formed fixture and score against golden."""
    golden: dict[str, list[dict[str, str]]] = json.loads(
        golden_file.read_text(encoding="utf-8")
    )
    results: list[OutcomeResult] = []
    for stem, expected_rows in sorted(golden.items()):
        text = (fixtures_dir / f"{stem}.270").read_text(encoding="utf-8")
        response = resolve_eligibility(parse_270_inquiry(text))
        by_service = {row.service_type: row.outcome.value for row in response.rows}
        for row in expected_rows:
            key = row["service_type"]
            if key == REJECT_KEY:
                predicted = (
                    response.reject.value if response.reject is not None else "<none>"
                )
            else:
                predicted = by_service.get(key, "<missing>")
            results.append(
                OutcomeResult(
                    fixture=stem,
                    service_type=key,
                    predicted=predicted,
                    expected=row["outcome"],
                )
            )
    return EligibilityEvalReport(results=results)


def main() -> None:
    report = run_eligibility_eval()
    print("Eligibility (271) eval on the self-authored 270 fixture set")
    print("=" * 74)
    for r in report.results:
        flag = "ok" if r.correct else "DIFF"
        print(f"{r.fixture:<24} {r.service_type:<16} {r.predicted:<24} [{flag}]")
    print("-" * 74)
    print(
        f"Exact-match: {report.correct}/{report.total} "
        f"({report.accuracy:.0%}) over {report.total} resolved outcomes "
        f"(benefit rows and rejects)"
    )
    print()
    print(f"{'outcome':<28}{'precision':>10}{'recall':>9}{'support':>9}")
    for cls, s in report.precision_recall().items():
        print(
            f"{cls:<28}{s['precision']:>10.3f}{s['recall']:>9.3f}{int(s['support']):>9}"
        )


if __name__ == "__main__":
    main()

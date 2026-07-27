"""Eval harness: 277 claim statuses on the self-authored 276 fixture set.

Parses every well-formed 276 fixture, resolves each requested claim reference
against the demo claim store, and compares the resulting status to the committed
golden file. Reports exact-match plus per-status precision and recall, and prints
a table. Fully offline and reproducible (no LLM, no network, no API keys):
resolution is a pure function of the parsed inquiry and the store.

Framing: the score is on this N-row self-authored set. It measures that the
rules-driven responder reproduces the intended status for hand-authored
synthetic inquiries; it is not a claim of accuracy against real payer claim
status responses, and the ``CS-*`` and ``RJ-*`` vocabularies are invented for
this demo rather than real X12 code lists.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from edi.claim_status_277 import ClaimStatus, resolve_claim_status
from edi.x12_276 import parse_276_inquiry

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "x276"
GOLDEN_FILE = FIXTURES / "golden.json"

_CLASSES = [status.value for status in ClaimStatus]


@dataclass(frozen=True)
class StatusResult:
    """One requested claim reference's predicted vs golden status."""

    fixture: str
    claim_ref: str
    predicted: str
    expected: str

    @property
    def correct(self) -> bool:
        return self.predicted == self.expected


@dataclass(frozen=True)
class ClaimStatusEvalReport:
    """Aggregate report over the fixture set."""

    results: list[StatusResult]

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


def run_claim_status_eval(
    *, fixtures_dir: Path = FIXTURES, golden_file: Path = GOLDEN_FILE
) -> ClaimStatusEvalReport:
    """Parse + resolve every well-formed fixture and score against golden."""
    golden: dict[str, list[dict[str, str]]] = json.loads(
        golden_file.read_text(encoding="utf-8")
    )
    results: list[StatusResult] = []
    for stem, expected_rows in sorted(golden.items()):
        text = (fixtures_dir / f"{stem}.276").read_text(encoding="utf-8")
        response = resolve_claim_status(parse_276_inquiry(text))
        by_ref = {row.claim_ref: row.status.value for row in response.rows}
        for row in expected_rows:
            ref = row["claim_ref"]
            results.append(
                StatusResult(
                    fixture=stem,
                    claim_ref=ref,
                    predicted=by_ref.get(ref, "<missing>"),
                    expected=row["status"],
                )
            )
    return ClaimStatusEvalReport(results=results)


def main() -> None:
    report = run_claim_status_eval()
    print("Claim status (277) eval on the self-authored 276 fixture set")
    print("=" * 74)
    for r in report.results:
        flag = "ok" if r.correct else "DIFF"
        print(f"{r.fixture:<24} {r.claim_ref:<12} {r.predicted:<28} [{flag}]")
    print("-" * 74)
    print(
        f"Exact-match: {report.correct}/{report.total} "
        f"({report.accuracy:.0%}) over {report.total} requested claims"
    )
    print()
    print(f"{'status':<30}{'precision':>10}{'recall':>9}{'support':>9}")
    for cls, s in report.precision_recall().items():
        print(
            f"{cls:<30}{s['precision']:>10.3f}{s['recall']:>9.3f}{int(s['support']):>9}"
        )


if __name__ == "__main__":
    main()

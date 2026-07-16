"""Eval harness: denial-triage accuracy on the self-authored 835 fixture set.

Parses every well-formed 835 fixture, runs the deterministic triage, and
compares each per-claim recommendation to the committed golden file. Reports
exact-match accuracy plus per-recommendation precision and recall, and prints a
table. Fully offline and reproducible (no LLM, no network, no API keys): the
triage is a pure function of the parsed denial codes.

Framing: the score is on this N-fixture self-authored set. It measures that the
rules-driven triage reproduces the intended recommendation for hand-authored
synthetic remittances; it is not a claim of accuracy against real payer data.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from edi.denial_triage import TriageRecommendation, triage_remittance
from edi.x12_835 import parse_835

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "x835"
GOLDEN_FILE = FIXTURES / "golden.json"

_CLASSES = [rec.value for rec in TriageRecommendation]


@dataclass(frozen=True)
class ClaimResult:
    """One claim's predicted vs golden recommendation."""

    fixture: str
    claim_ref: str
    predicted: str
    expected: str

    @property
    def correct(self) -> bool:
        return self.predicted == self.expected


@dataclass(frozen=True)
class TriageEvalReport:
    """Aggregate report over the fixture set."""

    results: list[ClaimResult]

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


def run_triage_eval(
    *, fixtures_dir: Path = FIXTURES, golden_file: Path = GOLDEN_FILE
) -> TriageEvalReport:
    """Parse + triage every well-formed fixture and score against golden."""
    golden: dict[str, list[dict[str, str]]] = json.loads(
        golden_file.read_text(encoding="utf-8")
    )
    results: list[ClaimResult] = []
    for stem, expected_claims in sorted(golden.items()):
        text = (fixtures_dir / f"{stem}.835").read_text(encoding="utf-8")
        triages = triage_remittance(parse_835(text))
        by_ref = {t.claim_ref: t.recommendation.value for t in triages}
        for row in expected_claims:
            ref = row["claim_ref"]
            results.append(
                ClaimResult(
                    fixture=stem,
                    claim_ref=ref,
                    predicted=by_ref.get(ref, "<missing>"),
                    expected=row["recommendation"],
                )
            )
    return TriageEvalReport(results=results)


def main() -> None:
    report = run_triage_eval()
    print("Denial-triage eval on the self-authored 835 fixture set")
    print("=" * 68)
    for r in report.results:
        flag = "ok" if r.correct else "DIFF"
        print(f"{r.fixture:<22} {r.claim_ref:<10} {r.predicted:<28} [{flag}]")
    print("-" * 68)
    print(
        f"Exact-match: {report.correct}/{report.total} "
        f"({report.accuracy:.0%}) over {report.total} claims"
    )
    print()
    print(f"{'recommendation':<30}{'precision':>10}{'recall':>9}{'support':>9}")
    for cls, s in report.precision_recall().items():
        print(
            f"{cls:<30}{s['precision']:>10.3f}{s['recall']:>9.3f}{int(s['support']):>9}"
        )


if __name__ == "__main__":
    main()

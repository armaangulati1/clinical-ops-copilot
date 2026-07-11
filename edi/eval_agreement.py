"""Eval wire-in: 278-ingested path vs native path decision agreement.

Runs the locked held-out split's cases through both ingestion paths and reports
whether the agent's decision agrees:

* native path  -> Case loaded from JSON, then the offline decision pipeline.
* 278 path     -> Case JSON encoded to a 278 request, parsed back to a Case,
                  then the same offline decision pipeline.

The decision pipeline is deterministic and offline (regex extractor +
``StubPlanner`` + the production required-field guardrail), so the number is
reproducible in CI without network or API keys and isolates the EDI ingestion
layer from planner nondeterminism. The locked split file and its labels are
read-only here; labels are never consulted.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from agent.decision_guardrail import enforce_required_fields
from agent.llm import StubPlanner
from edi.encoder import encode_278_request
from edi.parser import parse_278_request
from evals.splits import load_eval_split
from schemas.cases import Case
from schemas.decisions import DecisionAction
from schemas.loader import load_case_file
from servers.clinical_data.extractor import extract
from servers.clinical_data.policy_service import get_payer_policy

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCKED_SPLIT = PROJECT_ROOT / "evals" / "splits" / "locked_test.json"
CASES_DIR = PROJECT_ROOT / "data" / "cases"


def decide(case: Case) -> DecisionAction:
    """Deterministic offline decision for a case (native or 278-ingested)."""
    extraction = extract(case.clinical_note)
    policy = get_payer_policy(case.drug, case.condition)
    planner = StubPlanner()
    decision = asyncio.run(planner.plan_decision(case, extraction, policy, []))
    decision = enforce_required_fields(decision, extraction, policy)
    return decision.action


@dataclass(frozen=True)
class CaseAgreement:
    """Per-case comparison of native vs 278-ingested decisions."""

    case_id: str
    native_action: DecisionAction
    edi_action: DecisionAction

    @property
    def agrees(self) -> bool:
        return self.native_action == self.edi_action


@dataclass(frozen=True)
class AgreementReport:
    """Aggregate agreement across a split."""

    per_case: list[CaseAgreement]

    @property
    def agree_count(self) -> int:
        return sum(1 for row in self.per_case if row.agrees)

    @property
    def total(self) -> int:
        return len(self.per_case)

    @property
    def rate(self) -> float:
        return self.agree_count / self.total if self.total else 0.0


def run_agreement(
    *,
    split_path: Path = LOCKED_SPLIT,
    cases_dir: Path = CASES_DIR,
) -> AgreementReport:
    """Compute native-vs-278 decision agreement over a split (read-only)."""
    split = load_eval_split(split_path)
    rows: list[CaseAgreement] = []
    for case_id in split.case_ids:
        native_case = load_case_file(cases_dir / f"{case_id}.json")
        edi_case = parse_278_request(encode_278_request(native_case)).to_case()
        rows.append(
            CaseAgreement(
                case_id=case_id,
                native_action=decide(native_case),
                edi_action=decide(edi_case),
            )
        )
    return AgreementReport(per_case=rows)


def main() -> None:
    report = run_agreement()
    for row in report.per_case:
        flag = "ok" if row.agrees else "DIFF"
        print(
            f"{row.case_id}: native={row.native_action.value} "
            f"edi={row.edi_action.value} [{flag}]"
        )
    print(
        f"278-path vs native-path decision agreement: "
        f"{report.agree_count}/{report.total} ({report.rate:.0%})"
    )


if __name__ == "__main__":
    main()

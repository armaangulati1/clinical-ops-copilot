"""Derive held-out decision labels from FHIR facts + Ozempic/T2D payer policy.

HONESTY NOTE (read before interpreting scores):
Labels are computed by applying the same payer policy rules to the same structured
FHIR facts the agent reads at runtime. This measures whether the agent's
decision LOGIC matches policy-on-FHIR-input — not clinical ground truth.
Synthea patients are synthetic; n is small (~10-15).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from agent.fhir_facts import (
    T2D_FHIR_MAPPING,
    FhirClinicalBundle,
    ResolvedFact,
    resolve_fhir_facts,
)
from fhir_client.client import FhirClient
from fhir_client.models import Condition
from schemas.cases import CaseLabel, Difficulty
from schemas.decisions import DecisionAction
from schemas.policies import PayerPolicy
from schemas.seed_data import POLICIES

T2D_POLICY: PayerPolicy = POLICIES["t2d"]
T2D_REQUIRED_FIELDS = T2D_POLICY.required_criteria_fields

A1C_MIN_PERCENT = 7.0
METFORMIN_TRIAL_MIN_MONTHS = 3


@dataclass(frozen=True)
class ResolvedT2dFacts:
    """Policy-relevant facts resolved from FHIR (mirrors agent fusion input)."""

    a1c_percent: float | None
    metformin_trial_months: int | None
    bmi: float | None
    diabetes_duration_years: int | None
    has_t2d_diagnosis: bool


@dataclass(frozen=True)
class DerivedLabel:
    """Label + rationale from policy-on-FHIR (for human confirmation)."""

    patient_id: str
    facts: ResolvedT2dFacts
    label: CaseLabel
    missing_fields: list[str]


def fetch_patient_bundle(client: FhirClient, patient_id: str) -> FhirClinicalBundle:
    """Load the FHIR resources used by the agent fact resolver."""
    observations_by_loinc: dict[str, list[dict[str, Any]]] = {}
    for spec in T2D_FHIR_MAPPING.observations:
        observations = client.get_observations(patient_id, code=spec.loinc)
        observations_by_loinc[spec.loinc] = [
            obs.model_dump(mode="json") for obs in observations
        ]
    conditions = [c.model_dump(mode="json") for c in client.get_conditions(patient_id)]
    medications = [
        med.model_dump(mode="json")
        for med in client.get_medication_requests(patient_id)
    ]
    return FhirClinicalBundle(
        observations_by_loinc=observations_by_loinc,
        conditions=conditions,
        medications=medications,
        reference_date=datetime.now(tz=UTC),
    )


def resolve_t2d_facts_from_bundle(bundle: FhirClinicalBundle) -> ResolvedT2dFacts:
    """Resolve T2D policy fields from a FHIR bundle."""
    facts = resolve_fhir_facts(T2D_FHIR_MAPPING, bundle)
    conditions = [Condition.model_validate(raw) for raw in bundle.conditions]
    has_t2d = _has_type2_diabetes(conditions)
    return ResolvedT2dFacts(
        a1c_percent=_float_or_none(facts.get("a1c_percent")),
        metformin_trial_months=_int_or_none(facts.get("metformin_trial_months")),
        bmi=_float_or_none(facts.get("bmi")),
        diabetes_duration_years=_int_or_none(facts.get("diabetes_duration_years")),
        has_t2d_diagnosis=has_t2d,
    )


def derive_label_from_facts(
    patient_id: str,
    facts: ResolvedT2dFacts,
) -> DerivedLabel:
    """Apply Ozempic/T2D policy rules to resolved FHIR facts."""
    missing = _missing_required_fields(facts)
    fields_present = {field: field not in missing for field in T2D_REQUIRED_FIELDS}
    if missing:
        return DerivedLabel(
            patient_id=patient_id,
            facts=facts,
            missing_fields=missing,
            label=CaseLabel(
                correct_action=DecisionAction.REQUEST_MORE_INFO,
                required_fields_present=fields_present,
                fields_missing=missing,
                label_rationale=(
                    f"FHIR facts missing required policy fields: {', '.join(missing)}. "
                    "Policy-on-FHIR label: request-more-info."
                ),
                difficulty=Difficulty.MEDIUM,
            ),
        )

    if not facts.has_t2d_diagnosis:
        return DerivedLabel(
            patient_id=patient_id,
            facts=facts,
            missing_fields=[],
            label=CaseLabel(
                correct_action=DecisionAction.DENY_RISK,
                required_fields_present=fields_present,
                fields_missing=[],
                label_rationale=(
                    "Structured FHIR lacks a type 2 diabetes Condition; "
                    "criteria not met for Ozempic coverage."
                ),
                difficulty=Difficulty.MEDIUM,
            ),
        )

    if facts.a1c_percent is not None and facts.a1c_percent < A1C_MIN_PERCENT:
        return DerivedLabel(
            patient_id=patient_id,
            facts=facts,
            missing_fields=[],
            label=CaseLabel(
                correct_action=DecisionAction.DENY_RISK,
                required_fields_present=fields_present,
                fields_missing=[],
                label_rationale=(
                    f"Most recent A1C {facts.a1c_percent}% is below payer "
                    f"threshold {A1C_MIN_PERCENT}%."
                ),
                difficulty=Difficulty.MEDIUM,
            ),
        )

    if (
        facts.metformin_trial_months is not None
        and facts.metformin_trial_months < METFORMIN_TRIAL_MIN_MONTHS
    ):
        return DerivedLabel(
            patient_id=patient_id,
            facts=facts,
            missing_fields=[],
            label=CaseLabel(
                correct_action=DecisionAction.DENY_RISK,
                required_fields_present=fields_present,
                fields_missing=[],
                label_rationale=(
                    f"Metformin trial {facts.metformin_trial_months} months is "
                    f"below payer minimum {METFORMIN_TRIAL_MIN_MONTHS} months."
                ),
                difficulty=Difficulty.MEDIUM,
            ),
        )

    return DerivedLabel(
        patient_id=patient_id,
        facts=facts,
        missing_fields=[],
        label=CaseLabel(
            correct_action=DecisionAction.SUBMIT,
            required_fields_present=fields_present,
            fields_missing=[],
            label_rationale=(
                "All required FHIR facts present and meet Ozempic/T2D payer thresholds."
            ),
            difficulty=Difficulty.EASY,
        ),
    )


def derive_label_for_patient(client: FhirClient, patient_id: str) -> DerivedLabel:
    bundle = fetch_patient_bundle(client, patient_id)
    facts = resolve_t2d_facts_from_bundle(bundle)
    return derive_label_from_facts(patient_id, facts)


def _missing_required_fields(facts: ResolvedT2dFacts) -> list[str]:
    missing: list[str] = []
    if facts.a1c_percent is None:
        missing.append("a1c_percent")
    if facts.metformin_trial_months is None:
        missing.append("metformin_trial_months")
    if facts.bmi is None:
        missing.append("bmi")
    if facts.diabetes_duration_years is None:
        missing.append("diabetes_duration_years")
    return sorted(missing)


def _has_type2_diabetes(conditions: list[Condition]) -> bool:
    for condition in conditions:
        text = (condition.code.text if condition.code else "") or ""
        lowered = text.lower()
        if (
            ("diabetes mellitus type 2" in lowered or "type 2 diabetes" in lowered)
            and "neuropathy" not in lowered
            and "prediabetes" not in lowered
        ):
            return True
    return False


def _float_or_none(fact: ResolvedFact | None) -> float | None:
    if fact is None:
        return None
    return float(fact.value)


def _int_or_none(fact: ResolvedFact | None) -> int | None:
    if fact is None:
        return None
    return int(fact.value)


@dataclass(frozen=True)
class PatientCandidate:
    patient_id: str
    facts: ResolvedT2dFacts
    derived: DerivedLabel


def scan_patient_candidates(client: FhirClient) -> list[PatientCandidate]:
    """Scan all Synthea patients and return T2D-relevant candidates."""
    candidates: list[PatientCandidate] = []
    for patient in client.list_patients():
        if not patient.id:
            continue
        try:
            bundle = fetch_patient_bundle(client, patient.id)
            facts = resolve_t2d_facts_from_bundle(bundle)
        except Exception:
            continue
        if not _is_interesting_candidate(facts):
            continue
        derived = derive_label_from_facts(patient.id, facts)
        candidates.append(
            PatientCandidate(patient_id=patient.id, facts=facts, derived=derived)
        )
    return candidates


def _is_interesting_candidate(facts: ResolvedT2dFacts) -> bool:
    """Keep patients with at least one T2D-relevant signal."""
    return (
        facts.has_t2d_diagnosis
        or facts.a1c_percent is not None
        or facts.metformin_trial_months is not None
    )


def select_balanced_eval_set(
    candidates: list[PatientCandidate],
    *,
    target_size: int = 12,
) -> list[PatientCandidate]:
    """Pick ~target_size cases covering all three decision classes when possible."""
    by_action: dict[DecisionAction, list[PatientCandidate]] = {
        action: [] for action in DecisionAction
    }
    for candidate in candidates:
        by_action[candidate.derived.label.correct_action].append(candidate)

    selected: list[PatientCandidate] = []
    for action in (
        DecisionAction.SUBMIT,
        DecisionAction.REQUEST_MORE_INFO,
        DecisionAction.DENY_RISK,
    ):
        pool = by_action[action]
        pool.sort(key=lambda item: item.patient_id)
        selected.extend(pool[: max(3, target_size // 3)])

    if len(selected) < target_size:
        remaining = [c for c in candidates if c not in selected]
        remaining.sort(key=lambda item: item.patient_id)
        selected.extend(remaining[: target_size - len(selected)])

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[PatientCandidate] = []
    for item in selected:
        if item.patient_id in seen:
            continue
        seen.add(item.patient_id)
        unique.append(item)
    return unique[:target_size]

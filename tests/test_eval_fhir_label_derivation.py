"""Unit tests for FHIR label derivation (offline)."""

from __future__ import annotations

from evals.fhir.label_derivation import ResolvedT2dFacts, derive_label_from_facts
from schemas.decisions import DecisionAction


def test_derive_submit_when_all_thresholds_met() -> None:
    derived = derive_label_from_facts(
        "110998",
        ResolvedT2dFacts(
            a1c_percent=7.92,
            metformin_trial_months=6,
            bmi=32.0,
            diabetes_duration_years=3,
            has_t2d_diagnosis=True,
        ),
    )
    assert derived.label.correct_action == DecisionAction.SUBMIT


def test_derive_request_more_info_when_fields_missing() -> None:
    derived = derive_label_from_facts(
        "106999",
        ResolvedT2dFacts(
            a1c_percent=6.0,
            metformin_trial_months=None,
            bmi=30.0,
            diabetes_duration_years=2,
            has_t2d_diagnosis=True,
        ),
    )
    assert derived.label.correct_action == DecisionAction.REQUEST_MORE_INFO
    assert derived.missing_fields == ["metformin_trial_months"]


def test_derive_deny_risk_when_a1c_below_threshold() -> None:
    derived = derive_label_from_facts(
        "78748",
        ResolvedT2dFacts(
            a1c_percent=6.72,
            metformin_trial_months=12,
            bmi=32.86,
            diabetes_duration_years=3,
            has_t2d_diagnosis=True,
        ),
    )
    assert derived.label.correct_action == DecisionAction.DENY_RISK

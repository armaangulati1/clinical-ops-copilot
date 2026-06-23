"""Unit tests for Pydantic domain schemas."""

import pytest
from pydantic import ValidationError

from schemas.actions import Action, ActionType
from schemas.cases import CaseLabel, Difficulty
from schemas.decisions import Decision, DecisionAction, ProposedAction
from schemas.extraction import Extraction
from schemas.policies import PayerPolicy


def test_payer_policy_requires_unique_criteria_fields() -> None:
    with pytest.raises(ValidationError):
        PayerPolicy(
            drug="Humira",
            condition="rheumatoid arthritis",
            required_criteria_fields=["a1c_percent", "a1c_percent"],
            rules="Patient must meet criteria for adalimumab coverage.",
        )


def test_decision_optional_proposed_action() -> None:
    decision = Decision(
        action=DecisionAction.SUBMIT,
        confidence=0.9,
        rationale="All required criteria documented clearly.",
        proposed_action=ProposedAction(
            server="clinic-ops",
            tool="create_task",
            arguments={"title": "Submit PA", "idempotency_key": "k1"},
        ),
    )
    assert decision.proposed_action is not None
    assert decision.proposed_action.tool == "create_task"


def test_decision_confidence_bounds() -> None:
    Decision(
        action=DecisionAction.SUBMIT,
        confidence=0.9,
        rationale="All required criteria documented clearly.",
    )
    with pytest.raises(ValidationError):
        Decision(
            action=DecisionAction.SUBMIT,
            confidence=1.5,
            rationale="Invalid confidence value.",
        )


def test_extraction_allows_none_for_missing_fields() -> None:
    extraction = Extraction(patient_name="Alex Rivera", age=54)
    assert extraction.a1c_percent is None
    assert extraction.das28_score is None


def test_action_maps_to_downstream_effect() -> None:
    action = Action(
        effect=ActionType.DRAFT_SUBMISSION,
        case_id="case-001",
        details="Draft PA form with documented DAS28 and DMARD failures.",
    )
    assert action.effect == ActionType.DRAFT_SUBMISSION


def test_case_label_round_trip() -> None:
    label = CaseLabel(
        correct_action=DecisionAction.REQUEST_MORE_INFO,
        required_fields_present={"a1c_percent": True, "bmi": False},
        fields_missing=["bmi"],
        label_rationale="A1C documented but BMI absent from note.",
        difficulty=Difficulty.MEDIUM,
    )
    assert label.fields_missing == ["bmi"]

"""Unit tests for prior-auth router and validator."""

from __future__ import annotations

from schemas.seed_data import POLICIES
from servers.clinical_data.priorauth_extractor.router import (
    condition_path_from_policy,
    route,
)
from servers.clinical_data.priorauth_extractor.types import (
    ConditionPath,
    FieldCandidate,
    PipelineState,
)
from servers.clinical_data.priorauth_extractor.validator import validate_values


def test_router_selects_ra_path() -> None:
    plan = route("Humira prior-auth note", POLICIES["ra"])
    assert plan.condition_path == ConditionPath.RA
    assert "das28_score" in plan.required_fields


def test_router_selects_t2d_path() -> None:
    plan = route("Ozempic glycemic control", POLICIES["t2d"])
    assert plan.condition_path == ConditionPath.T2D
    assert "a1c_percent" in plan.required_fields


def test_router_selects_migraine_path() -> None:
    plan = route("Aimovig migraine prevention", POLICIES["migraine"])
    assert plan.condition_path == ConditionPath.MIGRAINE
    assert "failed_triptans" in plan.required_fields


def test_condition_path_from_policy_matches_three_conditions() -> None:
    assert condition_path_from_policy(POLICIES["ra"]) == ConditionPath.RA
    assert condition_path_from_policy(POLICIES["t2d"]) == ConditionPath.T2D
    assert condition_path_from_policy(POLICIES["migraine"]) == ConditionPath.MIGRAINE


def test_validator_rejects_out_of_range_das28() -> None:
    state = PipelineState(
        note="test",
        policy=POLICIES["ra"],
    )
    state.route = route("ra", POLICIES["ra"])
    state.candidates["das28_score"] = FieldCandidate(value=15.0, source="test")
    extraction = validate_values(state)
    assert extraction.das28_score is None
    assert "out_of_range" in state.flags["das28_score"]


def test_validator_rejects_out_of_range_a1c() -> None:
    state = PipelineState(note="test", policy=POLICIES["t2d"])
    state.route = route("t2d", POLICIES["t2d"])
    state.candidates["a1c_percent"] = FieldCandidate(value=25.0, source="test")
    extraction = validate_values(state)
    assert extraction.a1c_percent is None
    assert "out_of_range" in state.flags["a1c_percent"]


def test_validator_rejects_negative_duration() -> None:
    state = PipelineState(note="test", policy=POLICIES["t2d"])
    state.route = route("t2d", POLICIES["t2d"])
    state.candidates["metformin_trial_months"] = FieldCandidate(value=-1, source="test")
    extraction = validate_values(state)
    assert extraction.metformin_trial_months is None
    assert "metformin_trial_months" in state.flags

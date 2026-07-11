"""Tests for the X12 278 response generator and decision->HCR mapping."""

from __future__ import annotations

from pathlib import Path

import pytest

from edi.decision_map import DECISION_TO_HCR, map_decision
from edi.generator import build_278_response
from edi.parser import Request278, parse_278_request
from edi.tokenizer import Segment, tokenize
from schemas.decisions import Decision, DecisionAction

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "edi" / "fixtures"


def _request() -> Request278:
    return parse_278_request(
        (FIXTURES / "submit_ra_case001.278").read_text(encoding="utf-8")
    )


def _decision(action: DecisionAction, missing: list[str] | None = None) -> Decision:
    return Decision(
        action=action,
        confidence=0.9,
        rationale="test rationale for response generation",
        missing_fields=missing or [],
    )


def _segment_ids(interchange: str) -> list[str]:
    segments, _ = tokenize(interchange)
    return [seg.segment_id for seg in segments]


def _hcr_segment(interchange: str) -> Segment:
    segments, _ = tokenize(interchange)
    return next(seg for seg in segments if seg.segment_id == "HCR")


def test_response_has_valid_envelope_shape() -> None:
    out = build_278_response(_decision(DecisionAction.SUBMIT), _request())
    ids = _segment_ids(out)
    assert ids[0] == "ISA"
    assert ids[-1] == "IEA"
    for required in ("GS", "ST", "BHT", "HL", "NM1", "UM", "HCR", "SE", "GE"):
        assert required in ids
    # response is itself tokenizable / round-trips through the tokenizer
    assert out.startswith("ISA")


@pytest.mark.parametrize(
    "action,expected_code",
    [
        (DecisionAction.SUBMIT, "A1"),
        (DecisionAction.REQUEST_MORE_INFO, "A4"),
        (DecisionAction.DENY_RISK, "A4"),
    ],
)
def test_decision_maps_to_expected_hcr_code(
    action: DecisionAction, expected_code: str
) -> None:
    out = build_278_response(_decision(action), _request())
    hcr = _hcr_segment(out)
    assert hcr.element(1) == expected_code


def test_deny_risk_is_pended_not_denied() -> None:
    out = build_278_response(_decision(DecisionAction.DENY_RISK), _request())
    hcr = _hcr_segment(out)
    # A3 is Not Certified / denied; deny-risk must never emit it.
    assert hcr.element(1) == "A4"
    assert hcr.element(1) != "A3"
    assert map_decision(DecisionAction.DENY_RISK).action_code == "A4"


def test_bht_marks_response_and_echoes_reference() -> None:
    out = build_278_response(_decision(DecisionAction.SUBMIT), _request())
    segments, _ = tokenize(out)
    bht = next(seg for seg in segments if seg.segment_id == "BHT")
    assert bht.element(2) == "11"  # response
    assert bht.element(3) == "case-001"


def test_missing_fields_surface_in_response_message() -> None:
    out = build_278_response(
        _decision(DecisionAction.REQUEST_MORE_INFO, missing=["das28_score"]),
        _request(),
    )
    assert "das28_score" in out


def test_mapping_table_covers_all_actions() -> None:
    assert set(DECISION_TO_HCR) == set(DecisionAction)

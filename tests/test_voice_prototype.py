"""Unit tests for the isolated voice prototype (routing + spoken phrasing).

These cover only the deterministic glue in the ``voice/`` package. They do not
touch the agent, MCP, network, Whisper, or audio hardware, so they run in the
standard ``pytest -m "not network"`` suite.
"""

from __future__ import annotations

import pytest

from schemas.decisions import Decision, DecisionAction
from voice.route import case_id_from_transcript
from voice.speak import spoken_answer
from voice.transcribe import TranscriptionUnavailable, transcribe_file


@pytest.mark.parametrize(
    ("transcript", "expected"),
    [
        ("What is the prior auth status for case one?", "case-001"),
        ("check case 3 please", "case-003"),
        ("look at case-012", "case-012"),
        ("case number twelve", "case-012"),
        ("run case twenty three", "case-023"),
        ("status for case forty eight", "case-048"),
        ("case number 7", "case-007"),
    ],
)
def test_routing_resolves_spoken_case(transcript: str, expected: str) -> None:
    assert case_id_from_transcript(transcript) == expected


def test_routing_falls_back_to_default() -> None:
    assert case_id_from_transcript("hello there") == "case-001"
    assert (
        case_id_from_transcript("hello there", default_case_id="case-005")
        == "case-005"
    )


def test_spoken_answer_submit_mentions_action_and_confidence() -> None:
    decision = Decision(
        action=DecisionAction.SUBMIT,
        confidence=0.98,
        rationale="All required criteria met with high confidence.",
        missing_fields=[],
    )
    spoken = spoken_answer("case-001", decision)
    assert "case-001" in spoken
    assert "submit" in spoken
    assert "98 percent" in spoken


def test_spoken_answer_request_more_info_lists_missing_fields() -> None:
    decision = Decision(
        action=DecisionAction.REQUEST_MORE_INFO,
        confidence=0.70,
        rationale="Required fields missing; request documentation first.",
        missing_fields=["das28_score"],
    )
    spoken = spoken_answer("case-039", decision)
    assert "request-more-info" in spoken
    assert "das28 score" in spoken


def test_transcribe_missing_file_is_unavailable(tmp_path) -> None:
    missing = tmp_path / "nope.wav"
    with pytest.raises(TranscriptionUnavailable):
        transcribe_file(missing)

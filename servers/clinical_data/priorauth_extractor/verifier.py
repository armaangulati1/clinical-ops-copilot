"""Verifier pass: per-field confidence and evidence from the note."""

from __future__ import annotations

import json
import os
from typing import Any, cast

import anthropic
from anthropic.types import MessageParam, ToolChoiceToolParam, ToolParam
from pydantic import BaseModel, Field

from servers.clinical_data.priorauth_extractor.types import PipelineState

DEFAULT_MODEL = "claude-sonnet-4-5"
VERIFY_TOOL_NAME = "record_field_verification"
DEFAULT_EXTRACTOR_CONFIDENCE = 0.85
FLAG_CONFIDENCE_PENALTY = 0.15


class FieldVerification(BaseModel):
    field_name: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str = ""
    present: bool = True


class VerifierOutput(BaseModel):
    fields: list[FieldVerification] = Field(default_factory=list)


def _client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        msg = "ANTHROPIC_API_KEY is not set"
        raise RuntimeError(msg)
    return anthropic.Anthropic(api_key=api_key)


def _tool_schema() -> dict[str, Any]:
    schema = VerifierOutput.model_json_schema()
    return {
        "name": VERIFY_TOOL_NAME,
        "description": (
            "Verify each extracted prior-auth field against the clinical note. "
            "Assign confidence 0.0-1.0 and a short evidence quote."
        ),
        "input_schema": schema,
    }


def _compute_confidence(
    state: PipelineState,
    field_name: str,
    verified: float,
) -> float:
    confidence = verified
    if field_name in state.flags:
        confidence = max(0.0, confidence - FLAG_CONFIDENCE_PENALTY)
    return round(min(1.0, max(0.0, confidence)), 3)


def _missing_field_confidence(state: PipelineState, field_name: str) -> float:
    if field_name in state.policy.required_criteria_fields:
        return 0.2
    return 0.5


def apply_verifier(state: PipelineState) -> PipelineState:
    assert state.extraction is not None
    payload = state.extraction.model_dump(mode="json")
    prompt = (
        "Verify each extracted field against the clinical note.\n\n"
        f"Extracted JSON:\n{json.dumps(payload, indent=2)}\n\n"
        f"Clinical note:\n{state.note}"
    )
    message = _client().messages.create(
        model=DEFAULT_MODEL,
        max_tokens=1500,
        system=(
            "You verify prior-auth extractions. Use low confidence when a field is "
            "missing, ambiguous, or unsupported by the note."
        ),
        messages=cast(
            list[MessageParam],
            [{"role": "user", "content": prompt}],
        ),
        tools=cast(list[ToolParam], [_tool_schema()]),
        tool_choice=cast(
            ToolChoiceToolParam,
            {"type": "tool", "name": VERIFY_TOOL_NAME},
        ),
    )

    verified_fields: dict[str, FieldVerification] = {}
    for block in message.content:
        if block.type != "tool_use" or block.name != VERIFY_TOOL_NAME:
            continue
        if not isinstance(block.input, dict):
            continue
        output = VerifierOutput.model_validate(block.input)
        for item in output.fields:
            verified_fields[item.field_name] = item

    for field_name in state.target_fields():
        value = getattr(state.extraction, field_name)
        if field_name in verified_fields:
            item = verified_fields[field_name]
            confidence = _compute_confidence(state, field_name, item.confidence)
            state.field_confidence[field_name] = confidence
            if item.evidence:
                state.evidence[field_name] = item.evidence
            if (
                confidence < state.review_threshold or not item.present
            ) and field_name not in state.needs_review:
                state.needs_review.append(field_name)
            continue

        if value is None:
            confidence = _missing_field_confidence(state, field_name)
            state.field_confidence[field_name] = confidence
            if field_name in state.policy.required_criteria_fields:
                state.needs_review.append(field_name)
        else:
            state.field_confidence[field_name] = _compute_confidence(
                state,
                field_name,
                DEFAULT_EXTRACTOR_CONFIDENCE,
            )

    return state

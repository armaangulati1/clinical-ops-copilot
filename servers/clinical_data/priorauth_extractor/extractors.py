"""Claude-backed field extractors for prior-auth notes."""

from __future__ import annotations

import os
from typing import Any, cast

import anthropic
from anthropic.types import MessageParam, ToolChoiceToolParam, ToolParam

from schemas.extraction import Extraction
from servers.clinical_data.priorauth_extractor.types import (
    COMMON_FIELDS,
    CONDITION_FIELDS,
    FieldCandidate,
    PipelineState,
)

DEFAULT_MODEL = "claude-sonnet-4-5"
EXTRACTION_TOOL_NAME = "record_prior_auth_extraction"


def _client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        msg = "ANTHROPIC_API_KEY is not set"
        raise RuntimeError(msg)
    return anthropic.Anthropic(api_key=api_key)


def _tool_schema() -> dict[str, Any]:
    schema = Extraction.model_json_schema()
    schema["additionalProperties"] = False
    return {
        "name": EXTRACTION_TOOL_NAME,
        "description": (
            "Extract structured prior-auth clinical fields from the note. "
            "Use null for fields that are missing or ambiguous."
        ),
        "input_schema": schema,
    }


def _fields_for_state(state: PipelineState) -> list[str]:
    assert state.route is not None
    fields = list(COMMON_FIELDS) if state.route.extract_common else []
    if state.route.extract_condition_fields:
        fields.extend(CONDITION_FIELDS[state.route.condition_path])
    return fields


def _build_prompt(state: PipelineState) -> str:
    fields = _fields_for_state(state)
    required_fields = ", ".join(state.policy.required_criteria_fields)
    return (
        "Extract only the following prior-auth fields from the clinical note:\n"
        f"{', '.join(fields)}\n\n"
        f"Payer policy rules:\n{state.policy.rules}\n\n"
        f"Required policy fields:\n{required_fields}\n\n"
        f"Clinical note:\n{state.note}"
    )


def _parse_tool_input(block: anthropic.types.ToolUseBlock) -> dict[str, Any]:
    if block.name != EXTRACTION_TOOL_NAME:
        msg = f"Unexpected tool name: {block.name}"
        raise ValueError(msg)
    if not isinstance(block.input, dict):
        msg = "Tool input must be a JSON object"
        raise TypeError(msg)
    return block.input


def _call_extractor(state: PipelineState) -> Extraction:
    message = _client().messages.create(
        model=DEFAULT_MODEL,
        max_tokens=1200,
        system=(
            "You extract structured prior-auth facts from clinical notes. "
            "Only use information explicitly stated in the note."
        ),
        messages=cast(
            list[MessageParam],
            [{"role": "user", "content": _build_prompt(state)}],
        ),
        tools=cast(list[ToolParam], [_tool_schema()]),
        tool_choice=cast(
            ToolChoiceToolParam,
            {"type": "tool", "name": EXTRACTION_TOOL_NAME},
        ),
    )
    for block in message.content:
        if block.type == "tool_use":
            return Extraction.model_validate(_parse_tool_input(block))
    msg = "Extractor model did not return a tool_use block"
    raise RuntimeError(msg)


def apply_extractors(state: PipelineState) -> PipelineState:
    extraction = _call_extractor(state)
    for field_name in _fields_for_state(state):
        value = getattr(extraction, field_name)
        if value is None:
            continue
        state.candidates[field_name] = FieldCandidate(
            value=value,
            confidence=0.85,
            source="extractor",
        )
    return state

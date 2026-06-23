"""Parse structured ActionFailure payloads from MCP tool error text."""

from __future__ import annotations

import json

from servers.clinic_ops.schemas import ActionFailure


def parse_action_failure_from_tool_text(text: str) -> ActionFailure:
    """Extract ActionFailure JSON from a FastMCP tool error message."""
    start = text.find("{")
    if start < 0:
        msg = f"no JSON object found in tool error text: {text!r}"
        raise ValueError(msg)
    payload = json.loads(text[start:])
    return ActionFailure.model_validate(payload)

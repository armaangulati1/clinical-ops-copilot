"""LLM-as-judge for drafted prior-auth email quality."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol

import anthropic
from anthropic.types import ToolChoiceToolParam, ToolParam
from pydantic import BaseModel, Field, ValidationError

JUDGE_TOOL_NAME = "score_email_quality"

JUDGE_RUBRIC = (
    "Score the drafted prior-auth follow-up email on a single 1-5 scale:\n"
    "5 = clear, clinically correct, requests missing info, professional\n"
    "3 = acceptable but vague or missing key asks\n"
    "1 = unclear, incorrect, or unprofessional\n"
    "Consider whether the email appropriately requests missing documentation."
)


class EmailJudgeScore(BaseModel):
    overall_score: int = Field(..., ge=1, le=5)
    rationale: str = Field(..., min_length=10)


class EmailJudge(Protocol):
    async def score_email(
        self,
        *,
        case_id: str,
        subject: str,
        body: str,
        missing_fields: list[str],
    ) -> EmailJudgeScore:
        """Return a 1-5 rubric score for a drafted email."""


def judge_tool_schema() -> dict[str, object]:
    schema = EmailJudgeScore.model_json_schema()
    schema["additionalProperties"] = False
    return {
        "name": JUDGE_TOOL_NAME,
        "description": "Score drafted prior-auth email quality on a 1-5 rubric.",
        "input_schema": schema,
    }


class AnthropicEmailJudge:
    """Claude-backed judge for email drafts."""

    def __init__(self, model: str) -> None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            msg = "ANTHROPIC_API_KEY is not set"
            raise RuntimeError(msg)
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    async def score_email(
        self,
        *,
        case_id: str,
        subject: str,
        body: str,
        missing_fields: list[str],
    ) -> EmailJudgeScore:
        prompt = (
            f"Case ID: {case_id}\n"
            f"Missing fields context: {', '.join(missing_fields) or 'none listed'}\n"
            f"Subject: {subject}\n"
            f"Body:\n{body}\n\n"
            "Score this email using the rubric."
        )
        message = self._client.messages.create(
            model=self._model,
            max_tokens=500,
            system=JUDGE_RUBRIC,
            messages=[{"role": "user", "content": prompt}],
            tools=_cast_tools([judge_tool_schema()]),
            tool_choice=_cast_tool_choice({"type": "tool", "name": JUDGE_TOOL_NAME}),
        )
        for block in message.content:
            if block.type != "tool_use":
                continue
            if block.name != JUDGE_TOOL_NAME:
                continue
            if not isinstance(block.input, dict):
                continue
            try:
                return EmailJudgeScore.model_validate(block.input)
            except ValidationError:
                continue
        msg = "Email judge did not return a score_email_quality tool call"
        raise RuntimeError(msg)


class FixtureEmailJudge:
    """Offline judge using committed fixture scores."""

    def __init__(self, scores_by_case: dict[str, int]) -> None:
        self._scores_by_case = scores_by_case

    async def score_email(
        self,
        *,
        case_id: str,
        subject: str,
        body: str,
        missing_fields: list[str],
    ) -> EmailJudgeScore:
        _ = (subject, body, missing_fields)
        score = self._scores_by_case.get(case_id)
        if score is None:
            msg = f"No fixture judge score for {case_id}"
            raise KeyError(msg)
        return EmailJudgeScore(
            overall_score=score,
            rationale="Fixture judge score for offline validation.",
        )


def load_fixture_judge_scores(path: str | Path) -> dict[str, int]:
    ratings_path = Path(path)
    payload = json.loads(ratings_path.read_text(encoding="utf-8"))
    ratings = payload.get("fixture_judge_scores", payload)
    if not isinstance(ratings, dict):
        msg = "fixture judge scores must be a JSON object"
        raise TypeError(msg)
    return {str(case_id): int(score) for case_id, score in ratings.items()}


def _cast_tools(tools: list[dict[str, object]]) -> list[ToolParam]:
    from typing import cast

    return cast(list[ToolParam], tools)


def _cast_tool_choice(payload: dict[str, str]) -> ToolChoiceToolParam:
    from typing import cast

    return cast(ToolChoiceToolParam, payload)

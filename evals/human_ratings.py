"""Human email quality ratings for judge validation."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

DEFAULT_HUMAN_RATINGS_PATH = Path("evals/human_email_ratings.json")


class HumanEmailRating(BaseModel):
    case_id: str
    human_score: int = Field(..., ge=1, le=5)
    notes: str = ""


class HumanEmailRatingsFile(BaseModel):
    rubric: str
    ratings: list[HumanEmailRating]

    def scores_by_case(self) -> dict[str, int]:
        return {rating.case_id: rating.human_score for rating in self.ratings}


def load_human_ratings(
    path: Path = DEFAULT_HUMAN_RATINGS_PATH,
) -> HumanEmailRatingsFile:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return HumanEmailRatingsFile.model_validate(payload)

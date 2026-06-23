"""Judge-vs-human agreement metrics for email quality scoring."""

from __future__ import annotations

from pydantic import BaseModel, Field


class JudgeAgreementMetrics(BaseModel):
    n_cases: int
    exact_agreement_rate: float
    mean_absolute_error: float
    pearson_r: float | None = Field(
        default=None,
        description="Pearson correlation; None when variance is zero.",
    )


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or not xs:
        msg = "score lists must be the same non-empty length"
        raise ValueError(msg)
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    den_x = sum((x - mean_x) ** 2 for x in xs) ** 0.5
    den_y = sum((y - mean_y) ** 2 for y in ys) ** 0.5
    if den_x == 0 or den_y == 0:
        return None
    return float(num / (den_x * den_y))


def compute_judge_agreement(
    human_scores: list[int],
    judge_scores: list[int],
) -> JudgeAgreementMetrics:
    """Compare human and judge rubric scores (same 1-5 scale)."""
    if len(human_scores) != len(judge_scores):
        msg = "human_scores and judge_scores must have the same length"
        raise ValueError(msg)
    if not human_scores:
        return JudgeAgreementMetrics(
            n_cases=0,
            exact_agreement_rate=0.0,
            mean_absolute_error=0.0,
            pearson_r=None,
        )

    pairs = list(zip(human_scores, judge_scores, strict=True))
    matches = sum(1 for h, j in pairs if h == j)
    mae = sum(abs(h - j) for h, j in pairs) / len(human_scores)
    pearson = _pearson(
        [float(h) for h in human_scores],
        [float(j) for j in judge_scores],
    )

    return JudgeAgreementMetrics(
        n_cases=len(human_scores),
        exact_agreement_rate=round(matches / len(human_scores), 4),
        mean_absolute_error=round(mae, 4),
        pearson_r=round(pearson, 4) if pearson is not None else None,
    )

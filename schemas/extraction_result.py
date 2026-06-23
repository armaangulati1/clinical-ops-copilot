"""Prior-auth extraction result with per-field confidence metadata."""

from pydantic import BaseModel, Field

from schemas.extraction import Extraction

DEFAULT_REVIEW_THRESHOLD = 0.75


class ExtractionResult(BaseModel):
    """Prior-auth extraction with confidence routing for human review (Phase 5+)."""

    extraction: Extraction
    field_confidence: dict[str, float] = Field(
        default_factory=dict,
        description="Per-field confidence scores in [0.0, 1.0].",
    )
    needs_review: list[str] = Field(
        default_factory=list,
        description="Field names below review_threshold.",
    )
    evidence: dict[str, str] = Field(
        default_factory=dict,
        description="Supporting note snippets per field.",
    )
    review_threshold: float = Field(
        default=DEFAULT_REVIEW_THRESHOLD,
        ge=0.0,
        le=1.0,
    )

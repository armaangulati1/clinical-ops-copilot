"""Prior-auth agentic extraction pipeline.

Flow: router -> extractors -> validator -> verifier.
"""

from __future__ import annotations

from schemas.extraction_result import ExtractionResult
from schemas.policies import PayerPolicy
from servers.clinical_data.priorauth_extractor.extractors import apply_extractors
from servers.clinical_data.priorauth_extractor.router import (
    apply_router,
    resolve_policy,
)
from servers.clinical_data.priorauth_extractor.types import PipelineState
from servers.clinical_data.priorauth_extractor.validator import apply_validator
from servers.clinical_data.priorauth_extractor.verifier import apply_verifier


def run_pipeline(
    note_text: str,
    *,
    policy: PayerPolicy | None = None,
    review_threshold: float = 0.75,
) -> ExtractionResult:
    """Run the full prior-auth extraction pipeline."""
    resolved_policy = resolve_policy(note_text, policy)
    state = PipelineState(
        note=note_text,
        policy=resolved_policy,
        review_threshold=review_threshold,
    )
    state = apply_router(state)
    state = apply_extractors(state)
    state = apply_validator(state)
    state = apply_verifier(state)
    assert state.extraction is not None
    return ExtractionResult(
        extraction=state.extraction,
        field_confidence=state.field_confidence,
        needs_review=sorted(set(state.needs_review)),
        evidence=state.evidence,
        review_threshold=state.review_threshold,
    )

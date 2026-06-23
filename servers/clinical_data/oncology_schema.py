"""Pydantic models mirroring the ChartExtractor OpenAPI schema.

These types are separate from ``schemas.extraction.Extraction`` (prior-auth).
See: https://chartextract.onrender.com/docs
"""

from __future__ import annotations

from datetime import date
from enum import IntEnum, StrEnum

from pydantic import BaseModel, Field


class BiomarkerStatus(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    EQUIVOCAL = "equivocal"
    UNKNOWN = "unknown"


class CancerStage(StrEnum):
    I = "I"
    IA = "IA"
    IB = "IB"
    IC = "IC"
    II = "II"
    IIA = "IIA"
    IIB = "IIB"
    IIC = "IIC"
    III = "III"
    IIIA = "IIIA"
    IIIB = "IIIB"
    IIIC = "IIIC"
    IV = "IV"
    IVA = "IVA"
    IVB = "IVB"


class EcogPerformanceStatus(IntEnum):
    FULLY_ACTIVE = 0
    RESTRICTED_STRENUOUS = 1
    AMBULATORY = 2
    LIMITED_SELF_CARE = 3
    COMPLETELY_DISABLED = 4


class Biomarker(BaseModel):
    name: str = Field(description="biomarker name, e.g. EGFR, PD-L1, HER2")
    status: BiomarkerStatus = Field(description="test result for this biomarker")


class OncologyExtract(BaseModel):
    """Structured oncology variables from ChartExtractor."""

    primary_site: str | None = Field(
        default=None,
        description="anatomic primary tumor site, e.g. lung, breast, colon",
    )
    histology: str | None = Field(
        default=None,
        description="tumor histology / cell type, e.g. adenocarcinoma",
    )
    stage: CancerStage | None = Field(
        default=None,
        description="AJCC clinical or pathologic stage when stated",
    )
    biomarkers: list[Biomarker] = Field(
        default_factory=list,
        description="molecular biomarkers and their results",
    )
    ecog_performance_status: EcogPerformanceStatus | None = Field(
        default=None,
        description="ECOG performance status 0-4 when documented",
    )
    line_of_therapy: int | None = Field(
        default=None,
        ge=1,
        description="line of therapy: 1 = first-line, 2 = second-line, etc.",
    )
    date_of_diagnosis: date | None = Field(
        default=None,
        description="date of cancer diagnosis when stated",
    )
    treatment_regimen: list[str] = Field(
        default_factory=list,
        description="drug names in the current or documented treatment regimen",
    )


class FieldMeta(BaseModel):
    confidence: float = Field(ge=0.0, le=1.0)
    needs_review: bool = False
    source: str = ""
    evidence: str = ""
    flags: list[str] = Field(default_factory=list)


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class RunMetrics(BaseModel):
    latency_ms: float = Field(default=0.0, ge=0.0)
    estimated_cost_usd: float = Field(default=0.0, ge=0.0)
    trace_id: str | None = None


class ExtractionOutput(BaseModel):
    """ChartExtractor pipeline result with per-field confidence metadata."""

    extract: OncologyExtract
    fields: dict[str, FieldMeta] = Field(default_factory=dict)
    needs_review: list[str] = Field(default_factory=list)
    review_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    usage: TokenUsage = Field(default_factory=TokenUsage)
    run_metrics: RunMetrics = Field(default_factory=RunMetrics)

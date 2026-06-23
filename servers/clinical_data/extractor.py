"""Chart text extraction interface.

Prior-auth extraction (``schemas.extraction.Extraction``) is separate from the
ChartExtractor oncology API (``servers.clinical_data.oncology_schema``).

``EXTRACTOR_BACKEND`` selects the prior-auth extractor:
- ``stub`` (default): fast offline regex stub for tests/dev
- ``real``: agentic prior-auth pipeline in ``priorauth_extractor/``
"""

from __future__ import annotations

import os
import re
from typing import Protocol

from schemas.extraction import Extraction
from schemas.extraction_result import DEFAULT_REVIEW_THRESHOLD, ExtractionResult
from schemas.policies import PayerPolicy

EXTRACTOR_BACKEND_ENV = "EXTRACTOR_BACKEND"
DEFAULT_EXTRACTOR_BACKEND = "stub"

_PATIENT_RE = re.compile(r"Patient:\s*(?P<name>[A-Za-z ]+?),\s*age\s*(?P<age>\d+)")
_DURATION_MONTHS_RE = re.compile(r"Disease duration:\s*(?P<months>\d+)\s*months")
_DAS28_RE = re.compile(r"DAS28(?:\s+score)?:\s*(?P<score>\d+(?:\.\d+)?)")
_DMARDS_RE = re.compile(r"Failed conventional DMARDs:\s*(?P<count>\d+)")
_MTX_WEEKS_RE = re.compile(r"Methotrexate trial:\s*(?P<weeks>\d+)\s*weeks")
_A1C_RE = re.compile(r"(?:Most recent )?A1C:\s*(?P<a1c>\d+(?:\.\d+)?)%")
_METFORMIN_RE = re.compile(
    r"Metformin trial:\s*(?P<months>\d+)\s*months",
)
_BMI_RE = re.compile(r"BMI:\s*(?P<bmi>\d+(?:\.\d+)?)")
_DIABETES_YEARS_RE = re.compile(r"Diabetes duration:\s*(?P<years>\d+)\s*years")
_MIGRAINE_DAYS_RE = re.compile(
    r"Migraine headache days per month:\s*(?P<days>\d+)",
)
_TRIPTANS_RE = re.compile(r"Failed triptan trials:\s*(?P<count>\d+)")
_PREVENTIVES_RE = re.compile(
    r"Failed preventive medication trials:\s*(?P<count>\d+)",
)


class ChartExtractorProtocol(Protocol):
    """Interface for prior-auth chart extraction implementations."""

    def extract(
        self,
        note_text: str,
        policy: PayerPolicy | None = None,
    ) -> ExtractionResult:
        """Extract structured prior-auth fields from free text."""


def _extraction_field_names() -> list[str]:
    return list(Extraction.model_fields.keys())


def _result_from_extraction(
    extraction: Extraction,
    *,
    review_threshold: float = DEFAULT_REVIEW_THRESHOLD,
    needs_review: list[str] | None = None,
    field_confidence: dict[str, float] | None = None,
    evidence: dict[str, str] | None = None,
) -> ExtractionResult:
    confidence = field_confidence or {field: 1.0 for field in _extraction_field_names()}
    return ExtractionResult(
        extraction=extraction,
        field_confidence=confidence,
        needs_review=needs_review or [],
        evidence=evidence or {},
        review_threshold=review_threshold,
    )


class ChartExtractor:
    """Regex-based STUB for synthetic Phase 1 notes (offline / CI)."""

    def extract(
        self,
        note_text: str,
        policy: PayerPolicy | None = None,
    ) -> ExtractionResult:
        _ = policy
        patient = _PATIENT_RE.search(note_text)
        duration = _DURATION_MONTHS_RE.search(note_text)
        dmards = _DMARDS_RE.search(note_text)
        das28 = _DAS28_RE.search(note_text)
        mtx = _MTX_WEEKS_RE.search(note_text)
        a1c = _A1C_RE.search(note_text)
        metformin = _METFORMIN_RE.search(note_text)
        bmi = _BMI_RE.search(note_text)
        diabetes_years = _DIABETES_YEARS_RE.search(note_text)
        migraine_days = _MIGRAINE_DAYS_RE.search(note_text)
        triptans = _TRIPTANS_RE.search(note_text)
        preventives = _PREVENTIVES_RE.search(note_text)

        diagnosis_confirmed: bool | None = None
        if "rheumatoid arthritis" in note_text.lower():
            diagnosis_confirmed = True
        elif "inflammatory arthritis suspected" in note_text.lower():
            diagnosis_confirmed = False

        chronic_migraine: bool | None = None
        if "chronic migraine" in note_text.lower():
            chronic_migraine = True
        elif "episodic migraine" in note_text.lower():
            chronic_migraine = False

        extraction = Extraction(
            patient_name=patient.group("name").strip() if patient else None,
            age=int(patient.group("age")) if patient else None,
            diagnosis_confirmed=diagnosis_confirmed,
            disease_duration_months=int(duration.group("months")) if duration else None,
            failed_dmards=int(dmards.group("count")) if dmards else None,
            das28_score=float(das28.group("score")) if das28 else None,
            methotrexate_trial_weeks=int(mtx.group("weeks")) if mtx else None,
            a1c_percent=float(a1c.group("a1c")) if a1c else None,
            metformin_trial_months=int(metformin.group("months"))
            if metformin
            else None,
            bmi=float(bmi.group("bmi")) if bmi else None,
            diabetes_duration_years=int(diabetes_years.group("years"))
            if diabetes_years
            else None,
            migraine_days_per_month=int(migraine_days.group("days"))
            if migraine_days
            else None,
            chronic_migraine_diagnosis=chronic_migraine,
            failed_triptans=int(triptans.group("count")) if triptans else None,
            preventive_trial_failed=int(preventives.group("count"))
            if preventives
            else None,
        )
        return _result_from_extraction(extraction)


class AgenticPriorAuthExtractor:
    """Agentic prior-auth extractor built in this repo (not ChartExtractor oncology)."""

    def extract(
        self,
        note_text: str,
        policy: PayerPolicy | None = None,
    ) -> ExtractionResult:
        from servers.clinical_data.priorauth_extractor.pipeline import run_pipeline

        return run_pipeline(note_text, policy=policy)


def get_prior_auth_extractor() -> ChartExtractorProtocol:
    """Return the configured prior-auth extractor backend."""
    backend = os.environ.get(EXTRACTOR_BACKEND_ENV, DEFAULT_EXTRACTOR_BACKEND)
    if backend == "stub":
        return ChartExtractor()
    if backend == "real":
        return AgenticPriorAuthExtractor()
    msg = f"Unsupported {EXTRACTOR_BACKEND_ENV}={backend!r}; expected 'stub' or 'real'"
    raise ValueError(msg)


def extract(
    note_text: str,
    *,
    policy: PayerPolicy | None = None,
    extractor: ChartExtractorProtocol | None = None,
) -> ExtractionResult:
    """Extract prior-auth structured fields using the configured backend."""
    active = extractor or get_prior_auth_extractor()
    return active.extract(note_text, policy=policy)

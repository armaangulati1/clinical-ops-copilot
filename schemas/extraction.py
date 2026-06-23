"""Structured clinical fields extracted from free-text notes."""

from pydantic import BaseModel, Field


class Extraction(BaseModel):
    """Structured clinical facts pulled from a prior-auth clinical note.

    All fields are optional; ``None`` means the field was not found or is ambiguous.
    """

    patient_name: str | None = Field(default=None, min_length=1)
    age: int | None = Field(default=None, ge=0, le=120)

    # Rheumatoid arthritis (adalimumab / Humira)
    diagnosis_confirmed: bool | None = None
    disease_duration_months: int | None = Field(default=None, ge=0)
    failed_dmards: int | None = Field(default=None, ge=0)
    das28_score: float | None = Field(default=None, ge=0.0)
    methotrexate_trial_weeks: int | None = Field(default=None, ge=0)

    # Type 2 diabetes (semaglutide / Ozempic)
    a1c_percent: float | None = Field(default=None, ge=4.0, le=20.0)
    metformin_trial_months: int | None = Field(default=None, ge=0)
    bmi: float | None = Field(default=None, ge=10.0, le=80.0)
    diabetes_duration_years: int | None = Field(default=None, ge=0)

    # Chronic migraine (erenumab / Aimovig)
    migraine_days_per_month: int | None = Field(default=None, ge=0, le=31)
    chronic_migraine_diagnosis: bool | None = None
    failed_triptans: int | None = Field(default=None, ge=0)
    preventive_trial_failed: int | None = Field(default=None, ge=0)

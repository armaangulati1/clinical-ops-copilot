"""Config-driven FHIR fact resolver for prior-auth required fields."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fhir_client.models import Condition, MedicationRequest, Observation
from schemas.extraction_result import ExtractionResult
from schemas.policies import PayerPolicy

LOINC_SYSTEM = "http://loinc.org"
NOTE_PROVENANCE = "note"

A1C_LOINC = f"{LOINC_SYSTEM}|4548-4"
BMI_LOINC = f"{LOINC_SYSTEM}|39156-5"


@dataclass(frozen=True)
class ResolvedFact:
    """A single policy field resolved from structured FHIR data."""

    field_name: str
    value: float | int | bool
    provenance: str
    confidence: float = 1.0


@dataclass(frozen=True)
class ObservationFieldSpec:
    field_name: str
    loinc: str


@dataclass(frozen=True)
class ConditionDurationSpec:
    field_name: str
    match_texts: tuple[str, ...]
    match_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class MedicationTrialSpec:
    field_name: str
    match_texts: tuple[str, ...]


@dataclass(frozen=True)
class PolicyFhirMapping:
    """Maps prior-auth policy fields to FHIR resource queries."""

    policy_keys: tuple[str, ...]
    drug_keywords: tuple[str, ...]
    condition_keywords: tuple[str, ...]
    observations: tuple[ObservationFieldSpec, ...]
    condition_duration: ConditionDurationSpec | None
    medication_trials: tuple[MedicationTrialSpec, ...]


T2D_FHIR_MAPPING = PolicyFhirMapping(
    policy_keys=("t2d",),
    drug_keywords=("ozempic", "semaglutide"),
    condition_keywords=(
        "type 2 diabetes",
        "t2d",
        "diabetes mellitus type 2",
    ),
    observations=(
        ObservationFieldSpec("a1c_percent", A1C_LOINC),
        ObservationFieldSpec("bmi", BMI_LOINC),
    ),
    condition_duration=ConditionDurationSpec(
        field_name="diabetes_duration_years",
        match_texts=("diabetes mellitus type 2", "type 2 diabetes"),
        match_codes=("44054006", "E11"),
    ),
    medication_trials=(MedicationTrialSpec("metformin_trial_months", ("metformin",)),),
)

POLICY_FHIR_MAPPINGS: tuple[PolicyFhirMapping, ...] = (T2D_FHIR_MAPPING,)


@dataclass
class FhirClinicalBundle:
    """Raw FHIR resources grouped for fact resolution."""

    observations_by_loinc: dict[str, list[dict[str, Any]]]
    conditions: list[dict[str, Any]]
    medications: list[dict[str, Any]]
    reference_date: datetime | None = None


def mapping_for_policy(policy: PayerPolicy) -> PolicyFhirMapping | None:
    """Return the FHIR mapping for a payer policy, if any."""
    drug = policy.drug.lower()
    condition = policy.condition.lower()
    for mapping in POLICY_FHIR_MAPPINGS:
        if any(keyword in drug for keyword in mapping.drug_keywords):
            return mapping
        if any(keyword in condition for keyword in mapping.condition_keywords):
            return mapping
    return None


def resolve_fhir_facts(
    mapping: PolicyFhirMapping,
    bundle: FhirClinicalBundle,
) -> dict[str, ResolvedFact]:
    """Resolve policy fields from structured FHIR resources."""
    reference = bundle.reference_date or datetime.now(tz=UTC)
    facts: dict[str, ResolvedFact] = {}

    for obs_spec in mapping.observations:
        observations = [
            Observation.model_validate(raw)
            for raw in bundle.observations_by_loinc.get(obs_spec.loinc, [])
        ]
        fact = _resolve_observation_field(obs_spec, observations)
        if fact is not None:
            facts[obs_spec.field_name] = fact

    if mapping.condition_duration is not None:
        conditions = [Condition.model_validate(raw) for raw in bundle.conditions]
        fact = _resolve_condition_duration(
            mapping.condition_duration,
            conditions,
            reference,
        )
        if fact is not None:
            facts[mapping.condition_duration.field_name] = fact

    if mapping.medication_trials:
        medications = [
            MedicationRequest.model_validate(raw) for raw in bundle.medications
        ]
        for med_spec in mapping.medication_trials:
            fact = _resolve_medication_trial(med_spec, medications, reference)
            if fact is not None:
                facts[med_spec.field_name] = fact

    return facts


def fuse_extraction_with_fhir(
    note_result: ExtractionResult,
    fhir_facts: dict[str, ResolvedFact],
    *,
    required_fields: list[str],
) -> ExtractionResult:
    """Prefer FHIR facts, then note extraction, for each required policy field."""
    extraction_data = note_result.extraction.model_dump()
    confidence = dict(note_result.field_confidence)
    evidence = dict(note_result.evidence)
    provenance = dict(note_result.field_provenance)
    needs_review = list(note_result.needs_review)

    for field in required_fields:
        if field in fhir_facts:
            fact = fhir_facts[field]
            extraction_data[field] = fact.value
            confidence[field] = fact.confidence
            evidence[field] = fact.provenance
            provenance[field] = fact.provenance
            if field in needs_review:
                needs_review.remove(field)
            continue

        value = extraction_data.get(field)
        if value is not None and field not in needs_review:
            provenance[field] = provenance.get(field) or NOTE_PROVENANCE
            if field not in evidence:
                evidence[field] = note_result.evidence.get(field, NOTE_PROVENANCE)

    from schemas.extraction import Extraction

    return ExtractionResult(
        extraction=Extraction.model_validate(extraction_data),
        field_confidence=confidence,
        needs_review=sorted(set(needs_review)),
        evidence=evidence,
        field_provenance=provenance,
        review_threshold=note_result.review_threshold,
    )


def _resolve_observation_field(
    spec: ObservationFieldSpec,
    observations: list[Observation],
) -> ResolvedFact | None:
    ranked = sorted(
        observations,
        key=_observation_sort_key,
        reverse=True,
    )
    loinc_code = _loinc_code_from_system_pipe(spec.loinc)
    for observation in ranked:
        value = _observation_numeric_value(observation)
        if value is None:
            continue
        effective = _observation_effective(observation)
        effective_label = (
            effective.date().isoformat() if effective is not None else "unknown date"
        )
        return ResolvedFact(
            field_name=spec.field_name,
            value=round(value, 2) if spec.field_name == "a1c_percent" else value,
            provenance=f"FHIR Observation {loinc_code}, effective {effective_label}",
        )
    return None


def _resolve_condition_duration(
    spec: ConditionDurationSpec,
    conditions: list[Condition],
    reference: datetime,
) -> ResolvedFact | None:
    matched: list[tuple[Condition, datetime]] = []
    for condition in conditions:
        if not _condition_matches(condition, spec):
            continue
        onset = _condition_onset(condition)
        if onset is not None:
            matched.append((condition, onset))

    if not matched:
        return None

    condition, onset = min(matched, key=lambda item: item[1])
    years = _years_between(onset, reference)
    label = _condition_label(condition)
    return ResolvedFact(
        field_name=spec.field_name,
        value=years,
        provenance=f"FHIR Condition {label}, onset {onset.date().isoformat()}",
    )


def _resolve_medication_trial(
    spec: MedicationTrialSpec,
    medications: list[MedicationRequest],
    reference: datetime,
) -> ResolvedFact | None:
    authored_dates: list[datetime] = []
    med_label = spec.match_texts[0]
    for medication in medications:
        if not _medication_matches(medication, spec.match_texts):
            continue
        authored = _medication_authored_on(medication)
        if authored is not None:
            authored_dates.append(authored)
            med_label = _medication_label(medication)

    if not authored_dates:
        return None

    start = min(authored_dates)
    months = _months_between(start, reference)
    return ResolvedFact(
        field_name=spec.field_name,
        value=months,
        provenance=(
            f"FHIR MedicationRequest {med_label}, "
            f"trial since {start.date().isoformat()}"
        ),
    )


def _observation_numeric_value(observation: Observation) -> float | None:
    if observation.valueQuantity is None or observation.valueQuantity.value is None:
        return None
    return float(observation.valueQuantity.value)


def _observation_effective(observation: Observation) -> datetime | None:
    if observation.effectiveDateTime is not None:
        return _coerce_fhir_datetime(observation.effectiveDateTime)
    if observation.effectivePeriod is not None and observation.effectivePeriod.start:
        return _coerce_fhir_datetime(observation.effectivePeriod.start)
    return None


def _observation_sort_key(observation: Observation) -> datetime:
    effective = _observation_effective(observation)
    if effective is not None:
        return effective
    return datetime.min.replace(tzinfo=UTC)


def _condition_onset(condition: Condition) -> datetime | None:
    if condition.onsetDateTime is not None:
        return _coerce_fhir_datetime(condition.onsetDateTime)
    if condition.onsetPeriod is not None and condition.onsetPeriod.start:
        return _coerce_fhir_datetime(condition.onsetPeriod.start)
    return None


def _condition_matches(condition: Condition, spec: ConditionDurationSpec) -> bool:
    text = _condition_label(condition).lower()
    if any(pattern in text for pattern in spec.match_texts):
        return "neuropathy" not in text and "prediabetes" not in text
    if condition.code is None or condition.code.coding is None:
        return False
    for coding in condition.code.coding:
        code = (coding.code or "").upper()
        if code in spec.match_codes:
            return True
    return False


def _condition_label(condition: Condition) -> str:
    if condition.code is not None and condition.code.text:
        return condition.code.text
    if condition.code is not None and condition.code.coding:
        for coding in condition.code.coding:
            if coding.display:
                return coding.display
    return "condition"


def _medication_matches(
    medication: MedicationRequest,
    patterns: tuple[str, ...],
) -> bool:
    label = _medication_label(medication).lower()
    return any(pattern in label for pattern in patterns)


def _medication_label(medication: MedicationRequest) -> str:
    concept = medication.medicationCodeableConcept
    if concept is not None and concept.text:
        return concept.text
    if concept is not None and concept.coding:
        for coding in concept.coding:
            if coding.display:
                return coding.display
    return "medication"


def _medication_authored_on(medication: MedicationRequest) -> datetime | None:
    if medication.authoredOn is None:
        return None
    return _coerce_fhir_datetime(medication.authoredOn)


def _coerce_fhir_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    return _parse_fhir_datetime(value)


def _parse_fhir_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _months_between(start: datetime, end: datetime) -> int:
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(months, 0)


def _years_between(start: datetime, end: datetime) -> int:
    years = end.year - start.year
    if (end.month, end.day) < (start.month, start.day):
        years -= 1
    return max(years, 0)


def _loinc_code_from_system_pipe(system_pipe: str) -> str:
    if "|" in system_pipe:
        return system_pipe.split("|", 1)[1]
    return system_pipe

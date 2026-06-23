"""Curated synthetic prior-auth cases with human-defined ground truth."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from schemas.cases import Case, Difficulty, ReviewCandidate
from schemas.decisions import DecisionAction
from schemas.policies import PayerPolicy

PolicyKey = Literal["ra", "t2d", "migraine"]

POLICIES: dict[PolicyKey, PayerPolicy] = {
    "ra": PayerPolicy(
        drug="adalimumab (Humira)",
        condition="rheumatoid arthritis",
        required_criteria_fields=[
            "diagnosis_confirmed",
            "disease_duration_months",
            "failed_dmards",
            "das28_score",
            "methotrexate_trial_weeks",
        ],
        rules=(
            "Coverage requires confirmed rheumatoid arthritis (ICD-10 M05/M06), "
            "disease duration of at least 6 months, failure of at least 2 "
            "conventional DMARDs, DAS28 score of at least 3.2, and a "
            "methotrexate trial of at least 12 weeks."
        ),
    ),
    "t2d": PayerPolicy(
        drug="semaglutide (Ozempic)",
        condition="type 2 diabetes",
        required_criteria_fields=[
            "a1c_percent",
            "metformin_trial_months",
            "bmi",
            "diabetes_duration_years",
        ],
        rules=(
            "Coverage requires a documented type 2 diabetes diagnosis, "
            "most recent A1C of at least 7.0%, metformin trial of at least "
            "3 months at tolerated dose, and BMI recorded in the chart."
        ),
    ),
    "migraine": PayerPolicy(
        drug="erenumab (Aimovig)",
        condition="chronic migraine",
        required_criteria_fields=[
            "migraine_days_per_month",
            "chronic_migraine_diagnosis",
            "failed_triptans",
            "preventive_trial_failed",
        ],
        rules=(
            "Coverage requires chronic migraine diagnosis, at least 15 migraine "
            "days per month, documented failure of at least 2 triptans, and "
            "failure of at least 1 preventive migraine medication."
        ),
    ),
}

RA_FIELDS = POLICIES["ra"].required_criteria_fields
T2D_FIELDS = POLICIES["t2d"].required_criteria_fields
MIGRAINE_FIELDS = POLICIES["migraine"].required_criteria_fields


def _all_present(fields: list[str]) -> dict[str, bool]:
    return dict.fromkeys(fields, True)


def _missing(fields: list[str], missing: list[str]) -> dict[str, bool]:
    missing_set = set(missing)
    return {field: field not in missing_set for field in fields}


@dataclass(frozen=True)
class SeedSpec:
    """Author-curated case with intended ground-truth label."""

    case_id: str
    policy_key: PolicyKey
    clinical_note: str
    correct_action: DecisionAction
    difficulty: Difficulty
    required_fields_present: dict[str, bool]
    fields_missing: list[str]
    label_rationale: str


def spec_to_case(spec: SeedSpec) -> Case:
    policy = POLICIES[spec.policy_key]
    return Case(
        case_id=spec.case_id,
        clinical_note=spec.clinical_note,
        payer_policy=policy,
        drug=policy.drug,
        condition=policy.condition,
    )


def spec_to_review_candidate(spec: SeedSpec) -> ReviewCandidate:
    return ReviewCandidate(
        case=spec_to_case(spec),
        proposed_action=spec.correct_action,
        proposed_rationale=spec.label_rationale,
        difficulty=spec.difficulty,
        required_fields_present=spec.required_fields_present,
        fields_missing=spec.fields_missing,
    )


def _ra_note(
    name: str,
    age: int,
    *,
    months: int | None = None,
    dmards: int | None = None,
    das28: float | None = None,
    mtx_weeks: int | None = None,
    diagnosis: bool = True,
    extra: str = "",
) -> str:
    parts = [
        "Outpatient rheumatology prior-auth request for adalimumab (Humira).",
        f"Patient: {name}, age {age}.",
    ]
    if diagnosis:
        parts.append(
            "Diagnosis: rheumatoid arthritis (ICD-10 M06.9), RF and anti-CCP positive."
        )
    else:
        parts.append("Joint pain evaluation; inflammatory arthritis suspected.")
    if months is not None:
        parts.append(f"Disease duration: {months} months.")
    if mtx_weeks is not None:
        parts.append(f"Methotrexate trial: {mtx_weeks} weeks at stable dose.")
    elif "methotrexate" in extra.lower():
        parts.append(extra)
    if dmards is not None:
        parts.append(f"Failed conventional DMARDs: {dmards} (documented trials).")
    if das28 is not None:
        parts.append(f"Today's DAS28 score: {das28}.")
    if extra and "methotrexate" not in extra.lower():
        parts.append(extra)
    parts.append("Requesting continuation authorization for Humira.")
    return " ".join(parts)


def _t2d_note(
    name: str,
    age: int,
    *,
    a1c: float | None = None,
    metformin_months: int | None = None,
    bmi: float | None = None,
    diabetes_years: int | None = None,
    extra: str = "",
) -> str:
    parts = [
        "Endocrinology prior-auth request for semaglutide (Ozempic).",
        f"Patient: {name}, age {age}.",
        "Diagnosis: type 2 diabetes mellitus (E11.9).",
    ]
    if diabetes_years is not None:
        parts.append(f"Diabetes duration: {diabetes_years} years.")
    if a1c is not None:
        parts.append(f"Most recent A1C: {a1c}%.")
    if metformin_months is not None:
        parts.append(
            f"Metformin trial: {metformin_months} months at max tolerated dose."
        )
    elif "metformin" in extra.lower():
        parts.append(extra)
    if bmi is not None:
        parts.append(f"BMI: {bmi}.")
    if extra and "metformin" not in extra.lower():
        parts.append(extra)
    parts.append("Requesting Ozempic for glycemic control.")
    return " ".join(parts)


def _migraine_note(
    name: str,
    age: int,
    *,
    days: int | None = None,
    chronic: bool | None = None,
    triptans: int | None = None,
    preventives: int | None = None,
    extra: str = "",
) -> str:
    parts = [
        "Neurology prior-auth request for erenumab (Aimovig).",
        f"Patient: {name}, age {age}.",
    ]
    if chronic is True:
        parts.append("Diagnosis: chronic migraine (G43.7).")
    elif chronic is False:
        parts.append("Diagnosis: episodic migraine without chronic migraine features.")
    if days is not None:
        parts.append(f"Migraine headache days per month: {days}.")
    if triptans is not None:
        parts.append(f"Failed triptan trials: {triptans}.")
    if preventives is not None:
        parts.append(f"Failed preventive medication trials: {preventives}.")
    if extra:
        parts.append(extra)
    parts.append("Requesting Aimovig for migraine prevention.")
    return " ".join(parts)


SEED_SPECS: list[SeedSpec] = [
    # --- RA submit (6) ---
    SeedSpec(
        "case-001",
        "ra",
        _ra_note("Jordan Blake", 52, months=14, dmards=2, das28=4.8, mtx_weeks=16),
        DecisionAction.SUBMIT,
        Difficulty.EASY,
        _all_present(RA_FIELDS),
        [],
        "All RA criteria documented and met: 14-month duration, DAS28 4.8, "
        "2 failed DMARDs, 16-week MTX trial.",
    ),
    SeedSpec(
        "case-002",
        "ra",
        _ra_note("Avery Chen", 61, months=22, dmards=3, das28=5.1, mtx_weeks=20),
        DecisionAction.SUBMIT,
        Difficulty.EASY,
        _all_present(RA_FIELDS),
        [],
        "Confirmed RA with 22-month duration, DAS28 5.1, 3 DMARD failures, 20-week MTX.",
    ),
    SeedSpec(
        "case-003",
        "ra",
        _ra_note("Morgan Ellis", 47, months=9, dmards=2, das28=3.4, mtx_weeks=14),
        DecisionAction.SUBMIT,
        Difficulty.MEDIUM,
        _all_present(RA_FIELDS),
        [],
        "Meets thresholds with 9-month duration, DAS28 3.4, 2 failed DMARDs, 14-week MTX.",
    ),
    SeedSpec(
        "case-004",
        "ra",
        _ra_note("Riley Santos", 58, months=18, dmards=2, das28=3.2, mtx_weeks=12),
        DecisionAction.SUBMIT,
        Difficulty.HARD,
        _all_present(RA_FIELDS),
        [],
        "Borderline but documented DAS28 3.2 with minimum 12-week MTX and 2 DMARD failures.",
    ),
    SeedSpec(
        "case-005",
        "ra",
        _ra_note("Casey Nguyen", 44, months=11, dmards=2, das28=4.0, mtx_weeks=15),
        DecisionAction.SUBMIT,
        Difficulty.MEDIUM,
        _all_present(RA_FIELDS),
        [],
        "All required RA fields present; DAS28 4.0 exceeds 3.2 threshold.",
    ),
    SeedSpec(
        "case-006",
        "ra",
        _ra_note("Taylor Brooks", 66, months=30, dmards=4, das28=5.6, mtx_weeks=24),
        DecisionAction.SUBMIT,
        Difficulty.EASY,
        _all_present(RA_FIELDS),
        [],
        "Strong approval: long-standing RA, high disease activity, multiple DMARD failures.",
    ),
    # --- RA request-more-info (5) ---
    SeedSpec(
        "case-007",
        "ra",
        _ra_note("Jamie Ortiz", 50, months=10, dmards=2, mtx_weeks=14),
        DecisionAction.REQUEST_MORE_INFO,
        Difficulty.EASY,
        _missing(RA_FIELDS, ["das28_score"]),
        ["das28_score"],
        "DAS28 not documented; cannot verify disease activity threshold.",
    ),
    SeedSpec(
        "case-008",
        "ra",
        _ra_note(
            "Quinn Patel",
            55,
            months=12,
            dmards=2,
            das28=4.1,
            extra="Currently on methotrexate; duration not specified.",
        ),
        DecisionAction.REQUEST_MORE_INFO,
        Difficulty.MEDIUM,
        _missing(RA_FIELDS, ["methotrexate_trial_weeks"]),
        ["methotrexate_trial_weeks"],
        "MTX mentioned without trial duration; required weeks unknown.",
    ),
    SeedSpec(
        "case-009",
        "ra",
        _ra_note("Drew Kim", 49, months=8, das28=3.8, mtx_weeks=13),
        DecisionAction.REQUEST_MORE_INFO,
        Difficulty.MEDIUM,
        _missing(RA_FIELDS, ["failed_dmards"]),
        ["failed_dmards"],
        "Disease activity documented but number of failed DMARDs not stated.",
    ),
    SeedSpec(
        "case-010",
        "ra",
        _ra_note("Skyler Reed", 53, dmards=2, das28=4.2, mtx_weeks=16),
        DecisionAction.REQUEST_MORE_INFO,
        Difficulty.EASY,
        _missing(RA_FIELDS, ["disease_duration_months"]),
        ["disease_duration_months"],
        "No disease duration documented in the note.",
    ),
    SeedSpec(
        "case-011",
        "ra",
        _ra_note(
            "Alex Mercer",
            42,
            months=7,
            dmards=2,
            das28=3.5,
            mtx_weeks=12,
            diagnosis=False,
        ),
        DecisionAction.REQUEST_MORE_INFO,
        Difficulty.HARD,
        _missing(RA_FIELDS, ["diagnosis_confirmed"]),
        ["diagnosis_confirmed"],
        "RA not confirmed; only suspected inflammatory arthritis.",
    ),
    # --- RA deny-risk (5) ---
    SeedSpec(
        "case-012",
        "ra",
        _ra_note("Sam Rivera", 57, months=10, dmards=2, das28=2.4, mtx_weeks=14),
        DecisionAction.DENY_RISK,
        Difficulty.EASY,
        _all_present(RA_FIELDS),
        [],
        "DAS28 2.4 below 3.2 activity threshold despite other criteria met.",
    ),
    SeedSpec(
        "case-013",
        "ra",
        _ra_note("Robin Hale", 48, months=12, dmards=1, das28=4.5, mtx_weeks=16),
        DecisionAction.DENY_RISK,
        Difficulty.MEDIUM,
        _all_present(RA_FIELDS),
        [],
        "Only 1 failed DMARD documented; policy requires at least 2.",
    ),
    SeedSpec(
        "case-014",
        "ra",
        _ra_note("Jesse Park", 51, months=4, dmards=2, das28=4.0, mtx_weeks=14),
        DecisionAction.DENY_RISK,
        Difficulty.EASY,
        _all_present(RA_FIELDS),
        [],
        "Disease duration 4 months; policy requires at least 6 months.",
    ),
    SeedSpec(
        "case-015",
        "ra",
        _ra_note("Cameron Lee", 60, months=15, dmards=2, das28=2.9, mtx_weeks=10),
        DecisionAction.DENY_RISK,
        Difficulty.HARD,
        _all_present(RA_FIELDS),
        [],
        "DAS28 2.9 and MTX 10 weeks both below thresholds.",
    ),
    SeedSpec(
        "case-016",
        "ra",
        _ra_note("Finley Shaw", 45, months=8, dmards=2, das28=3.0, mtx_weeks=12),
        DecisionAction.DENY_RISK,
        Difficulty.HARD,
        _all_present(RA_FIELDS),
        [],
        "Borderline DAS28 3.0 below 3.2 cutoff; likely denial risk.",
    ),
    # --- T2D submit (6) ---
    SeedSpec(
        "case-017",
        "t2d",
        _t2d_note(
            "Harper Wells", 54, a1c=8.2, metformin_months=6, bmi=33.1, diabetes_years=5
        ),
        DecisionAction.SUBMIT,
        Difficulty.EASY,
        _all_present(T2D_FIELDS),
        [],
        "A1C 8.2%, 6-month metformin, BMI documented; all criteria met.",
    ),
    SeedSpec(
        "case-018",
        "t2d",
        _t2d_note(
            "Logan Price", 62, a1c=7.4, metformin_months=4, bmi=29.0, diabetes_years=8
        ),
        DecisionAction.SUBMIT,
        Difficulty.EASY,
        _all_present(T2D_FIELDS),
        [],
        "A1C 7.4% with adequate metformin trial and documented BMI.",
    ),
    SeedSpec(
        "case-019",
        "t2d",
        _t2d_note(
            "Parker Dunn", 49, a1c=7.0, metformin_months=3, bmi=31.5, diabetes_years=3
        ),
        DecisionAction.SUBMIT,
        Difficulty.HARD,
        _all_present(T2D_FIELDS),
        [],
        "Borderline A1C exactly 7.0% with minimum 3-month metformin; criteria met.",
    ),
    SeedSpec(
        "case-020",
        "t2d",
        _t2d_note(
            "Reese Holland",
            58,
            a1c=9.1,
            metformin_months=12,
            bmi=36.4,
            diabetes_years=10,
        ),
        DecisionAction.SUBMIT,
        Difficulty.EASY,
        _all_present(T2D_FIELDS),
        [],
        "Clearly elevated A1C with long metformin trial and BMI on file.",
    ),
    SeedSpec(
        "case-021",
        "t2d",
        _t2d_note(
            "Sage Monroe", 51, a1c=7.8, metformin_months=5, bmi=28.2, diabetes_years=6
        ),
        DecisionAction.SUBMIT,
        Difficulty.MEDIUM,
        _all_present(T2D_FIELDS),
        [],
        "All T2D fields present; A1C and metformin duration exceed minimums.",
    ),
    SeedSpec(
        "case-022",
        "t2d",
        _t2d_note(
            "Blair Tate", 67, a1c=8.5, metformin_months=9, bmi=34.0, diabetes_years=12
        ),
        DecisionAction.SUBMIT,
        Difficulty.MEDIUM,
        _all_present(T2D_FIELDS),
        [],
        "Documented uncontrolled diabetes with adequate metformin trial.",
    ),
    # --- T2D request-more-info (5) ---
    SeedSpec(
        "case-023",
        "t2d",
        _t2d_note("Emery Fox", 56, metformin_months=6, bmi=30.2, diabetes_years=4),
        DecisionAction.REQUEST_MORE_INFO,
        Difficulty.EASY,
        _missing(T2D_FIELDS, ["a1c_percent"]),
        ["a1c_percent"],
        "No A1C value in note; cannot assess glycemic threshold.",
    ),
    SeedSpec(
        "case-024",
        "t2d",
        _t2d_note("Rowan Gray", 59, a1c=7.6, metformin_months=5, diabetes_years=7),
        DecisionAction.REQUEST_MORE_INFO,
        Difficulty.EASY,
        _missing(T2D_FIELDS, ["bmi"]),
        ["bmi"],
        "BMI not documented in the clinical note.",
    ),
    SeedSpec(
        "case-025",
        "t2d",
        _t2d_note(
            "Indigo Shaw",
            52,
            a1c=8.0,
            bmi=32.0,
            diabetes_years=5,
            extra="Patient reports taking metformin; duration unclear.",
        ),
        DecisionAction.REQUEST_MORE_INFO,
        Difficulty.MEDIUM,
        _missing(T2D_FIELDS, ["metformin_trial_months"]),
        ["metformin_trial_months"],
        "Metformin use mentioned without quantified trial duration.",
    ),
    SeedSpec(
        "case-026",
        "t2d",
        _t2d_note("Marlowe Kent", 63, a1c=7.2, metformin_months=4, bmi=27.8),
        DecisionAction.REQUEST_MORE_INFO,
        Difficulty.MEDIUM,
        _missing(T2D_FIELDS, ["diabetes_duration_years"]),
        ["diabetes_duration_years"],
        "Diabetes duration not stated.",
    ),
    SeedSpec(
        "case-027",
        "t2d",
        _t2d_note(
            "Phoenix Reid",
            48,
            a1c=7.5,
            metformin_months=6,
            bmi=29.5,
            extra="Chart lists diabetes but onset date not documented.",
        ),
        DecisionAction.REQUEST_MORE_INFO,
        Difficulty.HARD,
        _missing(T2D_FIELDS, ["diabetes_duration_years"]),
        ["diabetes_duration_years"],
        "Diabetes mentioned without duration/years on record.",
    ),
    # --- T2D deny-risk (5) ---
    SeedSpec(
        "case-028",
        "t2d",
        _t2d_note(
            "River Stone", 55, a1c=6.4, metformin_months=8, bmi=31.0, diabetes_years=5
        ),
        DecisionAction.DENY_RISK,
        Difficulty.EASY,
        _all_present(T2D_FIELDS),
        [],
        "A1C 6.4% below 7.0% coverage threshold.",
    ),
    SeedSpec(
        "case-029",
        "t2d",
        _t2d_note(
            "Sloane Hart", 60, a1c=7.8, metformin_months=1, bmi=33.5, diabetes_years=9
        ),
        DecisionAction.DENY_RISK,
        Difficulty.MEDIUM,
        _all_present(T2D_FIELDS),
        [],
        "Metformin trial only 1 month; policy requires at least 3 months.",
    ),
    SeedSpec(
        "case-030",
        "t2d",
        _t2d_note(
            "Aspen Cole", 50, a1c=6.9, metformin_months=6, bmi=28.0, diabetes_years=4
        ),
        DecisionAction.DENY_RISK,
        Difficulty.HARD,
        _all_present(T2D_FIELDS),
        [],
        "Borderline A1C 6.9% below 7.0% requirement.",
    ),
    SeedSpec(
        "case-031",
        "t2d",
        _t2d_note(
            "Winter Lane", 64, a1c=7.1, metformin_months=2, bmi=30.5, diabetes_years=11
        ),
        DecisionAction.DENY_RISK,
        Difficulty.MEDIUM,
        _all_present(T2D_FIELDS),
        [],
        "A1C qualifies but metformin duration insufficient at 2 months.",
    ),
    SeedSpec(
        "case-032",
        "t2d",
        _t2d_note(
            "Eden Marsh", 57, a1c=6.8, metformin_months=5, bmi=32.2, diabetes_years=6
        ),
        DecisionAction.DENY_RISK,
        Difficulty.HARD,
        _all_present(T2D_FIELDS),
        [],
        "Glycemic control appears adequate at A1C 6.8%; unlikely to meet medical necessity.",
    ),
    # --- Migraine submit (5) ---
    SeedSpec(
        "case-033",
        "migraine",
        _migraine_note(
            "Nova Bell", 38, days=18, chronic=True, triptans=2, preventives=1
        ),
        DecisionAction.SUBMIT,
        Difficulty.EASY,
        _all_present(MIGRAINE_FIELDS),
        [],
        "18 headache days/month with chronic migraine and failed triptans/preventive.",
    ),
    SeedSpec(
        "case-034",
        "migraine",
        _migraine_note(
            "Luna Pierce", 45, days=20, chronic=True, triptans=3, preventives=2
        ),
        DecisionAction.SUBMIT,
        Difficulty.EASY,
        _all_present(MIGRAINE_FIELDS),
        [],
        "Clearly meets chronic migraine frequency and failure requirements.",
    ),
    SeedSpec(
        "case-035",
        "migraine",
        _migraine_note(
            "Stella Crane", 41, days=15, chronic=True, triptans=2, preventives=1
        ),
        DecisionAction.SUBMIT,
        Difficulty.HARD,
        _all_present(MIGRAINE_FIELDS),
        [],
        "Exactly 15 days/month at threshold with required failures documented.",
    ),
    SeedSpec(
        "case-036",
        "migraine",
        _migraine_note(
            "Ivy Nolan", 50, days=16, chronic=True, triptans=2, preventives=1
        ),
        DecisionAction.SUBMIT,
        Difficulty.MEDIUM,
        _all_present(MIGRAINE_FIELDS),
        [],
        "16 migraine days/month exceeds minimum with chronic diagnosis confirmed.",
    ),
    SeedSpec(
        "case-037",
        "migraine",
        _migraine_note(
            "Wren Dalton", 36, days=22, chronic=True, triptans=2, preventives=2
        ),
        DecisionAction.SUBMIT,
        Difficulty.MEDIUM,
        _all_present(MIGRAINE_FIELDS),
        [],
        "High-frequency chronic migraine with multiple failed therapies.",
    ),
    # --- Migraine request-more-info (6) ---
    SeedSpec(
        "case-038",
        "migraine",
        _migraine_note("Cleo Banks", 43, chronic=True, triptans=2, preventives=1),
        DecisionAction.REQUEST_MORE_INFO,
        Difficulty.EASY,
        _missing(MIGRAINE_FIELDS, ["migraine_days_per_month"]),
        ["migraine_days_per_month"],
        "Headache frequency not quantified per month.",
    ),
    SeedSpec(
        "case-039",
        "migraine",
        _migraine_note("Mila Torres", 47, days=17, triptans=2, preventives=1),
        DecisionAction.REQUEST_MORE_INFO,
        Difficulty.MEDIUM,
        _missing(MIGRAINE_FIELDS, ["chronic_migraine_diagnosis"]),
        ["chronic_migraine_diagnosis"],
        "Headache days documented but chronic migraine diagnosis not confirmed.",
    ),
    SeedSpec(
        "case-040",
        "migraine",
        _migraine_note("Nora Finch", 39, days=19, chronic=True, preventives=1),
        DecisionAction.REQUEST_MORE_INFO,
        Difficulty.EASY,
        _missing(MIGRAINE_FIELDS, ["failed_triptans"]),
        ["failed_triptans"],
        "Triptan failure count not documented.",
    ),
    SeedSpec(
        "case-041",
        "migraine",
        _migraine_note("Ella Moss", 52, days=16, chronic=True, triptans=2),
        DecisionAction.REQUEST_MORE_INFO,
        Difficulty.MEDIUM,
        _missing(MIGRAINE_FIELDS, ["preventive_trial_failed"]),
        ["preventive_trial_failed"],
        "No preventive medication trial failures documented.",
    ),
    SeedSpec(
        "case-042",
        "migraine",
        _migraine_note(
            "Zoe Hart",
            44,
            days=18,
            chronic=True,
            extra="Has tried sumatriptan; other triptan trials not listed.",
        ),
        DecisionAction.REQUEST_MORE_INFO,
        Difficulty.HARD,
        _missing(MIGRAINE_FIELDS, ["failed_triptans"]),
        ["failed_triptans"],
        "Only one triptan named; total failures ambiguous for policy count.",
    ),
    SeedSpec(
        "case-043",
        "migraine",
        _migraine_note("Aria Quinn", 46, days=21, triptans=2),
        DecisionAction.REQUEST_MORE_INFO,
        Difficulty.HARD,
        _missing(
            MIGRAINE_FIELDS, ["chronic_migraine_diagnosis", "preventive_trial_failed"]
        ),
        ["chronic_migraine_diagnosis", "preventive_trial_failed"],
        "High frequency noted but chronic diagnosis and preventive failures missing.",
    ),
    # --- Migraine deny-risk (5) ---
    SeedSpec(
        "case-044",
        "migraine",
        _migraine_note(
            "Faye Knox", 40, days=8, chronic=True, triptans=2, preventives=1
        ),
        DecisionAction.DENY_RISK,
        Difficulty.EASY,
        _all_present(MIGRAINE_FIELDS),
        [],
        "Only 8 headache days/month; below 15-day chronic migraine threshold.",
    ),
    SeedSpec(
        "case-045",
        "migraine",
        _migraine_note(
            "Greta Lowe", 48, days=16, chronic=False, triptans=2, preventives=1
        ),
        DecisionAction.DENY_RISK,
        Difficulty.MEDIUM,
        _all_present(MIGRAINE_FIELDS),
        [],
        "Episodic migraine diagnosis; policy requires chronic migraine.",
    ),
    SeedSpec(
        "case-046",
        "migraine",
        _migraine_note(
            "Hazel Voss", 42, days=17, chronic=True, triptans=1, preventives=1
        ),
        DecisionAction.DENY_RISK,
        Difficulty.MEDIUM,
        _all_present(MIGRAINE_FIELDS),
        [],
        "Only 1 failed triptan; policy requires at least 2.",
    ),
    SeedSpec(
        "case-047",
        "migraine",
        _migraine_note(
            "Iris Boone", 37, days=14, chronic=True, triptans=2, preventives=1
        ),
        DecisionAction.DENY_RISK,
        Difficulty.HARD,
        _all_present(MIGRAINE_FIELDS),
        [],
        "Borderline 14 days/month below 15-day requirement.",
    ),
    SeedSpec(
        "case-048",
        "migraine",
        _migraine_note(
            "Jade Poole", 55, days=18, chronic=True, triptans=2, preventives=0
        ),
        DecisionAction.DENY_RISK,
        Difficulty.EASY,
        _all_present(MIGRAINE_FIELDS),
        [],
        "No failed preventive trials documented (0); policy requires at least 1.",
    ),
]

assert len(SEED_SPECS) == 48

_ACTION_COUNTS = {
    action: sum(1 for spec in SEED_SPECS if spec.correct_action == action)
    for action in DecisionAction
}
assert _ACTION_COUNTS[DecisionAction.SUBMIT] == 17
assert _ACTION_COUNTS[DecisionAction.REQUEST_MORE_INFO] == 16
assert _ACTION_COUNTS[DecisionAction.DENY_RISK] == 15

# Labeling Rubric — Prior-Auth Triage Ground Truth

Use this rubric when reviewing proposed labels in `data/_review/candidates.json`.
**Final labels in `data/labels/labels.json` must be human-confirmed** — do not accept
LLM-proposed labels without checking against these rules.

## Required first step

For each case, mark each `PayerPolicy.required_criteria_fields` entry as present/absent in
`required_fields_present`. List absent or ambiguous fields in `fields_missing`.

## `submit`

Assign **submit** when **all** of the following hold:

1. Every required policy field is **present and unambiguous** in the clinical note.
2. Documented values **meet** payer thresholds in the policy `rules` text.
3. No conflicting evidence remains unresolved.

Examples: DAS28 ≥ 3.2 with ≥ 2 failed DMARDs and ≥ 12 weeks MTX; A1C ≥ 7.0% with ≥ 3 months
metformin; ≥ 15 headache days/month with chronic migraine diagnosis and failed triptans/preventive.

## `request-more-info`

Assign **request-more-info** when:

1. At least one **required** field is **missing** from the note, **or**
2. A required field is **ambiguous** (mentioned but not quantified, or contradictory).

Do **not** use this label when values are clear but fail thresholds — that is `deny-risk`.

Examples: no DAS28 documented; “on methotrexate” without duration; BMI not stated.

## `deny-risk`

Assign **deny-risk** when:

1. Required fields are sufficiently present to evaluate criteria, **and**
2. Documented facts **fail** one or more payer thresholds (likely payer denial).

Examples: DAS28 2.4; A1C 6.4%; 8 headache days/month; only 1 DMARD failure when 2 required.

## Difficulty tags

| Tag | Guidance |
|-----|----------|
| **easy** | Clear-cut label; single obvious criterion drives the decision. |
| **medium** | Multiple criteria interact, or one borderline value is clearly on one side. |
| **hard** | Borderline thresholds, ambiguous wording, or conflicting secondary details. |

## `label_rationale`

Write one or two sentences citing **specific fields and values** from the note that justify the
label. Reference payer rule text when helpful.

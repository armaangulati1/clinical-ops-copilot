# Specialty Medication Prior Authorization — Workflow Spec

## Setting

Automated triage of **specialty-medication prior-authorization (PA)** requests in an
outpatient clinic. Phase 1 covers three synthetic drug/condition pairs:

| Drug | Condition |
|------|-----------|
| adalimumab (Humira) | Rheumatoid arthritis |
| semaglutide (Ozempic) | Type 2 diabetes |
| erenumab (Aimovig) | Chronic migraine |

All data is **synthetic**; no real PHI is used.

## Workflow states

```
received → extracted → criteria-checked → decided → actioned
```

| State | Description |
|-------|-------------|
| **received** | PA request arrives with a clinical note, drug, condition, and payer policy. |
| **extracted** | Structured clinical fields are pulled from the free-text note (`Extraction`). |
| **criteria-checked** | Extracted fields are compared against `PayerPolicy.required_criteria_fields`. |
| **decided** | Agent emits a `Decision` (action, confidence, rationale, missing_fields). |
| **actioned** | Downstream `Action` is prepared (draft submission, info request, or review flag). |

Human review may interrupt the flow after **decided** when confidence is low (see below).

## Decision options

| Action | Meaning | Typical downstream `Action` |
|--------|---------|----------------------------|
| **submit** | Documented clinical facts **clearly meet** payer policy criteria. All required fields are present, unambiguous, and satisfy thresholds. | `draft_submission` |
| **request-more-info** | At least one **required** policy field is **missing or ambiguous** in the note. Criteria cannot be evaluated yet. | `request_info_email` |
| **deny-risk** | Facts are present enough to evaluate, but **do not meet** criteria (likely payer denial). Flag for human review before sending a denial. | `flag_for_review` |

## Low confidence

A decision is **low confidence** (human review required in later phases) when any of:

1. **Missing required fields** — one or more `PayerPolicy.required_criteria_fields` cannot be extracted with certainty.
2. **Conflicting evidence** — the note contains contradictory values (e.g., two different A1C results with no reconciliation).
3. **Borderline criteria** — values within a documented margin of payer thresholds (e.g., DAS28 3.1 vs 3.2 cutoff, A1C 6.9–7.0, exactly 15 headache days/month).

Low confidence does **not** automatically change the triage class; it triggers review **in addition to** the chosen action. A `deny-risk` at 0.55 confidence and a `submit` at 0.52 confidence both require human sign-off.

## Phase 1 scope

Phase 1 defines domain models, a labeled synthetic dataset, and review tooling. No MCP servers,
agent orchestration, or approval UI are implemented yet.

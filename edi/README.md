# X12 278 prior-authorization layer

A hand-rolled X12 278 (**005010X217**) health-care-services-review layer wired
onto the existing prior-auth agent: it **parses** a 278 REQUEST into the agent's
`Case` input, runs the same decision pipeline, and **generates** a 278 RESPONSE
from the agent's decision.

## Honest scope

- **Simplified subset** of the 005010X217 implementation guide. Only the
  segments the agent actually needs are mapped; everything else is tolerated and
  ignored, not validated.
- **Synthetic data only.** Fixtures are derived from the repo's synthetic
  Synthea/HAPI cases. No PHI, no real 278 traffic.
- **Not HIPAA-certified EDI tooling.** No SNIP-level compliance validation, no
  TA1/999 acknowledgements, no real payer companion-guide conformance. This is a
  demo/portfolio interoperability layer, not a clearinghouse.
- Hand-rolled tokenizer and parser (no EDI dependency), so the delimiter and
  envelope handling is explicit and readable.

## Supported segment subset (REQUEST → `Case`)

Delimiters are resolved from the ISA header by fixed position (element, ISA11
repetition, ISA16 component, and the segment terminator that follows ISA16),
the canonical X12 bootstrap.

| Segment | Purpose | Elements used | Maps to |
|---------|---------|---------------|---------|
| `ISA` | Interchange header | delimiters (positional) | envelope / delimiters |
| `GS` / `ST` | Functional group / transaction set | `ST01=278` | envelope |
| `BHT` | Beginning of hierarchical transaction | `BHT03` | `Case.case_id` |
| `HL` | Hierarchical loops (20/21/22/EV) | level code | loop structure |
| `NM1*PR` | Payer (information source) | name | `payer_name` |
| `NM1*1P` | Requesting provider | name, `XX`+NPI | `provider` |
| `NM1*IL` | Subscriber / patient | name, `MI`+member id | `patient` / `Case.patient_id` |
| `UM` | Services review info | `UM01` category, `UM02` cert type, `UM03` service type | request metadata (**required**) |
| `DTP*472` | Service date | `D8` date | `service_date` |
| `HI` | Diagnosis | `ABK`/`ABF`/`BK`/`BF` + ICD-10-CM code | `diagnosis_codes` |
| `MSG` | Message text | free-form (≤264 chars/segment) | `Case.clinical_note` (concatenated) |
| `REF*ZZ` | Mutually-defined reference | `REF02` value, `REF03` tag | see demo carriers |
| `SE` / `GE` / `IEA` | Trailers | (counts only) | envelope |

**Required segments:** `ST`, `BHT`, `UM`. Absence raises `MissingSegmentError`.

**Mapping guards:** `Request278.to_case()` rejects a request whose concatenated
`MSG` narrative is under 50 characters (the `Case.clinical_note` minimum), along
with a missing `BHT03` case reference or missing drug/condition `REF` carriers,
raising `InvalidSegmentError`. The `Case` produced by the parser carries a
**placeholder** `payer_policy` object (drug and condition only); the agent
re-looks-up the authoritative policy from the clinical-data service, so
`case.payer_policy` from the parser must not be consumed as real policy content
downstream.

### Two documented demo simplifications

1. **Clinical narrative in `MSG`.** A real 278 references supporting clinical
   documentation as an attachment (PWK / 275), not inline. For the demo the full
   note is carried across one or more `MSG` segments (X12 `MSG01` max 264 chars)
   and concatenated on ingestion, so the same downstream extractor runs unchanged.
2. **`REF*ZZ` policy-lookup carriers.** The requested drug name and condition
   text are carried verbatim in `REF*ZZ` segments tagged in `REF03`
   (`DRUG` / `CONDITION`). The agent looks up the authoritative payer policy from
   the clinical-data service keyed on the **exact** drug + condition strings, so
   the 278 carries those keys directly. A real integration would resolve
   codes (HI diagnosis, service/procedure codes) to policy keys via a
   terminology service instead.

## Decision → HCR mapping (RESPONSE)

The agent emits one of three internal decisions; each maps to an HCR (Health
Care Services Review) action code. Single source of truth: `edi/decision_map.py`.

**Role framing:** the agent's decisions are provider-side. A 278 RESPONSE
(HCR A1/A4) is issued by the payer/UMO side, so the response generator
**simulates the utilization-review side** for demo purposes, showing what a
payer-side determination would look like given the agent's assessment. It is
pre-adjudication demo output, not a claim that the agent is a
utilization-management organization or issues real determinations.

| Agent decision | HCR01 action | Label | Rationale |
|----------------|--------------|-------|-----------|
| `submit` | `A1` | Certified in Total | Required criteria met; cleared to submit. |
| `request-more-info` | `A4` | Pended | Additional documentation required before a determination. |
| `deny-risk` | `A4` | Pended | **Not A3.** `deny-risk` is a risk flag behind a human approval gate, not a denial authority, so it pends for human review with a distinct reason. Only a human downstream can issue `A3` (Not Certified). |

This mapping is deliberately conservative: the automated layer never issues a
denial (`A3`). It certifies clear approvals, pends everything else.

## Fixtures

`edi/fixtures/*.278`, synthetic, committed:

- 8 well-formed requests across all three policy families (RA/adalimumab,
  T2D/semaglutide, migraine/erenumab) and all three decision outcomes, plus a
  `*_with_patient_id` variant that exercises the `NM1*IL` member-id round-trip.
- 4 malformed requests: `malformed_empty`, `malformed_truncated_isa`,
  `malformed_wrong_delimiters` (non-distinct ISA delimiters), `malformed_missing_um`.

## Eval wire-in

`python -m edi.eval_agreement` runs the **locked** held-out split's cases through
both ingestion paths and reports decision agreement:

- **native path:** `Case` from JSON, then the offline decision pipeline.
- **278 path:** `Case`, encode 278, parse 278, back to `Case`, then the same pipeline.

The pipeline is deterministic and offline (regex extractor + `StubPlanner` + the
repo's real required-field guardrail, not a test double), so the number is
reproducible in CI without network or API keys and isolates the EDI ingestion
layer from planner nondeterminism. The locked split file and its labels are
read-only; labels are never consulted. This measures **ingestion fidelity**
(does encoding to and parsing from 278 change the agent's decision?), not
clinical correctness versus ground truth.

Current result: **16/16 (100%)** decision agreement on the locked split, so the
EDI round-trip preserves every decision. The round-trip uses the repo's own
encoder, so this is a self-consistency test of the parser and mapping, not
third-party 278 conformance. On this split the offline decider produces 12
`submit` and 4 `request-more-info` decisions and 0 `deny-risk`, so the eval
exercises only the submit and request-more-info classes under the offline
decider. The `deny-risk` to A4 mapping is covered by unit tests, not by this
eval.

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

## Invented carrier segments

Several layers in this package need to put a self-authored vocabulary on the
wire. They deliberately do not reuse the real X12 segments that would normally
carry that content (`EB`, `AAA`, `STC`, `CAS`), because those segments imply
externally maintained code lists this project does not reproduce. So they emit
**invented carrier segments** instead.

Single source of truth: `edi/invented_segments.py`.

| Carrier | Layer | Carries | Stands in for |
|---------|-------|---------|---------------|
| `ZEBC` | 271 | self-authored `EB-*` benefit outcome | real `EB` |
| `ZRJC` | 271, 277 | self-authored `RJ-*` reject reason | real `AAA` |
| `ZCSI` | 277 | self-authored `CS-*` claim status | real `STC` |
| `DRC` | 835 | self-authored `DR-*` denial reason | real `CAS` (CARC/RARC) |

**Why the IDs are four characters.** An X12 segment identifier is two or three
characters. A four-character ID is therefore not a valid X12 segment ID and
cannot collide with any segment in any X12 transaction set. That is a structural
guarantee rather than a lookup, which matters: an earlier revision of this
package used `CSI` and asserted in four places that it was "not a real X12
segment". **That was wrong.** `CSI` is a real X12 segment ("Claim Status
Information", transaction set 260). The carriers were renamed so the claim rests
on a length rule instead of on anyone's recollection of the standard.

The two-or-three-character rule is **normative X12 syntax**, not an empirical
observation of some published list: the interchange syntax every HIPAA
implementation guide builds on defines a segment identifier as two or three
uppercase alphanumeric characters. `CSI` is well formed under that rule, which
is precisely why the earlier "not a real segment" assertion about it was unsafe.
`ZEBC`, `ZRJC` and `ZCSI` are four characters, so no conformant X12 grammar can
admit them as segment IDs at all. The guarantee is checkable from the syntax
rule itself, with no third-party list in the middle.

**A four-character segment ID is invalid X12 by construction, and that is the
point.** This package emits demo-shaped interchanges, not conformant EDI. An ID
no parser can mistake for a standard segment makes the non-conformance visible
on the wire rather than only in a README. None of this output is
clearinghouse-ready.

`DRC` is the one exception: it predates this rule and already ships on `main`,
so it keeps its three-character ID. Three characters is a well-formed segment ID,
so the length guarantee does **not** cover `DRC`. It was checked against a
published X12 segment directory on 2026-07-28 and found absent. That is a lookup,
and a lookup is weaker evidence than a syntax rule. It is recorded here as the
weaker claim it is.

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

---

# X12 835 denial-triage demo

A second, independent demo layer over the same hand-rolled tokenizer/error core:
it **parses** a self-authored X12 835 (claim payment / remittance advice) subset
into typed claims, then runs a **deterministic denial-triage** step that
recommends a next action per claim. Additive and standalone; it does not touch
the 278 layer or the agent decision path.

- `edi/x12_835.py` - parser: 835-shaped interchange to a `RemittanceAdvice`
  (`claims: [{claim_ref, status, billed, paid, service_lines, denial_codes}]`).
- `edi/denial_triage.py` - transparent rules over the parsed denials.
- `edi/eval_triage.py` - `python -m edi.eval_triage`: exact-match + per-class
  precision/recall on the fixture set.

## Honest scope

- **Self-authored subset**, not the real 005010X221 implementation guide. The
  envelope/claim shapes (`ISA`/`GS`/`ST`/`BPR`/`TRN`/`CLP`/`SVC`) are modeled at
  subset level; everything else is tolerated and ignored, not validated.
- **Invented denial-code system.** Real 835 remittances carry adjustment reasons
  in `CAS` segments using externally maintained **CARC/RARC** code lists. This
  demo deliberately does **not** reproduce any of that content. It carries denial
  reasons in an **invented `DRC` segment** using a small self-authored `DR-*`
  vocabulary. No real CARC/RARC/CAS content appears anywhere, and the triage table
  is not a model of any real payer's denial logic. `DRC` is the one invented
  carrier here that predates the four-character rule; it was verified absent from
  the published X12 segment directory on 2026-07-28 (see
  [Invented carrier segments](#invented-carrier-segments)).
- **Synthetic, self-authored data only.** Every fixture is hand-authored; no PHI,
  no real payer traffic, **not affiliated with any company, payer, or product.**
- **Simulation of the provider-side remittance-review step**, for demo purposes.
  Not HIPAA-certified EDI tooling; issues no real determinations.

## Supported segment subset (835 -> `RemittanceAdvice`)

Delimiters are resolved from the ISA header by fixed position (the same canonical
X12 bootstrap the 278 layer uses).

| Segment | Purpose | Elements used | Maps to |
|---------|---------|---------------|---------|
| `ISA` | Interchange header | delimiters (positional) | envelope / delimiters |
| `GS` / `ST` | Functional group / transaction set | `ST01=835` | envelope |
| `BPR` | Financial information | `BPR02` total paid | `total_paid` (optional) |
| `TRN` | Reassociation trace | `TRN02` | `trace_number` |
| `CLP` | Claim payment info | ref, status, billed, paid, patient resp | `ClaimPayment` (**required**) |
| `SVC` | Service-line payment | `PROC-*` id, billed, paid | `ServiceLine` |
| `DRC` | **Invented** denial-reason carrier | `DR-*` code, free text | `denial_codes` (claim- or line-level) |
| `SE` / `GE` / `IEA` | Trailers | (counts only) | envelope |

**Required segments:** `ST`, `CLP`. Absence raises `MissingSegmentError`.
Monetary elements are parsed to `Decimal`; a non-numeric amount raises
`InvalidSegmentError`. Malformed input (empty, truncated ISA, non-distinct
delimiters, missing `CLP`) raises a structured `X12ParseError` subclass, never a
crash. Status tokens (`PAID`/`PART`/`DENY`), `PROC-*` service ids, and `DR-*`
denial codes are all self-authored, so no real CPT/HCPCS or CARC/RARC content is
present. A `DRC` after a `SVC` attaches to that service line; a `DRC` before any
`SVC` attaches to the claim.

## Self-authored denial-code table and triage rules

Single source of truth: `edi/denial_triage.py`. **These are invented demo codes,
not real CARC/RARC.**

| Denial code (invented) | Recommendation | Rationale |
|------------------------|----------------|-----------|
| `DR-DOC-MISSING` | `resubmit-with-documentation` | Supporting documentation absent; attach and resubmit. |
| `DR-AUTH-ABSENT` | `resubmit-with-documentation` | Prior authorization not on file; obtain and resubmit. |
| `DR-CODE-INVALID` | `correct-and-rebill` | Service code invalid/mismatched; correct and rebill. |
| `DR-ELIG-LAPSED` | `correct-and-rebill` | Member eligibility data stale; verify and rebill corrected. |
| `DR-DUPLICATE` | `needs-human-review` | Flagged as a duplicate; human confirms before any action. |
| `DR-COORD-BENEFITS` | `needs-human-review` | Coordination-of-benefits / other-payer issue; human review. |

Rules are transparent (no scoring model, no LLM): the recommendation is a pure
function of the denial codes present. When a claim carries several codes, the
**most conservative** recommendation wins:
`needs-human-review` > `correct-and-rebill` > `resubmit-with-documentation` >
`no-action`. A paid-in-full claim with no denial reasons is `no-action`. Two fail-
safe cases route to `needs-human-review`: an **unrecognized** denial code, and an
**underpayment with no coded reason** (never guess, never fail silent).

## Fixtures

`edi/fixtures/x835/*.835`, synthetic, committed: 6 well-formed remittances
covering every outcome (paid-in-full, partial, denied single-reason, denied
multi-reason, a multi-claim batch mixing outcomes, and claim- vs line-level
denial codes) plus 4 malformed inputs (`malformed_empty`,
`malformed_truncated_isa`, `malformed_wrong_delimiters`, `malformed_missing_clp`).
Golden triage outputs live in `edi/fixtures/x835/golden.json`.

## Eval

`python -m edi.eval_triage` parses each well-formed fixture, triages every claim,
and scores against the golden file. On its **9-claim self-authored fixture set**
the triage reaches **9/9 (100%) exact-match**, with precision and recall of
**1.000** for each of the four recommendation classes:

| Recommendation | Precision | Recall | Support |
|----------------|-----------|--------|---------|
| `no-action` | 1.000 | 1.000 | 2 |
| `resubmit-with-documentation` | 1.000 | 1.000 | 3 |
| `correct-and-rebill` | 1.000 | 1.000 | 2 |
| `needs-human-review` | 1.000 | 1.000 | 2 |

This measures that the rules-driven triage reproduces the intended recommendation
on hand-authored synthetic remittances. It is **not** a claim of accuracy against
real payer remittances or against real CARC/RARC denial semantics.

---

# X12 270/271 eligibility demo

A third demo layer over the same hand-rolled tokenizer/error core: it **parses**
a self-authored X12 270 (health-care eligibility/benefit **inquiry**) subset into
a typed inquiry, then runs a **deterministic responder** that resolves a benefit
outcome per requested service type from the repo's own synthetic coverage table
and emits a **271-shaped response**. Additive and standalone; it does not touch
the 278, the 835, or the agent decision path.

- `edi/x12_270.py` - parser: 270-shaped interchange to an `EligibilityInquiry`
  (subscriber, provider, payer, requested service types, service date).
- `edi/eligibility_271.py` - synthetic coverage table, the resolution rules, and
  the 271 response generator.
- `edi/eval_eligibility.py` - `python -m edi.eval_eligibility`: exact-match +
  per-outcome precision/recall on the fixture set.

## Honest scope

- **Self-authored subset**, not the real 005010X279 implementation guide. The
  envelope/inquiry shapes (`ISA`/`GS`/`ST`/`BHT`/`HL`/`NM1`/`DMG`/`DTP`/`EQ`) are
  modeled at subset level; everything else is tolerated and ignored, not validated.
- **Invented code systems.** Real 270 inquiries name a service type in `EQ01`
  from an externally maintained code list, real 271 responses report benefits in
  `EB` segments from another, and both report rejects in `AAA` segments from a
  third. This demo deliberately reproduces **none** of that content. It uses a
  self-authored `SRV-*` service-type vocabulary, a self-authored `EB-*` outcome
  vocabulary carried in an **invented `ZEBC` segment**, and self-authored `RJ-*`
  reject reasons carried in an **invented `ZRJC` segment**. Both carrier IDs are
  four characters, and an X12 segment ID is two or three, so neither can name a
  real segment (see [Invented carrier segments](#invented-carrier-segments)). A
  test asserts the demo emits no `EB*`, `AAA*`, or `STC*` segment anywhere.
- **Synthetic, self-authored data only.** Every fixture, member, plan, and amount
  is hand-authored; no PHI, no real payer traffic, **not affiliated with any
  company, payer, or product.**
- **The responder simulates the payer side**, for demo purposes. It is not
  HIPAA-certified EDI tooling, it is **not a clearinghouse integration**, and it
  issues no real coverage determinations.

## Supported segment subset (270 -> `EligibilityInquiry`)

Delimiters are resolved from the ISA header by fixed position (the same canonical
X12 bootstrap the 278 and 835 layers use).

| Segment | Purpose | Elements used | Maps to |
|---------|---------|---------------|---------|
| `ISA` | Interchange header | delimiters (positional) | envelope / delimiters |
| `GS` / `ST` | Functional group / transaction set | `ST01=270` | envelope |
| `BHT` | Beginning of hierarchical transaction | `BHT03` | `submitter_reference` |
| `HL` | Hierarchical loops (20/21/22) | level code | loop structure |
| `NM1*PR` | Payer (information source) | name | `payer_name` |
| `NM1*1P` | Information receiver / provider | name, `XX`+NPI | `provider` |
| `NM1*IL` | Subscriber | name, `MI`+member id | `subscriber` |
| `DMG` | Subscriber demographics | `D8` birth date, gender (verbatim) | `subscriber` |
| `DTP*472` | Service date | `D8` date | `service_date` |
| `EQ` | Benefit inquiry line | `EQ01` self-authored `SRV-*` (**required**) | `service_types` |
| `SE` / `GE` / `IEA` | Trailers | (counts only) | envelope |

**Required segments:** `ST`, `BHT`, `EQ`. Absence raises `MissingSegmentError`.
An `EQ` with no service type raises `InvalidSegmentError`. Malformed input
(empty, truncated ISA, non-distinct delimiters, missing `EQ`) raises a structured
`X12ParseError` subclass, never a crash. Only the `D8` demographics form is
modeled; other `DMG01` qualifiers are ignored rather than guessed at.

**Mapping guard:** coverage lookup is keyed on the `NM1*IL` member id carried
with an `MI` qualifier. `EligibilityInquiry.require_member_key()` raises
`InvalidSegmentError` when it is absent, so the responder never resolves against
a guess.

## Synthetic coverage table and resolution rules

Single source of truth: `edi/eligibility_271.py`. **These are invented demo
members, plans, and codes, not real coverage data.**

| Member | Plan | Active | Benefits (self-authored) |
|--------|------|--------|--------------------------|
| `MBR-1001` | DEMO PLAN A | yes | `SRV-MEDICAL` copay 25.00 · `SRV-SPECIALIST` copay 45.00 · `SRV-IMAGING` copay 75.00, prior auth required |
| `MBR-1002` | DEMO PLAN B | yes | `SRV-MEDICAL` deductible 400.00 remaining · `SRV-PHARMACY` copay 15.00, prior auth required |
| `MBR-1003` | DEMO PLAN C | no | `SRV-MEDICAL` copay 30.00 · `SRV-PHARMACY` copay 20.00 |

| Outcome (invented) | When it is reported |
|--------------------|---------------------|
| `EB-ACTIVE-COVERED` | Active plan, covered service type, no auth requirement, deductible met. |
| `EB-AUTH-REQUIRED` | Covered, but the plan requires prior authorization first. |
| `EB-DEDUCTIBLE-UNMET` | Covered, but deductible remains, so the member owes the allowed amount. |
| `EB-NOT-COVERED` | The requested service type is not a benefit of this plan. |
| `EB-INACTIVE` | The member's plan is not active, so nothing can be reported as covered. |

| Reject (invented) | When it is reported |
|-------------------|---------------------|
| `RJ-MEMBER-NOT-FOUND` | No such member id in the demo coverage table. |
| `RJ-DOB-MISMATCH` | Member found, but the inquiry's `DMG02` birth date disagrees. |

Rules are transparent (no scoring model, no LLM): the outcome is a pure function
of the coverage table and the inquiry. When several conditions hold for one
service type, the **most restrictive** outcome wins: `EB-INACTIVE` >
`EB-NOT-COVERED` > `EB-AUTH-REQUIRED` > `EB-DEDUCTIBLE-UNMET` >
`EB-ACTIVE-COVERED`. That mirrors the conservative precedence of the 835 triage
layer. A reject is inquiry-level and suppresses every benefit row, because a
member whose identity did not resolve must never receive coverage detail.

## Fixtures

`edi/fixtures/x270/*.270`, synthetic, committed: **8 well-formed inquiries**
covering every outcome and both rejects (single service type, a three-service-type
inquiry, unmet deductible, prior-auth-required pharmacy, a non-covered service
type, an inactive plan across two service types, an unknown member, and a birth
date mismatch) plus 4 malformed inputs (`malformed_empty`,
`malformed_truncated_isa`, `malformed_wrong_delimiters`, `malformed_missing_eq`).
Golden outcomes live in `edi/fixtures/x270/golden.json`.

## Eval

`python -m edi.eval_eligibility` parses each well-formed fixture, resolves every
requested service type, and scores against the golden file. Its self-authored
fixture set resolves **11 outcomes across 8 inquiries**, and those 11 are not all
benefits: **9 are benefit rows and 2 are rejects** (`RJ-MEMBER-NOT-FOUND`,
`RJ-DOB-MISMATCH`). Over those 11 the responder reaches **11/11 (100%)
exact-match**, with precision and recall of **1.000** for each of the five
outcome classes and both reject reasons:

| Outcome | Precision | Recall | Support |
|---------|-----------|--------|---------|
| `EB-ACTIVE-COVERED` | 1.000 | 1.000 | 3 |
| `EB-AUTH-REQUIRED` | 1.000 | 1.000 | 2 |
| `EB-DEDUCTIBLE-UNMET` | 1.000 | 1.000 | 1 |
| `EB-NOT-COVERED` | 1.000 | 1.000 | 1 |
| `EB-INACTIVE` | 1.000 | 1.000 | 2 |
| `RJ-MEMBER-NOT-FOUND` | 1.000 | 1.000 | 1 |
| `RJ-DOB-MISMATCH` | 1.000 | 1.000 | 1 |

This measures that the rules-driven responder reproduces the intended outcome on
hand-authored synthetic inquiries. It is **not** a claim of accuracy against real
payer eligibility responses or against real X12 benefit semantics.

---

# X12 276/277 claim-status demo

A fourth demo layer over the same core: it **parses** a self-authored X12 276
(health-care claim status **inquiry**) subset, then runs a **deterministic
responder** that resolves a status per requested claim reference from the repo's
own synthetic claim store and emits a **277-shaped response**.

- `edi/x12_276.py` - parser: 276-shaped interchange to a `ClaimStatusInquiry`
  (subscriber, provider, payer, trace number, requested claim references).
- `edi/claim_status_277.py` - synthetic claim store, the status rules, and the
  277 response generator.
- `edi/eval_claim_status.py` - `python -m edi.eval_claim_status`: exact-match +
  per-status precision/recall on the fixture set.

## Honest scope

- **Self-authored subset**, not the real 005010X212 implementation guide. The
  envelope/inquiry shapes (`ISA`/`GS`/`ST`/`BHT`/`TRN`/`HL`/`NM1`/`REF`/`DTP`)
  are modeled at subset level; everything else is tolerated and ignored.
- **No real claim-status code content.** Real 277 responses report status in
  `STC` segments using externally maintained claim status category codes and
  claim status codes. This demo reproduces **none** of that. Status travels in an
  **invented `ZCSI` segment** using a self-authored `CS-*` vocabulary; rejects use
  the same invented `ZRJC` carrier as the eligibility layer; denial reasons reuse
  the 835 layer's invented `DRC` carrier and its `DR-*` vocabulary. `ZCSI` and
  `ZRJC` are four characters and therefore cannot name a real X12 segment (see
  [Invented carrier segments](#invented-carrier-segments)).
- **Claim references travel in `REF*ZZ` carriers** tagged `CLAIM` in `REF03`, the
  same mutually-defined pattern the 278 layer uses for its demo lookup keys, so
  no real reference-qualifier semantics are implied.
- **Synthetic, self-authored data only.** Every claim reference and amount is
  hand-authored; no PHI, no real payer traffic, **not affiliated with any
  company, payer, or product.**
- **The responder simulates the payer side**, for demo purposes. Not
  HIPAA-certified EDI tooling, **not a clearinghouse integration**, and it
  reports no real adjudication.

## Supported segment subset (276 -> `ClaimStatusInquiry`)

| Segment | Purpose | Elements used | Maps to |
|---------|---------|---------------|---------|
| `ISA` | Interchange header | delimiters (positional) | envelope / delimiters |
| `GS` / `ST` | Functional group / transaction set | `ST01=276` | envelope |
| `BHT` | Beginning of hierarchical transaction | `BHT03` | `submitter_reference` |
| `TRN` | Trace | `TRN02` | `trace_number` |
| `HL` | Hierarchical loops (20/21/22) | level code | loop structure |
| `NM1*PR` | Payer | name | `payer_name` |
| `NM1*1P` | Provider | name, `XX`+NPI | `provider` |
| `NM1*IL` | Subscriber | name, `MI`+member id | `subscriber` |
| `REF*ZZ` | Claim reference carrier, `REF03` tag `CLAIM` | `REF02` value (**required**) | `claim_refs` |
| `DTP*472` | Service date | `D8` date | `service_date` |
| `SE` / `GE` / `IEA` | Trailers | (counts only) | envelope |

**Required segments:** `ST`, `BHT`, `REF`. Absence raises `MissingSegmentError`.
A `REF` present but carrying no `CLAIM`-tagged reference also raises
`MissingSegmentError` (the segment-id check alone would pass, leaving nothing to
look up), and a `CLAIM` carrier with an empty `REF02` raises
`InvalidSegmentError`. Malformed input (empty, truncated ISA, non-distinct
delimiters, missing `REF`) raises a structured `X12ParseError` subclass.

## Synthetic claim store and status rules

Single source of truth: `edi/claim_status_277.py`. **These are invented demo
claims and codes, not real adjudication data.**

The finalized claims deliberately **mirror the 835 layer's fixture claims**: same
references, same billed and paid amounts, same self-authored `DR-*` denial
reasons. One synthetic claim can therefore be followed across both demo layers,
asked about with a 276 and reported back with a 277, or paid or denied on an 835
remittance and triaged. A test parses the 835 fixtures and asserts the two stay
consistent, so the mirror cannot silently drift. The two `PEND` claims have no
835 counterpart by design, because a remittance only exists once adjudication has
finished; a test asserts that too.

| Status (invented) | When it is reported |
|-------------------|---------------------|
| `CS-FINALIZED-PAID` | Adjudication complete, paid in full. |
| `CS-FINALIZED-PARTIAL` | Adjudication complete, paid short of billed. |
| `CS-FINALIZED-DENIED` | Adjudication complete, nothing payable; `DR-*` reasons echoed. |
| `CS-PENDING-REVIEW` | Received, still in adjudication. |
| `CS-PENDING-DOCUMENTATION` | Received, waiting on requested material. |
| `CS-NOT-FOUND` | No claim on file for that reference; row also carries `RJ-CLAIM-NOT-FOUND`. |

Rules are transparent (no scoring model, no LLM): the status is a pure function
of the store. Two fail-safe behaviors mirror the 835 layer's discipline: an
unknown claim reference is reported as `CS-NOT-FOUND` **without suppressing the
other rows in the same inquiry**, and an adjudication token the mapping does not
recognize falls back to `CS-PENDING-REVIEW` rather than being reported as a
finalized outcome (never guess, never fail silent).

## Fixtures

`edi/fixtures/x276/*.276`, synthetic, committed: **7 well-formed inquiries**
covering every status (single paid claim, a three-claim batch mixing paid and
denied, a partial payment, both pending reasons, an unknown claim, and a mixed
known/unknown inquiry) plus 4 malformed inputs (`malformed_empty`,
`malformed_truncated_isa`, `malformed_wrong_delimiters`, `malformed_missing_ref`).
Golden statuses live in `edi/fixtures/x276/golden.json`.

## Eval

`python -m edi.eval_claim_status` parses each well-formed fixture, resolves every
requested claim reference, and scores against the golden file. On its **10-claim
self-authored fixture set** (7 inquiries) the responder reaches **10/10 (100%)
exact-match**, with precision and recall of **1.000** for each of the six status
classes:

| Status | Precision | Recall | Support |
|--------|-----------|--------|---------|
| `CS-FINALIZED-PAID` | 1.000 | 1.000 | 2 |
| `CS-FINALIZED-PARTIAL` | 1.000 | 1.000 | 1 |
| `CS-FINALIZED-DENIED` | 1.000 | 1.000 | 3 |
| `CS-PENDING-REVIEW` | 1.000 | 1.000 | 1 |
| `CS-PENDING-DOCUMENTATION` | 1.000 | 1.000 | 1 |
| `CS-NOT-FOUND` | 1.000 | 1.000 | 2 |

This measures that the rules-driven responder reproduces the intended status on
hand-authored synthetic inquiries. It is **not** a claim of accuracy against real
payer claim-status responses or against real X12 claim-status semantics.

## Running the four layers

```bash
uv run pytest tests/test_x12_278_*.py tests/test_x12_835_*.py -q
uv run pytest tests/test_x12_270_*.py tests/test_eligibility_271.py -q
uv run pytest tests/test_x12_276_*.py tests/test_claim_status_277.py -q
uv run pytest tests/test_invented_segment_ids.py -q   # carrier-ID + claim guards
uv run python -m edi.eval_eligibility
uv run python -m edi.eval_claim_status
```

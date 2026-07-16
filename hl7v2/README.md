# HL7 v2 ingestion layer (subset)

A hand-rolled, dependency-free **HL7 v2.x** ingestion layer for the prior-auth
copilot. It reads the encoding characters from the MSH header (the canonical v2
bootstrap), parses two message types, and maps them onto the copilot's
**existing** ingestion boundaries without touching the agent decision path.

## Honest scope

- **Simplified v2 subset.** Two message types only: `ADT^A01` (admit) and
  `ORU^R01` (observation result). Only the segments those need are parsed
  (`MSH`, `EVN`, `PID`, `PV1`, `OBR`, `OBX`); any other segment is tolerated and
  ignored, not validated.
- **Synthetic data only.** Fixtures are self-authored: invented patients and
  facilities, no real MRNs, no PHI patterns, no real message traffic.
- **Not a certified HL7 interface engine.** No MLLP transport framing, no ACK
  (`ACK`/`MSA`) generation, no Z-segment or conformance-profile handling, no
  full HL7 data-type validation, no terminology validation. A demo/portfolio
  interoperability layer, **not affiliated with any company**.
- **Deterministic and offline.** No LLM, no keys, no network.
- Hand-rolled parser (no HL7 dependency), so delimiter and envelope handling is
  explicit and readable, mirroring the sibling X12 278 layer.

## Encoding and envelope

Delimiters are resolved from the MSH header, the canonical HL7 v2 bootstrap:
`MSH-1` is the **field separator** (the character immediately after `MSH`) and
`MSH-2` declares the remaining four encoding characters: component (`^`),
repetition (`~`), escape (`\`), and subcomponent (`&`). Repeating fields (`~`)
and escape sequences (`\F\`, `\S\`, `\T\`, `\R\`, `\E\`) are handled. Segment
terminators may be `\r`, `\n`, or `\r\n` (fixtures are stored one segment per
line for readability).

**Envelope validation:** `MSH-12` must be an HL7 `2.x` version and `MSH-9` must
be a supported message type, else `UnsupportedVersionError` /
`UnsupportedMessageTypeError`.

## Supported segments and the two mapping boundaries

The agent decision path is **byte-untouched**. Each message type maps onto a
structure the copilot already consumes.

### `ADT^A01` → `PatientContext` (the `Case.patient_id` boundary)

| Segment | Purpose | Fields used | Maps to |
|---------|---------|-------------|---------|
| `MSH` | Envelope | delimiters, `MSH-9` type, `MSH-12` version | routing |
| `EVN` | Event type | `EVN-1` code, `EVN-2` datetime | `event_type` |
| `PID` | Patient identification | `PID-3` id list (repeating), `PID-5` name, `PID-7` DOB, `PID-8` sex | `patient_id`, demographics |
| `PV1` | Patient visit | `PV1-2` class, `PV1-3` location, `PV1-19` visit no., `PV1-44` admit dt | visit context |

`PatientContext.patient_id` mirrors `schemas.cases.Case.patient_id`: the identity
key the copilot uses for structured fact fusion. The X12 278 layer fills that
field from `NM1*IL`; an ADT admit fills it from `PID-3`.

### `ORU^R01` → `FhirClinicalBundle` (the structured-observation boundary)

| Segment | Purpose | Fields used | Maps to |
|---------|---------|-------------|---------|
| `MSH` / `PID` / `PV1` | As above | (see above) | routing / identity |
| `OBR` | Observation request | `OBR-4` service id, `OBR-7` datetime | order metadata |
| `OBX` | Observation result | `OBX-2` value type, `OBX-3` code (e.g. LOINC), `OBX-5` value, `OBX-6` units, `OBX-11` status, `OBX-14` datetime | FHIR `Observation` |

Each `OBX` becomes a FHIR R4B-shaped `Observation` resource keyed by
`system|code`, exactly the `observations_by_loinc` structure that the
**unchanged** `agent.fhir_facts.resolve_fhir_facts` consumes. `NM` results become
`valueQuantity`; other value types become `valueString`. HL7 coding-system
tokens are mapped to FHIR system URIs (`LN` → `http://loinc.org`, `SCT` →
`http://snomed.info/sct`). A LOINC-coded ORU therefore resolves prior-auth
observation fields (A1c `4548-4`, BMI `39156-5`) through the existing fact
resolver with **no change** to that code. See
`tests/test_hl7v2_mapper.py::test_mapped_oru_resolves_facts_through_unchanged_resolver`.

## Malformed handling

Every failure raises an `HL7ParseError` subclass with a segment tag, never a
crash:

- `EmptyMessageError`: empty / whitespace-only input.
- `MissingSegmentError`: no MSH, or a required `PID`/`OBX` absent.
- `InvalidDelimiterError`: encoding characters unresolved or non-distinct.
- `InvalidSegmentError`: a present segment (e.g. a truncated MSH) is malformed.
- `UnsupportedVersionError` / `UnsupportedMessageTypeError`: outside the subset.

## Fixtures

`hl7v2/fixtures/*.hl7`, synthetic, committed:

- **6 well-formed:** `adt_a01_admit_basic`, `adt_a01_admit_repeat_ids` (repeating
  `PID-3` id list), `oru_r01_a1c_bmi` (LOINC A1c + BMI), `oru_r01_metabolic_panel`
  (multi-OBX), `oru_r01_mixed_types` (numeric + string OBX),
  `oru_r01_escaped` (an escaped field separator in a free-text result).
- **4 malformed:** `malformed_empty`, `malformed_missing_msh`,
  `malformed_truncated_msh`, `malformed_unsupported_type`.

Golden files for both the parsed message and the boundary mapping live in
`hl7v2/fixtures/goldens/{parsed,mapped}/`.

## Eval (exact match)

`python -m hl7v2.eval` runs every well-formed fixture and checks two exact
dictionary matches against the committed goldens (the parsed `HL7Message` and
the boundary mapping), printing a per-fixture table:

| Fixture | parsed | mapped |
|---------|:------:|:------:|
| `adt_a01_admit_basic` | ok | ok |
| `adt_a01_admit_repeat_ids` | ok | ok |
| `oru_r01_a1c_bmi` | ok | ok |
| `oru_r01_escaped` | ok | ok |
| `oru_r01_metabolic_panel` | ok | ok |
| `oru_r01_mixed_types` | ok | ok |

Result: **6/6 (100%)** exact match on its self-authored HL7 v2 set. Because the
goldens are authored by this repo, this is a self-consistency check of the parser
and the two mappings, **not** third-party HL7 conformance certification.
`python -m hl7v2.eval --update` regenerates the goldens after an intentional
change.

```bash
python -m hl7v2.eval            # per-fixture table + 6/6
uv run pytest tests/test_hl7v2_*.py -q
```

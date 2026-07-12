# OCR intake and browser-agent layers (README section draft)

> Draft for the main README. Not yet merged. Reviewer edits happen here first.

Two demo-scope layers that extend the prior-authorization workflow to the two
intake/egress edges a deployment engineer touches on prior-auth work: reading
scanned decision letters (OCR) and reading status back out of a payer portal
(browser automation).

## What is demonstrated

**OCR intake (`ocr/`).** Synthetic scanned prior-authorization decision letters
are generated in-repo, run through a tesseract OCR pipeline, and parsed into a
structured `LetterRecord` (case id, decision, auth number, drug, condition,
dates) with a tolerant field parser that handles OCR noise. A field-level
accuracy eval scores parsed records against known ground truth.

**Browser agent (`browser_agent/`).** A self-built synthetic payer portal
(FastAPI, two pages) is driven by a Playwright agent: log in, submit a case-id
lookup, and read the authorization status from the DOM into a structured
`PortalStatus`. A round-trip demo checks the statuses the agent scrapes against
the portal's own source data.

## Honest scope

- **Synthetic letters, generated in-repo.** The OCR fixtures are rendered from
  templates by `ocr/generate_fixtures.py` (Pillow). Names and case ids are
  invented. There is no PHI anywhere in the pipeline.
- **Self-built demo portal.** The browser agent drives a local FastAPI app in
  this repo (`browser_agent/portal/`), clearly labeled synthetic in-page and in
  code. It does not resemble, proxy, or connect to any real payer website. This
  is not RPA against a real payer system.
- **Self-consistency evals, not external validation.** The portal round-trip
  compares what the agent scrapes to the portal's own source JSON. Agreement
  shows the agent navigates and scrapes correctly. It does not validate any
  external system. The OCR eval scores against ground truth we generated
  ourselves, so the accuracy number reflects a controlled synthetic set, not
  real-world payer-letter accuracy.
- **Demo-scope only.** These layers are demonstrations of the techniques (OCR
  field extraction, browser automation) on synthetic data. They are not
  hardened intake or automation systems.

## Accuracy (measured)

Field-level accuracy of the OCR pipeline over the 12 committed synthetic
letters (`uv run python -m ocr.eval_ocr`):

| field          | correct / total | accuracy |
|----------------|-----------------|----------|
| case_id        | 12 / 12         | 100.0%   |
| patient_name   | 12 / 12         | 100.0%   |
| decision       | 12 / 12         | 100.0%   |
| drug           | 12 / 12         | 100.0%   |
| condition      | 12 / 12         | 100.0%   |
| auth_number    | 12 / 12         | 100.0%   |
| decision_date  | 12 / 12         | 100.0%   |
| valid_through  | 12 / 12         | 100.0%   |
| **OVERALL**    | **96 / 96**     | **100.0%** |

Four of the twelve letters are deliberately degraded (Gaussian blur, speckle
noise, and rotation) to simulate low-quality scans. Raw tesseract output on
those does contain real errors: for example, on `letter_11` the label "Case ID"
is read as "Case 1D", and disclaimer text clips at the rotated page edge. The
tolerant parser recovers the field values from that noisy text (case-insensitive
labels, whitespace collapse, a light OCR-confusion remap on the numeric tail of
code fields, and tolerant matching of the "ID" label), which is why field
accuracy lands at 100% despite the raw OCR noise. The number is honest but
controlled: it is 100% on a synthetic set we generated and scored ourselves, not
a claim about real payer letters.

The browser round-trip (`uv run python -m browser_agent.demo`) reports 12 / 12
statuses matching the portal source (0 mismatches).

## Run commands

```
# One-time system deps (macOS)
brew install tesseract
uv add pillow pytesseract playwright   # already in pyproject
uv run playwright install chromium

# OCR: regenerate fixtures and score accuracy
uv run python -m ocr.generate_fixtures
uv run python -m ocr.eval_ocr

# Browser agent: run the synthetic-portal round trip (also writes screenshots)
uv run python -m browser_agent.demo
```

## Tests

CI-safe tests (run under the standard gate, no tesseract/chromium needed):

- `tests/test_ocr_parser.py`: parser on hand-written raw-text samples,
  including OCR-noise samples, empty and garbage input.
- `tests/test_ocr_generate.py`: fixture-generation determinism and structure.
- `tests/test_portal_routes.py`: portal routes via `TestClient`, plus a
  cross-check that the portal case ids match the OCR ground truth.

Tool-dependent tests (marked `ocr` / `browser`, excluded from the CI gate and
self-skipping when the tool is absent):

- `tests/test_ocr_pipeline.py` (`ocr`): full OCR over the fixtures, accuracy
  floor, malformed/empty-image handling.
- `tests/test_browser_agent.py` (`browser`): Playwright agent login, lookup,
  bad-password and unknown-case errors, full self-consistency demo.

The CI gate runs `pytest -m "not network and not ocr and not browser"`, so the
tesseract/chromium tests never run on CI runners that lack those tools.

## Evidence

Screenshots of the portal flow, captured by the agent during the demo:

- `browser_agent/evidence/01_login.png`
- `browser_agent/evidence/02_lookup_form.png`
- `browser_agent/evidence/03_status_result.png`

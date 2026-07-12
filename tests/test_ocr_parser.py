"""CI-safe unit tests for the OCR text parser (no tesseract required).

These exercise ``parse_letter_text`` on hand-written raw-text samples,
including samples that mimic tesseract noise, so parsing behavior is covered
by the standard CI gate without the tesseract binary.
"""

from __future__ import annotations

from ocr.reader import LetterRecord, parse_letter_text

CLEAN_APPROVED = """UTILIZATION MANAGEMENT DECISION NOTICE
[SYNTHETIC DEMO LETTER - NOT A REAL PAYER DOCUMENT]

Date: 03/14/2026
Case ID: PA-2026-0042
Member: Jordan Rivera
Medication: Adalimumab
Condition: Rheumatoid Arthritis

Decision: APPROVED
Authorization Number: AUTH-8871245
Valid Through: 09/14/2026

Generated for demonstration purposes only.
"""

CLEAN_DENIED = """Date: 03/18/2026
Case ID: PA-2026-0117
Member: Casey Nguyen
Medication: Semaglutide
Condition: Type 2 Diabetes

Decision: DENIED

Generated for demonstration purposes only.
"""


def test_parses_clean_approved_letter() -> None:
    rec = parse_letter_text(CLEAN_APPROVED)
    assert rec == LetterRecord(
        case_id="PA-2026-0042",
        patient_name="Jordan Rivera",
        decision="APPROVED",
        drug="Adalimumab",
        condition="Rheumatoid Arthritis",
        auth_number="AUTH-8871245",
        decision_date="03/14/2026",
        valid_through="09/14/2026",
    )


def test_denied_letter_has_no_auth_or_valid_through() -> None:
    rec = parse_letter_text(CLEAN_DENIED)
    assert rec.decision == "DENIED"
    assert rec.auth_number is None
    assert rec.valid_through is None
    assert rec.case_id == "PA-2026-0117"


def test_decision_word_in_title_does_not_leak() -> None:
    # The title contains the word DECISION; only the labeled line should count.
    rec = parse_letter_text(
        "UTILIZATION MANAGEMENT DECISION NOTICE\nDecision: PENDED\n"
    )
    assert rec.decision == "PENDED"


def test_tolerates_ocr_label_noise_case_1d() -> None:
    # tesseract sometimes reads the "ID" label as "1D" on noisy scans.
    rec = parse_letter_text("Case 1D: PA-2026-0701\nDecision: PENDED\n")
    assert rec.case_id == "PA-2026-0701"


def test_normalizes_digit_lookalikes_in_code_tail() -> None:
    # Letter look-alikes inside the numeric tail are remapped to digits.
    rec = parse_letter_text("Authorization Number: AUTH-88O1S4\n")
    assert rec.auth_number == "AUTH-880154"


def test_prefix_letters_are_not_corrupted_by_normalization() -> None:
    # The "AUTH" prefix must survive; only the numeric tail is remapped.
    rec = parse_letter_text("Authorization Number: AUTH-7719004\n")
    assert rec.auth_number == "AUTH-7719004"


def test_empty_text_returns_unknown_record() -> None:
    rec = parse_letter_text("")
    assert rec.decision == "UNKNOWN"
    assert rec.case_id is None
    assert rec.auth_number is None
    assert rec.patient_name is None


def test_garbage_text_is_not_misparsed() -> None:
    rec = parse_letter_text("!!! ~~~ \x0c random noise 293\n")
    assert rec.decision == "UNKNOWN"
    assert rec.case_id is None

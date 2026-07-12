"""OCR pipeline: image -> raw text -> structured LetterRecord.

The pipeline has two separable stages so tests can cover the parser without
requiring the tesseract binary:

    read_image(path)      -> raw OCR text        (needs tesseract)
    parse_letter_text(s)  -> LetterRecord         (pure Python, CI-safe)
    read_letter(path)     -> LetterRecord         (needs tesseract)

Field parsing is deliberately tolerant: labels are matched case-insensitively,
whitespace is collapsed, and code-shaped fields (case ids, auth numbers) get a
light OCR-confusion normalization (see ``_normalize_code``). The normalization
is disclosed and intentionally conservative so the reported accuracy stays
honest rather than being propped up by aggressive guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytesseract
from PIL import Image, UnidentifiedImageError


@dataclass(frozen=True)
class LetterRecord:
    """Structured fields extracted from one decision letter."""

    case_id: str | None
    patient_name: str | None
    decision: str  # APPROVED | DENIED | PENDED | UNKNOWN
    drug: str | None
    condition: str | None
    auth_number: str | None
    decision_date: str | None
    valid_through: str | None


class OcrError(RuntimeError):
    """Raised when an image cannot be read for OCR."""


def read_image(path: str | Path) -> str:
    """Run tesseract OCR over an image file and return raw text.

    Raises OcrError on a missing or unreadable image so callers get a
    structured failure instead of a bare library exception.
    """
    p = Path(path)
    if not p.exists():
        raise OcrError(f"image not found: {p}")
    try:
        with Image.open(p) as img:
            return str(pytesseract.image_to_string(img))
    except UnidentifiedImageError as exc:
        raise OcrError(f"not a readable image: {p}") from exc


_DATE = r"(\d{1,2}/\d{1,2}/\d{2,4})"


def _collapse(text: str) -> str:
    # Collapse runs of spaces/tabs but keep newlines (labels are line-scoped).
    return re.sub(r"[ \t]+", " ", text)


def _search(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text, flags=re.IGNORECASE)
    return m.group(1).strip() if m else None


def _normalize_code(value: str | None) -> str | None:
    """Light, disclosed OCR-confusion normalization for code-shaped fields.

    Case ids and auth numbers here are structured as letters/prefix followed by
    digits. Inside a run that should be digits, tesseract sometimes emits a
    letter that looks like a digit. We only remap within the trailing numeric
    run and only for the unambiguous look-alikes: prefix letters are never
    touched. This assumes codes end in an all-digit run, which holds for this
    repo's fixture formats; a legitimate letter inside that trailing run would
    be remapped, so do not reuse this on code formats that mix letters into
    the tail.
    """
    if value is None:
        return None
    value = value.upper().strip().rstrip(".")
    value = value.replace(" ", "")
    digit_map = {"O": "0", "I": "1", "L": "1", "S": "5", "B": "8", "Z": "2"}
    # Split into a leading prefix (letters/dash) and a trailing code run.
    m = re.match(r"^([A-Z\-]*?)([A-Z0-9]+)$", value)
    if not m:
        return value
    prefix, tail = m.group(1), m.group(2)
    # Normalize only the tail, and only once we are past its first letter run.
    chars = list(tail)
    seen_digit = any(c.isdigit() for c in chars)
    if seen_digit:
        first_digit = next(i for i, c in enumerate(chars) if c.isdigit())
        for i in range(first_digit, len(chars)):
            if chars[i] in digit_map:
                chars[i] = digit_map[chars[i]]
    return prefix + "".join(chars)


def _parse_decision(text: str) -> str:
    # Prefer the explicit "Decision:" line (require the colon so the word
    # "DECISION" inside the letter title does not match).
    line = _search(r"Decision\s*:\s*([A-Za-z ]+)", text)
    # Fallback scope excludes the title line to avoid false matches.
    body = "\n".join(
        ln for ln in text.splitlines() if "DECISION NOTICE" not in ln.upper()
    )
    scope = (line or body).upper()
    if "APPROV" in scope or "CERTIFIED" in scope:
        return "APPROVED"
    if "DENIE" in scope or "NOT CERTIFIED" in scope:
        return "DENIED"
    if "PEND" in scope:
        return "PENDED"
    return "UNKNOWN"


def parse_letter_text(text: str) -> LetterRecord:
    """Parse raw OCR text into a LetterRecord. Pure Python, no tesseract."""
    t = _collapse(text)

    # "ID" is a frequent label misread ("1D", "lD") on noisy scans, so the
    # label itself is matched tolerantly.
    case_id = _normalize_code(
        _search(r"Case\s*[I1l][D0][:\s]*([A-Z0-9][A-Z0-9\- ]{3,})", t)
    )
    patient = _search(r"(?:Member|Patient)[:\s]*([A-Za-z][A-Za-z .'\-]+)", t)
    drug = _search(r"(?:Medication|Drug)[:\s]*([A-Za-z][A-Za-z0-9 /\-]+)", t)
    condition = _search(r"(?:Condition|Diagnosis)[:\s]*([A-Za-z][A-Za-z0-9 /\-]+)", t)
    auth = _normalize_code(
        _search(
            r"Auth(?:orization)?\s*(?:Number|No\.?|#)?[:\s]*"
            r"([A-Z0-9][A-Z0-9\- ]{3,})",
            t,
        )
    )
    decision_date = _search(r"Date[:\s]*" + _DATE, t)
    valid_through = _search(r"Valid\s*Through[:\s]*" + _DATE, t)
    decision = _parse_decision(t)

    return LetterRecord(
        case_id=case_id,
        patient_name=patient.title() if patient else None,
        decision=decision,
        drug=drug.title() if drug else None,
        condition=condition.title() if condition else None,
        auth_number=auth,
        decision_date=decision_date,
        valid_through=valid_through,
    )


def read_letter(path: str | Path) -> LetterRecord:
    """Full pipeline: OCR an image file then parse it. Needs tesseract."""
    return parse_letter_text(read_image(path))

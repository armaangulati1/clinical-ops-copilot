"""Map a spoken transcript to a case ID for the existing agent.

The production agent operates on ``Case`` objects keyed by case ID (e.g.
``case-001``), not on free-form questions. So the voice layer's only job is to
resolve the caller's spoken question to one of those existing case IDs. It does
this deterministically (no extra LLM call) by:

  1. matching an explicit spoken case number ("case one", "case 3", "case-012"),
  2. otherwise falling back to a configured default case.

This keeps the demo honest: the voice layer routes; the REAL agent decides.
"""

from __future__ import annotations

import re

DEFAULT_CASE_ID = "case-001"

# Spoken number words -> digit, covering the case range we ship (1-48).
_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fourty": 40,
}


def _words_to_int(phrase: str) -> int | None:
    """Convert a small spoken number phrase ("twenty three") to an int."""
    tokens = [t for t in re.split(r"[\s-]+", phrase.strip().lower()) if t]
    total = 0
    matched = False
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in _TENS:
            value = _TENS[tok]
            if i + 1 < len(tokens) and tokens[i + 1] in _ONES:
                value += _ONES[tokens[i + 1]]
                i += 1
            total += value
            matched = True
        elif tok in _ONES:
            total += _ONES[tok]
            matched = True
        i += 1
    return total if matched else None


def case_id_from_transcript(
    transcript: str,
    *,
    default_case_id: str = DEFAULT_CASE_ID,
) -> str:
    """Resolve a transcript to a ``case-0NN`` id.

    Recognizes: "case-012", "case 12", "case twelve", "case number 3".
    Falls back to ``default_case_id`` when no case is named.
    """
    text = transcript.lower()

    # "case-012" / "case 12" / "case number 12" (digits)
    digit_match = re.search(r"case[\s\-#]*(?:number\s*)?(\d{1,3})", text)
    if digit_match:
        return f"case-{int(digit_match.group(1)):03d}"

    # "case twelve" / "case number twenty three" (spoken words)
    word_match = re.search(
        r"case[\s\-#]*(?:number\s*)?"
        r"((?:zero|one|two|three|four|five|six|seven|eight|nine|ten|"
        r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
        r"eighteen|nineteen|twenty|thirty|forty|fourty)(?:[\s-]+\w+)?)",
        text,
    )
    if word_match:
        number = _words_to_int(word_match.group(1))
        if number is not None and number > 0:
            return f"case-{number:03d}"

    return default_case_id

"""PHI redaction for logs, audit trails, and run records."""

from __future__ import annotations

import os
import re
from re import Pattern
from typing import Any

# Stable masked tokens (coherent across a single run).
TOKEN_NAME = "[NAME]"
TOKEN_MRN = "[MRN]"
TOKEN_DOB = "[DOB]"
TOKEN_ADDRESS = "[ADDRESS]"
TOKEN_PHONE = "[PHONE]"
TOKEN_EMAIL = "[EMAIL]"
TOKEN_SSN = "[SSN]"
TOKEN_FREE_TEXT = "[REDACTED_TEXT]"

IDENTIFIER_FIELD_TOKENS: dict[str, str] = {
    "patient_name": TOKEN_NAME,
    "patient_id": TOKEN_MRN,
    "mrn": TOKEN_MRN,
    "email": TOKEN_EMAIL,
    "to": TOKEN_EMAIL,
    "phone": TOKEN_PHONE,
    "address": TOKEN_ADDRESS,
    "date_of_birth": TOKEN_DOB,
    "dob": TOKEN_DOB,
}

FREE_TEXT_FIELD_NAMES = frozenset(
    {
        "clinical_note",
        "note_text",
        "note",
        "body",
        "details",
        "subject",
        "rationale",
        "message",
        "evidence",
    },
)

SECRET_ENV_NAMES = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "CHARTEXTRACT_API_KEY",
    },
)

EMAIL_PATTERN: Pattern[str] = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
)
PHONE_PATTERN: Pattern[str] = re.compile(
    r"\b(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]?\d{3}[-.\s]?\d{4}\b",
)
SSN_PATTERN: Pattern[str] = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
MRN_PATTERN: Pattern[str] = re.compile(
    r"\b(?:MRN|mrn)[#:\s-]*[A-Z0-9-]{5,}\b",
)
DOB_PATTERN: Pattern[str] = re.compile(
    r"\b(?:DOB|date of birth)[:\s]*\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
    re.IGNORECASE,
)
PATIENT_NAME_PATTERN: Pattern[str] = re.compile(
    r"(Patient:\s*)([A-Za-z][A-Za-z .'-]{1,80})",
    re.IGNORECASE,
)
ADDRESS_PATTERN: Pattern[str] = re.compile(
    r"\b\d{1,5}\s+[A-Za-z0-9 .'-]+"
    r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln)\b",
    re.IGNORECASE,
)
HARDCODED_KEY_PATTERN: Pattern[str] = re.compile(
    r"sk-ant-api[0-9A-Za-z_-]{10,}",
)

# One vendor's key shape is not "a secrets scan". This repo authenticates to
# four providers: Anthropic (the agent), OpenAI (the Whisper voice prototype),
# Twilio (telephony) and ElevenLabs (the TTS backend). A guard that knows only
# the first reports a clean repo while another vendor's credential sits in a
# tracked file.
#
# Twilio auth tokens are bare 32-character hex with no prefix, too generic to
# match on its own without flagging hashes and fixture ids, so that one is
# matched only next to its own variable name.
#
# ElevenLabs keys are `sk_` + 48 hex. Note the UNDERSCORE: every OpenAI pattern
# above uses `sk-` with a hyphen, so an ElevenLabs key matched none of them and
# was invisible to this scan until the TTS backend was added. That is the same
# family as the 2026-07-27 `demo_env.sh` miss: the guard could not see the place
# the secret actually lives.
PROVIDER_KEY_PATTERNS: tuple[tuple[str, Pattern[str]], ...] = (
    ("anthropic", HARDCODED_KEY_PATTERN),
    ("openai", re.compile(r"sk-proj-[0-9A-Za-z_-]{20,}")),
    ("openai", re.compile(r"\bsk-[A-Za-z0-9]{48}\b")),
    ("twilio-account-sid", re.compile(r"\bAC[0-9a-f]{32}\b")),
    ("twilio-api-key-sid", re.compile(r"\bSK[0-9a-f]{32}\b")),
    (
        "twilio-auth-token",
        re.compile(r"(?i)twilio[_-]?auth[_-]?token\s*[=:]\s*['\"]?[0-9a-f]{32}\b"),
    ),
    ("elevenlabs", re.compile(r"\bsk_[0-9a-f]{48}\b")),
)


def scan_for_provider_keys(text: str) -> list[str]:
    """Return the vendor labels whose live-key shape appears in ``text``.

    Labels, never the matched value: a guard that echoes the secret it found
    into a public CI log has published it rather than caught it.
    """
    return sorted(
        {label for label, pattern in PROVIDER_KEY_PATTERNS if pattern.search(text)}
    )


INLINE_SECRET_PATTERN: Pattern[str] = re.compile(
    r"(?i)(api[_-]?key|secret|token)\s*=\s*['\"][^'\"]{8,}['\"]",
)

TEXT_REDACTION_RULES: tuple[tuple[Pattern[str], str], ...] = (
    (EMAIL_PATTERN, TOKEN_EMAIL),
    (PHONE_PATTERN, TOKEN_PHONE),
    (SSN_PATTERN, TOKEN_SSN),
    (MRN_PATTERN, TOKEN_MRN),
    (DOB_PATTERN, TOKEN_DOB),
    (PATIENT_NAME_PATTERN, rf"\1{TOKEN_NAME}"),
    (ADDRESS_PATTERN, TOKEN_ADDRESS),
)

ALL_PHI_SCAN_PATTERNS: tuple[Pattern[str], ...] = (
    EMAIL_PATTERN,
    PHONE_PATTERN,
    SSN_PATTERN,
    MRN_PATTERN,
    DOB_PATTERN,
    ADDRESS_PATTERN,
    HARDCODED_KEY_PATTERN,
)


def redact_text(text: str) -> str:
    """Scrub identifier patterns from free text; preserve clinical facts."""
    redacted = text
    for pattern, replacement in TEXT_REDACTION_RULES:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def redact_value(value: Any, *, field_name: str | None = None) -> Any:
    """Recursively redact a value for safe logging."""
    if field_name in IDENTIFIER_FIELD_TOKENS and isinstance(value, str) and value:
        return IDENTIFIER_FIELD_TOKENS[field_name]
    if isinstance(value, str):
        if field_name in FREE_TEXT_FIELD_NAMES or field_name is None:
            return redact_text(value)
        return redact_text(value)
    if isinstance(value, dict):
        return redact_payload(value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    return value


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Redact a JSON-like payload before persistence to logs or audit."""
    redacted: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, dict):
            redacted[key] = redact_payload(value)
        elif isinstance(value, list):
            redacted[key] = [redact_value(item, field_name=key) for item in value]
        else:
            redacted[key] = redact_value(value, field_name=key)
    return redacted


def redact_secret_values(text: str, secrets: tuple[str, ...] = ()) -> str:
    """Replace known secret values that must never appear in logs."""
    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[SECRET]")
    for env_name in SECRET_ENV_NAMES:
        value = os.environ.get(env_name)
        if value:
            redacted = redacted.replace(value, "[SECRET]")
    return redact_text(redacted)


def find_raw_phi_literals(text: str, literals: tuple[str, ...]) -> list[str]:
    """Return seeded PHI literals still present in text (for tests)."""
    found: list[str] = []
    for literal in literals:
        if literal and literal in text:
            found.append(literal)
    return found


def scan_for_obvious_secrets_in_source(source: str) -> list[str]:
    """Detect obvious hardcoded secret patterns in source text."""
    findings: list[str] = []
    if HARDCODED_KEY_PATTERN.search(source):
        findings.append("anthropic_api_key_pattern")
    if INLINE_SECRET_PATTERN.search(source):
        findings.append("inline_secret_assignment")
    return findings

"""Prompt-injection detection and containment for clinical free text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from re import Pattern

INJECTION_PATTERNS: tuple[Pattern[str], ...] = (
    re.compile(r"ignore\s+(?:your|all|previous|prior)\s+instructions", re.I),
    re.compile(r"disregard\s+(?:the\s+)?policy", re.I),
    re.compile(r"approve\s+(?:anyway|regardless|without\s+review)", re.I),
    re.compile(r"email\s+all\s+records", re.I),
    re.compile(r"exfiltrat(?:e|ion)", re.I),
    re.compile(r"send\s+all\s+patient", re.I),
    re.compile(r"override\s+(?:the\s+)?approval", re.I),
    re.compile(r"system\s*:\s*you\s+are", re.I),
)

NEUTRALIZED_LINE = "[INJECTION_PATTERN_REMOVED]"


@dataclass(frozen=True)
class InjectionScanResult:
    """Outcome of scanning user-controlled clinical text."""

    suspicious: bool
    reasons: list[str]
    sanitized_text: str
    original_length: int


def scan_and_sanitize(text: str) -> InjectionScanResult:
    """Detect injection attempts and neutralize instruction-like lines."""
    reasons: list[str] = []
    for pattern in INJECTION_PATTERNS:
        if pattern.search(text):
            reasons.append(pattern.pattern)

    sanitized_lines: list[str] = []
    for line in text.splitlines():
        if any(pattern.search(line) for pattern in INJECTION_PATTERNS):
            sanitized_lines.append(NEUTRALIZED_LINE)
        else:
            sanitized_lines.append(line)

    sanitized = "\n".join(sanitized_lines)
    return InjectionScanResult(
        suspicious=bool(reasons),
        reasons=reasons,
        sanitized_text=sanitized,
        original_length=len(text),
    )

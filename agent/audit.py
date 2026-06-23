"""Append-only audit trail with PHI redaction."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from schemas.approval import AuditEvent, AuditEventType
from schemas.phi_redaction import redact_payload, redact_secret_values


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    redacted = redact_payload(payload)
    scrubbed = redact_secret_values(json.dumps(redacted, default=str))
    loaded = json.loads(scrubbed)
    if isinstance(loaded, dict):
        return loaded
    return redacted


class AuditTrail(Protocol):
    """Append-only audit storage."""

    def append(
        self,
        case_id: str,
        event_type: AuditEventType,
        payload: dict[str, Any],
    ) -> AuditEvent:
        """Append a redacted audit event."""

    def get_case_history(self, case_id: str) -> list[AuditEvent]:
        """Return ordered history for a case."""


class InMemoryAuditTrail:
    """In-memory audit trail for tests."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []
        self._sequence = 0

    def append(
        self,
        case_id: str,
        event_type: AuditEventType,
        payload: dict[str, Any],
    ) -> AuditEvent:
        event = AuditEvent(
            case_id=case_id,
            event_type=event_type,
            timestamp=_utc_now(),
            payload=_safe_payload(payload),
            sequence=self._sequence,
        )
        self._sequence += 1
        self._events.append(event)
        return event

    def get_case_history(self, case_id: str) -> list[AuditEvent]:
        return [event for event in self._events if event.case_id == case_id]


class JsonlAuditTrail:
    """File-backed append-only audit trail."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._sequence = self._load_sequence()

    def _load_sequence(self) -> int:
        if not self.path.exists():
            return 0
        count = 0
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                count += 1
        return count

    def append(
        self,
        case_id: str,
        event_type: AuditEventType,
        payload: dict[str, Any],
    ) -> AuditEvent:
        event = AuditEvent(
            case_id=case_id,
            event_type=event_type,
            timestamp=_utc_now(),
            payload=_safe_payload(payload),
            sequence=self._sequence,
        )
        self._sequence += 1
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json() + "\n")
        return event

    def get_case_history(self, case_id: str) -> list[AuditEvent]:
        if not self.path.exists():
            return []
        events: list[AuditEvent] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = AuditEvent.model_validate_json(line)
            if event.case_id == case_id:
                events.append(event)
        events.sort(key=lambda item: item.sequence)
        return events


def get_case_history(case_id: str, trail: AuditTrail) -> list[AuditEvent]:
    """Reconstruct the ordered audit history for a case."""
    return trail.get_case_history(case_id)

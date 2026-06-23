"""Idempotency store for state-changing clinic-ops actions."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field


class IdempotencyRecord(BaseModel):
    """Cached successful action result."""

    action: str = Field(min_length=1)
    payload: dict[str, Any]


class IdempotencyStore(Protocol):
    """Interface for idempotent action result storage."""

    def get(self, action: str, idempotency_key: str) -> IdempotencyRecord | None:
        """Return a prior successful result, if any."""

    def put(self, action: str, idempotency_key: str, payload: dict[str, Any]) -> None:
        """Persist a successful result for duplicate/retry calls."""


class InMemoryIdempotencyStore:
    """In-memory idempotency store (sufficient for Phase 3)."""

    def __init__(self) -> None:
        self._records: dict[str, IdempotencyRecord] = {}

    def _key(self, action: str, idempotency_key: str) -> str:
        return f"{action}:{idempotency_key}"

    def get(self, action: str, idempotency_key: str) -> IdempotencyRecord | None:
        return self._records.get(self._key(action, idempotency_key))

    def put(self, action: str, idempotency_key: str, payload: dict[str, Any]) -> None:
        record = IdempotencyRecord(action=action, payload=payload)
        self._records[self._key(action, idempotency_key)] = record

    def clear(self) -> None:
        self._records.clear()

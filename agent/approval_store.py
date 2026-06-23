"""Approval record persistence."""

from __future__ import annotations

from typing import Protocol

from schemas.approval import ApprovalStatus, PendingApproval


class ApprovalStore(Protocol):
    """Storage for pending and resolved approvals."""

    def save(self, approval: PendingApproval) -> None:
        """Persist a new or updated approval record."""

    def get(self, approval_id: str) -> PendingApproval | None:
        """Load an approval by id."""

    def list_pending(self) -> list[PendingApproval]:
        """Return approvals awaiting human action."""


class InMemoryApprovalStore:
    """In-memory approval store for tests and local UI."""

    def __init__(self) -> None:
        self._records: dict[str, PendingApproval] = {}

    def save(self, approval: PendingApproval) -> None:
        self._records[approval.approval_id] = approval

    def get(self, approval_id: str) -> PendingApproval | None:
        return self._records.get(approval_id)

    def list_pending(self) -> list[PendingApproval]:
        pending = [
            record
            for record in self._records.values()
            if record.status == ApprovalStatus.PENDING
        ]
        return sorted(pending, key=lambda item: item.created_at)

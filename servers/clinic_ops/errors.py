"""Domain errors for clinic-ops actions."""

from __future__ import annotations

from servers.clinic_ops.schemas import ActionFailure


class TransientMockError(Exception):
    """Simulated transient external failure (retryable)."""


class MockTimeoutError(Exception):
    """Simulated hung external call that exceeded the configured timeout."""


class ActionFailedError(Exception):
    """Raised when an action cannot complete after retries."""

    def __init__(self, failure: ActionFailure) -> None:
        self.failure = failure
        super().__init__(failure.message)

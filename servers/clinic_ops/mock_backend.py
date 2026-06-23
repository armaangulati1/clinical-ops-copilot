"""Mock external services with latency, failures, and side-effect counters."""

from __future__ import annotations

import asyncio
import random
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from servers.clinic_ops.config import ServerConfig
from servers.clinic_ops.errors import MockTimeoutError, TransientMockError


@dataclass
class MockCounters:
    """Side-effect counters for chaos/idempotency assertions."""

    sends: int = 0
    schedules: int = 0
    tasks: int = 0


@dataclass
class MockBackend:
    """Stateful mock for email, scheduling, and task systems."""

    config: ServerConfig
    rng: random.Random = field(default_factory=random.Random)
    counters: MockCounters = field(default_factory=MockCounters)

    def maybe_raise_transient(self) -> None:
        if self.config.failure_rate <= 0:
            return
        if self.rng.random() < self.config.failure_rate:
            raise TransientMockError("simulated transient external failure")

    async def _sleep_latency(self) -> None:
        low = self.config.latency_min_seconds
        high = self.config.latency_max_seconds
        if high <= 0:
            return
        delay = low if high <= low else self.rng.uniform(low, high)
        await asyncio.sleep(delay)

    async def run_slow_io(self, *, force_latency: float | None = None) -> None:
        """Simulate slow external I/O with optional injected latency."""

        async def _work() -> None:
            if force_latency is not None:
                await asyncio.sleep(force_latency)
            else:
                await self._sleep_latency()
            self.maybe_raise_transient()

        try:
            await asyncio.wait_for(_work(), timeout=self.config.mock_timeout_seconds)
        except TimeoutError as exc:
            msg = (
                f"mock external call exceeded timeout "
                f"({self.config.mock_timeout_seconds}s)"
            )
            raise MockTimeoutError(msg) from exc

    async def send_email_once(self, to: str, subject: str) -> str:
        await self.run_slow_io()
        self.counters.sends += 1
        return f"msg_{uuid.uuid4().hex[:12]}"

    async def schedule_followup_once(
        self,
        patient_id: str,
        when: datetime,
        note: str,
    ) -> str:
        await self.run_slow_io()
        self.counters.schedules += 1
        return f"fu_{uuid.uuid4().hex[:12]}"

    async def create_task_once(self, title: str, details: str) -> str:
        await self.run_slow_io()
        self.counters.tasks += 1
        return f"task_{uuid.uuid4().hex[:12]}"


def utc_now() -> datetime:
    return datetime.now(tz=UTC)

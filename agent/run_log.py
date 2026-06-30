"""Structured JSONL run logging for agent trajectories."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from schemas.decisions import Decision
from schemas.phi_redaction import redact_payload, redact_secret_values
from schemas.run_metrics import PlannerRunMetrics


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


@dataclass
class ToolCallRecord:
    """One MCP tool invocation in an agent run."""

    tool: str
    arguments_summary: dict[str, Any]
    result_summary: dict[str, Any]
    duration_ms: float
    timestamp: str = field(default_factory=_utc_now_iso)


@dataclass
class RunLog:
    """Audit-trail log for a single case run."""

    case_id: str
    drug: str
    condition: str
    started_at: str = field(default_factory=_utc_now_iso)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    decision: Decision | None = None
    planner_metrics: PlannerRunMetrics | None = None
    guardrail_event: dict[str, Any] | None = None
    field_provenance: dict[str, str] | None = None
    fhir_fallback: dict[str, Any] | None = None
    completed_at: str | None = None
    error: str | None = None

    def record_tool_call(
        self,
        *,
        tool: str,
        arguments_summary: dict[str, Any],
        result_summary: dict[str, Any],
        duration_ms: float,
    ) -> None:
        self.tool_calls.append(
            ToolCallRecord(
                tool=tool,
                arguments_summary=arguments_summary,
                result_summary=result_summary,
                duration_ms=duration_ms,
            )
        )

    def record_decision(
        self,
        decision: Decision,
        *,
        planner_metrics: PlannerRunMetrics | None = None,
    ) -> None:
        self.decision = decision
        self.planner_metrics = planner_metrics
        self.completed_at = _utc_now_iso()

    def record_error(self, message: str) -> None:
        self.error = message
        self.completed_at = _utc_now_iso()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "case_id": self.case_id,
            "drug": self.drug,
            "condition": self.condition,
            "started_at": self.started_at,
            "tool_calls": [
                {
                    "tool": record.tool,
                    "arguments_summary": record.arguments_summary,
                    "result_summary": record.result_summary,
                    "duration_ms": record.duration_ms,
                    "timestamp": record.timestamp,
                }
                for record in self.tool_calls
            ],
            "completed_at": self.completed_at,
            "error": redact_secret_values(self.error) if self.error else None,
        }
        if self.decision is not None:
            payload["decision"] = redact_payload(self.decision.model_dump(mode="json"))
        if self.planner_metrics is not None:
            payload["planner_metrics"] = self.planner_metrics.model_dump(mode="json")
        if self.guardrail_event is not None:
            payload["guardrail_event"] = redact_payload(self.guardrail_event)
        if self.field_provenance is not None:
            payload["field_provenance"] = redact_payload(self.field_provenance)
        if self.fhir_fallback is not None:
            payload["fhir_fallback"] = redact_payload(self.fhir_fallback)
        return redact_payload(payload)


class RunLogWriter:
    """Append structured run logs as JSON lines."""

    def __init__(self, runs_dir: Path) -> None:
        self.runs_dir = runs_dir
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.runs_dir / "agent_runs.jsonl"

    def write(self, run_log: RunLog) -> Path:
        line = redact_secret_values(
            json.dumps(run_log.to_dict(), ensure_ascii=False, default=str)
        )
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return self.path

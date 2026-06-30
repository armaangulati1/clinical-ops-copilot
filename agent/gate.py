"""Human approval gate enforcing the Phase 5 safety core."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from agent.approval_policy import requires_approval
from agent.approval_store import ApprovalStore
from agent.audit import AuditTrail
from agent.executor import ActionExecutor
from agent.injection_guard import InjectionScanResult
from agent.mcp_host import McpHost
from agent.run_log import RunLog
from schemas.approval import (
    ApprovalResolution,
    ApprovalStatus,
    AuditEventType,
    PendingApproval,
    WorkflowResult,
    WorkflowStatus,
)
from schemas.cases import Case
from schemas.decisions import Decision, ProposedAction
from schemas.extraction_result import ExtractionResult
from schemas.policies import PayerPolicy


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


class ApprovalGate:
    """Pause, persist, and resolve high-risk proposed actions."""

    def __init__(
        self,
        store: ApprovalStore,
        audit: AuditTrail,
        executor: ActionExecutor,
        *,
        confidence_threshold: float = 0.75,
    ) -> None:
        self._store = store
        self._audit = audit
        self._executor = executor
        self._confidence_threshold = confidence_threshold

    def set_mcp_host(self, host: McpHost) -> None:
        """Attach an MCP host for approved action execution."""
        self._executor.set_host(host)

    def record_run_log(self, run_log: RunLog) -> None:
        """Persist tool calls and decision from an agent run."""
        for record in run_log.tool_calls:
            self._audit.append(
                run_log.case_id,
                AuditEventType.TOOL_CALL,
                {
                    "tool": record.tool,
                    "arguments_summary": record.arguments_summary,
                    "result_summary": record.result_summary,
                    "duration_ms": record.duration_ms,
                    "timestamp": record.timestamp,
                },
            )
        if run_log.guardrail_event:
            self._audit.append(
                run_log.case_id,
                AuditEventType.GUARDRAIL_EVENT,
                run_log.guardrail_event,
            )
        if run_log.fhir_fallback:
            self._audit.append(
                run_log.case_id,
                AuditEventType.FHIR_FALLBACK,
                run_log.fhir_fallback,
            )
        if run_log.field_provenance:
            self._audit.append(
                run_log.case_id,
                AuditEventType.FIELD_PROVENANCE,
                {"field_provenance": run_log.field_provenance},
            )
        if run_log.decision is not None:
            self._audit.append(
                run_log.case_id,
                AuditEventType.DECISION,
                {"decision": run_log.decision.model_dump(mode="json")},
            )

    async def process_agent_result(
        self,
        case: Case,
        decision: Decision,
        extraction: ExtractionResult,
        policy: PayerPolicy,
        run_log: RunLog,
        *,
        injection_scan: InjectionScanResult | None = None,
    ) -> WorkflowResult:
        """Apply approval policy after the agent produces a Decision."""
        if injection_scan is not None and injection_scan.suspicious:
            self._audit.append(
                case.case_id,
                AuditEventType.SECURITY_EVENT,
                {
                    "event": "prompt_injection_detected",
                    "reason_count": len(injection_scan.reasons),
                    "sanitized_note_length": len(injection_scan.sanitized_text),
                },
            )
        self.record_run_log(run_log)

        if not requires_approval(
            decision,
            confidence_threshold=self._confidence_threshold,
        ):
            return WorkflowResult(
                case_id=case.case_id,
                status=WorkflowStatus.COMPLETED,
                decision=decision,
                message="No approval required; no clinic-ops action executed.",
            )

        approval_id = f"appr_{uuid.uuid4().hex[:12]}"
        pending = PendingApproval(
            approval_id=approval_id,
            case_id=case.case_id,
            decision=decision,
            extraction=extraction,
            policy=policy,
            proposed_action=decision.proposed_action,
            created_at=_utc_now(),
        )
        self._store.save(pending)
        self._audit.append(
            case.case_id,
            AuditEventType.APPROVAL_PENDING,
            {
                "approval_id": approval_id,
                "proposed_action": (
                    decision.proposed_action.model_dump(mode="json")
                    if decision.proposed_action
                    else None
                ),
            },
        )
        return WorkflowResult(
            case_id=case.case_id,
            status=WorkflowStatus.PENDING_APPROVAL,
            decision=decision,
            approval_id=approval_id,
            message="Workflow paused for human approval.",
        )

    async def approve(
        self,
        approval_id: str,
        *,
        reviewer: str = "reviewer",
    ) -> PendingApproval:
        """Approve and execute the proposed action exactly once."""
        existing = self._store.get(approval_id)
        if existing is None:
            msg = f"Unknown approval_id={approval_id!r}"
            raise KeyError(msg)
        if existing.status in {
            ApprovalStatus.APPROVED,
            ApprovalStatus.EDITED_AND_APPROVED,
        }:
            return existing
        if existing.status == ApprovalStatus.REJECTED:
            msg = f"Approval {approval_id!r} was rejected"
            raise ValueError(msg)
        return await self._resolve(
            approval_id,
            resolution=ApprovalResolution.APPROVE,
            reviewer=reviewer,
        )

    async def reject(
        self,
        approval_id: str,
        *,
        reviewer: str = "reviewer",
    ) -> PendingApproval:
        """Reject without executing any clinic-ops action."""
        pending = self._require_pending(approval_id)
        pending.status = ApprovalStatus.REJECTED
        pending.reviewer = reviewer
        pending.resolved_at = _utc_now()
        self._store.save(pending)
        self._audit.append(
            pending.case_id,
            AuditEventType.APPROVAL_RESOLVED,
            {
                "approval_id": approval_id,
                "resolution": ApprovalResolution.REJECT.value,
                "reviewer": reviewer,
            },
        )
        return pending

    async def approve_with_edit(
        self,
        approval_id: str,
        edited_action: ProposedAction,
        *,
        reviewer: str = "reviewer",
    ) -> PendingApproval:
        """Approve with reviewer-edited action args, then execute once."""
        pending = self._require_pending(approval_id)
        pending.edited_action = edited_action
        pending.status = ApprovalStatus.EDITED_AND_APPROVED
        pending.reviewer = reviewer
        pending.resolved_at = _utc_now()
        self._audit.append(
            pending.case_id,
            AuditEventType.APPROVAL_RESOLVED,
            {
                "approval_id": approval_id,
                "resolution": ApprovalResolution.EDIT_AND_APPROVE.value,
                "reviewer": reviewer,
                "edited_action": edited_action.model_dump(mode="json"),
            },
        )
        await self._execute_if_needed(pending, edited_action)
        self._store.save(pending)
        return pending

    async def _resolve(
        self,
        approval_id: str,
        *,
        resolution: ApprovalResolution,
        reviewer: str,
    ) -> PendingApproval:
        pending = self._require_pending(approval_id)
        pending.status = ApprovalStatus.APPROVED
        pending.reviewer = reviewer
        pending.resolved_at = _utc_now()
        action = pending.proposed_action
        self._audit.append(
            pending.case_id,
            AuditEventType.APPROVAL_RESOLVED,
            {
                "approval_id": approval_id,
                "resolution": resolution.value,
                "reviewer": reviewer,
            },
        )
        if action is not None:
            await self._execute_if_needed(pending, action)
        self._store.save(pending)
        return pending

    async def _execute_if_needed(
        self,
        pending: PendingApproval,
        action: ProposedAction,
    ) -> dict[str, Any] | None:
        if pending.execution_result is not None:
            return pending.execution_result
        result = await self._executor.execute_approved_action(
            pending.case_id,
            action,
        )
        pending.execution_result = result
        return result

    def _require_pending(self, approval_id: str) -> PendingApproval:
        pending = self._store.get(approval_id)
        if pending is None:
            msg = f"Unknown approval_id={approval_id!r}"
            raise KeyError(msg)
        if pending.status != ApprovalStatus.PENDING:
            msg = f"Approval {approval_id!r} is not pending (status={pending.status})"
            raise ValueError(msg)
        return pending

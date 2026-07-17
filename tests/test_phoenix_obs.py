"""Deterministic offline tests for the Phoenix/OpenInference instrumentation.

These exercise the tracing layer only (in-memory span exporter, stub planner,
mock MCP host). They assert span presence, span-kind and attribute correctness,
parent/child nesting, transparency of the wrappers, and -- most importantly for
a clinical context -- that no clinical-note PHI reaches a span.
"""

from __future__ import annotations

import asyncio

import pytest

from agent.llm import PlannerLlm, StubPlanner
from agent.mcp_host import DiscoveredTool
from evals.dataset import load_eval_dataset
from evals.runner import build_mock_host
from phoenix_obs import build_inmemory_tracer, traced_run_case
from schemas.cases import Case
from schemas.decisions import Decision, DecisionAction, ProposedAction
from schemas.extraction_result import ExtractionResult
from schemas.loader import DatasetEntry
from schemas.policies import PayerPolicy

PIPELINE_SPAN = "prior_auth.pipeline"
EXTRACT_SPAN = "mcp.tool.extract_chart"
POLICY_SPAN = "mcp.tool.get_payer_policy"
PLANNER_SPAN = "planner.plan_decision"
GUARDRAIL_SPAN = "guardrail.required_field"


def _entry(case_id: str) -> DatasetEntry:
    entries = load_eval_dataset()
    for entry in entries:
        if entry.case.case_id == case_id:
            return entry
    raise AssertionError(f"case {case_id} not in dataset")


def _run(entry: DatasetEntry, planner: PlannerLlm) -> tuple[object, object]:
    tracer, exporter = build_inmemory_tracer()

    async def _go() -> object:
        host = build_mock_host(entry)
        return await traced_run_case(entry.case, host, planner, tracer)

    result = asyncio.run(_go())
    return result, exporter


def _spans_by_name(exporter: object) -> dict[str, object]:
    spans = exporter.get_finished_spans()  # type: ignore[attr-defined]
    return {span.name: span for span in spans}


def test_pipeline_emits_expected_spans() -> None:
    _, exporter = _run(_entry("case-001"), StubPlanner())
    names = set(_spans_by_name(exporter))
    assert {
        PIPELINE_SPAN,
        EXTRACT_SPAN,
        POLICY_SPAN,
        PLANNER_SPAN,
        GUARDRAIL_SPAN,
    } <= names


def test_span_kinds_follow_openinference() -> None:
    _, exporter = _run(_entry("case-001"), StubPlanner())
    spans = _spans_by_name(exporter)
    kind = "openinference.span.kind"
    assert spans[PIPELINE_SPAN].attributes[kind] == "CHAIN"  # type: ignore[attr-defined]
    assert spans[EXTRACT_SPAN].attributes[kind] == "TOOL"  # type: ignore[attr-defined]
    assert spans[PLANNER_SPAN].attributes[kind] == "LLM"  # type: ignore[attr-defined]
    assert spans[GUARDRAIL_SPAN].attributes[kind] == "GUARDRAIL"  # type: ignore[attr-defined]


def test_child_spans_nest_under_pipeline_root() -> None:
    _, exporter = _run(_entry("case-001"), StubPlanner())
    spans = _spans_by_name(exporter)
    root_ctx = spans[PIPELINE_SPAN].get_span_context()  # type: ignore[attr-defined]
    for child_name in (EXTRACT_SPAN, POLICY_SPAN, PLANNER_SPAN, GUARDRAIL_SPAN):
        parent = spans[child_name].parent  # type: ignore[attr-defined]
        assert parent is not None
        assert parent.span_id == root_ctx.span_id


def test_planner_and_root_carry_decision_action() -> None:
    result, exporter = _run(_entry("case-001"), StubPlanner())
    spans = _spans_by_name(exporter)
    predicted = result.decision.action.value  # type: ignore[attr-defined]
    assert spans[PLANNER_SPAN].attributes["decision.action"] == predicted  # type: ignore[attr-defined]
    assert spans[PIPELINE_SPAN].attributes["decision.action"] == predicted  # type: ignore[attr-defined]
    assert predicted in spans[PLANNER_SPAN].attributes["output.value"]  # type: ignore[attr-defined]


def test_guardrail_span_records_untriggered_from_audit() -> None:
    _, exporter = _run(_entry("case-001"), StubPlanner())
    guardrail = _spans_by_name(exporter)[GUARDRAIL_SPAN]
    attrs = guardrail.attributes  # type: ignore[attr-defined]
    assert attrs["guardrail.triggered"] is False
    assert attrs["guardrail.source"] == "run_log.guardrail_event"


class _ForceSubmitPlanner(PlannerLlm):
    """Always returns a high-confidence submit, to provoke the guardrail."""

    async def plan_decision(
        self,
        case: Case,
        extraction: ExtractionResult,
        policy: PayerPolicy,
        discovered_tools: list[DiscoveredTool],
    ) -> Decision:
        return Decision(
            action=DecisionAction.SUBMIT,
            confidence=0.95,
            rationale="Forced submit for guardrail exercise.",
            missing_fields=[],
            proposed_action=ProposedAction(
                server="clinic-ops",
                tool="create_task",
                arguments={"title": "submit", "details": "submit"},
            ),
        )


def test_guardrail_span_records_triggered_event() -> None:
    # case-007 has a required field the mock extraction cannot fill, so forcing a
    # submit trips the required-field guardrail inside run_case.
    result, exporter = _run(_entry("case-007"), _ForceSubmitPlanner())
    assert result.run_log.guardrail_event  # type: ignore[attr-defined]
    guardrail = _spans_by_name(exporter)[GUARDRAIL_SPAN]
    attrs = guardrail.attributes  # type: ignore[attr-defined]
    assert attrs["guardrail.triggered"] is True
    assert attrs["guardrail.original_action"] == "submit"
    assert attrs["guardrail.overridden_action"] == "request-more-info"


def test_no_clinical_note_phi_reaches_spans() -> None:
    # case-001's note contains "Patient: Jordan Blake"; the repo's PHI redaction
    # must scrub it before it lands on any span attribute.
    _, exporter = _run(_entry("case-001"), StubPlanner())
    spans = exporter.get_finished_spans()  # type: ignore[attr-defined]
    blob = "".join(str(span.attributes) for span in spans)
    assert "Jordan Blake" not in blob
    assert "[NAME]" in blob


def test_wrappers_do_not_change_the_decision() -> None:
    # The instrumentation must be transparent: the traced run produces the same
    # decision as the unwrapped pipeline on the same case.
    from agent.runner import run_case

    entry = _entry("case-001")

    async def _plain() -> str:
        host = build_mock_host(entry)
        result = await run_case(entry.case, host, StubPlanner())
        return result.decision.action.value

    plain_action = asyncio.run(_plain())
    traced_result, _ = _run(entry, StubPlanner())
    assert traced_result.decision.action.value == plain_action  # type: ignore[attr-defined]


def test_readme_keeps_the_honest_framing() -> None:
    # Guard the demo-scope framing in CI: no false affiliation or production
    # claims, and the required honesty phrases stay present.
    from pathlib import Path

    readme = Path(__file__).resolve().parent.parent / "phoenix_obs" / "README.md"
    raw = readme.read_text(encoding="utf-8").lower()
    # Normalize markdown emphasis + line wrapping so phrase checks are robust.
    text = " ".join(raw.replace("*", "").split())
    # "production observability" may appear only when explicitly negated.
    assert text.count("production observability") == text.count(
        "not production observability"
    )
    assert "not production observability" in text
    assert "production-grade observability" not in text
    # The disclaimer of affiliation must survive, phrased as a negation.
    assert "not affiliated with or endorsed by arize" in text
    assert "independent demonstration" in text
    assert "demo scope" in text
    assert "self-authored synthetic data" in text


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

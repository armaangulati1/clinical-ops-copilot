"""Run FHIR-backed evaluation over labeled Synthea patients."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from pydantic import BaseModel, Field

from agent.config import (
    CLINICAL_DATA_AUTH_TOKEN_ENV,
    CLINICAL_DATA_URL_ENV,
    AgentConfig,
    load_config,
)
from agent.llm import AnthropicPlanner, PlannerLlm, StubPlanner
from agent.mcp_host import StdioMcpHost
from agent.run_log import RunLogWriter
from evals.aggregate import build_eval_results
from evals.fhir.dataset import load_fhir_eval_dataset
from evals.metrics.classification import (
    ClassificationMetrics,
    compute_classification_metrics,
)
from evals.models import EvalIntegrityNote, EvalResults
from evals.report import format_results_table
from evals.runner import build_mock_host, run_dataset_eval
from schemas.cases import Case
from schemas.loader import DatasetEntry

FHIR_EVAL_FHIR_BASE_URL = "http://localhost:8080/fhir"


def build_fhir_eval_config(project_root: Path) -> AgentConfig:
    """Local FHIR eval config: stdio clinical-data only, never remote HTTP MCP."""
    return replace(
        load_config(project_root),
        extractor_backend="stub",
        clinical_data_url=None,
        clinical_data_auth_token=None,
    )


class FhirEvalComparison(BaseModel):
    """Side-by-side decision metrics for FHIR vs note-only on the same cases."""

    note_only: ClassificationMetrics
    note: str = Field(
        default=(
            "Note-only path uses the same cases with patient_id cleared and "
            "stub note extraction (no FHIR fusion)."
        )
    )


class FhirEvalResults(BaseModel):
    """FHIR eval report with honest caveats and optional note-only baseline."""

    integrity: EvalIntegrityNote
    labels_confirmed: bool
    patient_ids_by_case: dict[str, str]
    fhir: EvalResults
    comparison: FhirEvalComparison | None = None
    caveats: list[str] = Field(default_factory=list)


def _sparse_note_case(entry: DatasetEntry) -> Case:
    """Same case input without patient_id for note-only baseline."""
    return entry.case.model_copy(update={"patient_id": None})


async def run_fhir_eval(
    project_root: Path,
    *,
    planner: PlannerLlm | None = None,
    include_note_only_baseline: bool = True,
    require_confirmed_labels: bool = False,
) -> FhirEvalResults:
    """Evaluate the agent on the FHIR-backed labeled set (requires live HAPI)."""
    entries, manifest = load_fhir_eval_dataset(project_root)
    labels_confirmed = bool(manifest.get("labels_confirmed", False))
    if require_confirmed_labels and not labels_confirmed:
        msg = (
            "FHIR eval labels are not yet confirmed. "
            "Review evals/fhir/LABEL_REVIEW.md and set labels_confirmed=true "
            "in evals/fhir/manifest.json before scoring."
        )
        raise RuntimeError(msg)

    config = build_fhir_eval_config(project_root)
    active_planner = planner or _default_fhir_planner(config)
    planner_model = _planner_model_name(active_planner, config)

    writer = RunLogWriter(project_root / "data/runs/eval/fhir")
    host = await _connect_fhir_stdio_host(config)
    try:
        fhir_case_results = await run_dataset_eval(
            entries,
            active_planner,
            host=host,
            config=config,
            writer=writer,
        )
    finally:
        await host.close()

    note_only_metrics: ClassificationMetrics | None = None
    if include_note_only_baseline:
        note_entries = [
            DatasetEntry(_sparse_note_case(entry), entry.label) for entry in entries
        ]
        note_results = await run_dataset_eval(
            note_entries,
            active_planner,
            host_factory=lambda entry: build_mock_host(entry, config=config),
            config=config,
        )
        note_only_metrics = compute_classification_metrics(
            [result.truth_action for result in note_results],
            [result.predicted_action for result in note_results],
        )

    patient_ids = {entry.case.case_id: entry.case.patient_id or "" for entry in entries}
    caveats = [
        "Small n (~12) Synthea patients on local HAPI; not clinical ground truth.",
        (
            "Labels are derived by applying the Ozempic/T2D payer policy to the "
            "same structured FHIR facts the agent reads — a decision-logic eval, "
            "not independent chart review."
        ),
    ]
    if isinstance(active_planner, StubPlanner):
        caveats.append(
            "StubPlanner checks field presence only; deny-risk labels require "
            "policy threshold reasoning that StubPlanner does not perform."
        )
    if not labels_confirmed:
        caveats.insert(
            0,
            "LABELS PENDING HUMAN CONFIRMATION — see evals/fhir/LABEL_REVIEW.md.",
        )

    integrity = EvalIntegrityNote(
        labels_read_only_in_evals=True,
        agent_runtime_reads_labels=False,
        seed_data_used_for_case_authoring=False,
        caveat=(
            "FHIR eval labels in evals/fhir/labels.json were derived from "
            "policy-on-FHIR facts via evals/fhir/label_derivation.py and "
            "human-confirmed in LABEL_REVIEW.md."
        ),
    )

    fhir_eval = build_eval_results(
        entries,
        fhir_case_results,
        planner_model=planner_model,
        notes=[
            "FHIR-backed eval path (CLINICAL_DATA_SOURCE=fhir, live HAPI).",
            f"Patients: {len(entries)} Synthea IDs on Ozempic/T2D policy.",
        ],
    )
    fhir_eval = fhir_eval.model_copy(update={"integrity": integrity})

    comparison = None
    if note_only_metrics is not None:
        comparison = FhirEvalComparison(note_only=note_only_metrics)

    return FhirEvalResults(
        integrity=integrity,
        labels_confirmed=labels_confirmed,
        patient_ids_by_case=patient_ids,
        fhir=fhir_eval,
        comparison=comparison,
        caveats=caveats,
    )


async def _connect_fhir_stdio_host(config: AgentConfig) -> StdioMcpHost:
    """Connect local stdio MCP with FHIR clinical-data mode (ignores remote URL env)."""
    prior = {
        "CLINICAL_DATA_SOURCE": os.environ.get("CLINICAL_DATA_SOURCE"),
        "FHIR_BASE_URL": os.environ.get("FHIR_BASE_URL"),
        "EXTRACTOR_BACKEND": os.environ.get("EXTRACTOR_BACKEND"),
        CLINICAL_DATA_URL_ENV: os.environ.get(CLINICAL_DATA_URL_ENV),
        CLINICAL_DATA_AUTH_TOKEN_ENV: os.environ.get(CLINICAL_DATA_AUTH_TOKEN_ENV),
    }
    os.environ["CLINICAL_DATA_SOURCE"] = "fhir"
    os.environ["FHIR_BASE_URL"] = FHIR_EVAL_FHIR_BASE_URL
    os.environ["EXTRACTOR_BACKEND"] = "stub"
    os.environ.pop(CLINICAL_DATA_URL_ENV, None)
    os.environ.pop(CLINICAL_DATA_AUTH_TOKEN_ENV, None)
    local_config = replace(
        config,
        extractor_backend="stub",
        clinical_data_url=None,
        clinical_data_auth_token=None,
    )
    try:
        return await StdioMcpHost.connect(local_config)
    finally:
        for key, value in prior.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def format_fhir_results_table(results: FhirEvalResults) -> str:
    """Human-readable FHIR eval table with caveats and note-only comparison."""
    lines = [
        "FHIR-backed prior-auth evaluation",
        "=================================",
        f"Labels confirmed: {results.labels_confirmed}",
        "",
    ]
    for caveat in results.caveats:
        lines.append(f"CAVEAT: {caveat}")
    lines.append("")
    lines.append(format_results_table(results.fhir))
    if results.comparison is not None:
        note = results.comparison.note_only
        fhir_cls = results.fhir.classification
        lines.extend(
            [
                "",
                "Comparison: note-only baseline (patient_id cleared, stub extraction)",
                "-------------------------------------------------------------------",
                f"{'Path':<12} {'Accuracy':>10} {'Macro-F1':>10}",
                f"{'FHIR':<12} {fhir_cls.accuracy:>10.4f} {fhir_cls.macro_f1:>10.4f}",
                f"{'Note-only':<12} {note.accuracy:>10.4f} {note.macro_f1:>10.4f}",
                "",
                "Note-only per-class F1:",
            ]
        )
        for label, metrics in note.per_class.items():
            lines.append(f"  {label:20s} F1={metrics.f1:.3f} (n={metrics.support})")
    return "\n".join(lines)


def write_fhir_results(
    results: FhirEvalResults,
    *,
    project_root: Path,
) -> tuple[Path, Path]:
    """Persist FHIR eval JSON + markdown summary."""
    results_dir = project_root / "evals/results"
    json_path = results_dir / "fhir.json"
    summary_path = results_dir / "fhir_summary.md"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(results.model_dump_json(indent=2), encoding="utf-8")
    summary_path.write_text(format_fhir_results_table(results), encoding="utf-8")
    return json_path, summary_path


async def run_fhir_eval_command(
    project_root: Path,
    *,
    use_live_planner: bool = True,
) -> None:
    """Entry for `uv run evals --fhir`."""
    from fhir_client.client import FhirClient

    _load_project_env(project_root)

    if not FhirClient().is_reachable():
        msg = "Local HAPI FHIR server not reachable (start with make fhir-up)"
        raise RuntimeError(msg)

    planner: PlannerLlm | None = None
    if use_live_planner:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            msg = (
                "ANTHROPIC_API_KEY is required for live FHIR eval "
                "(--fhir-offline for stub)"
            )
            raise RuntimeError(msg)
        config = build_fhir_eval_config(project_root)
        planner = AnthropicPlanner(config.anthropic_model)

    results = await run_fhir_eval(project_root, planner=planner)
    json_path, summary_path = write_fhir_results(results, project_root=project_root)
    print(format_fhir_results_table(results))
    print()
    print(f"Wrote {json_path}")
    print(f"Wrote {summary_path}")


def _load_project_env(project_root: Path) -> None:
    """Load repository .env when present (same pattern as local agent runs)."""
    env_path = project_root / ".env"
    if not env_path.is_file():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(env_path)


def _default_fhir_planner(config: AgentConfig) -> PlannerLlm:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicPlanner(config.anthropic_model)
    return StubPlanner()


def _planner_model_name(planner: PlannerLlm, config: AgentConfig) -> str:
    if isinstance(planner, StubPlanner):
        return "stub"
    if isinstance(planner, AnthropicPlanner):
        return config.anthropic_model
    return config.anthropic_model

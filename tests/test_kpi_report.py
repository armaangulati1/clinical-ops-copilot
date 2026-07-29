"""Tests for the KPI report artifact, the backfill path, and the CLI.

These cover the parts a reader of the repository actually sees: the committed
report must be current, it must state its own scope, and the backfill that
recovers operational signals from an older run must refuse to touch a run log
that is not provably the same run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.llm import StubPlanner
from evals.aggregate import build_eval_results
from evals.dataset import load_eval_dataset
from evals.models import EvalResults
from evals.runner import build_mock_host, run_dataset_eval
from kpi.__main__ import build_parser, build_report_for, report_paths
from kpi.backfill import (
    RunLogMismatchError,
    backfill_intervention_signals,
    load_run_log_signals,
)
from kpi.compute import compute_kpi_report
from kpi.models import UnmeasuredKpi
from kpi.report import render_json, render_markdown

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCKED_RESULTS = PROJECT_ROOT / "evals/results/locked_test.json"
REPORTS_DIR = PROJECT_ROOT / "kpi/reports"
CASES_DIR = PROJECT_ROOT / "data/cases"
LABELS_PATH = PROJECT_ROOT / "data/labels/labels.json"

# The fact-lock bans this word for this project: it runs on synthetic data at
# demo scope. The guard is spelled in pieces so the scan cannot match itself.
BANNED_WORD = "produc" + "tion"
# Built from its code point for the same reason: the em dash is banned in this
# repository's written output, so the guard must not carry a literal one.
EM_DASH = chr(0x2014)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _committed_report_paths() -> tuple[Path, Path]:
    return report_paths(LOCKED_RESULTS, REPORTS_DIR)


def test_committed_kpi_report_is_current() -> None:
    """CI regenerates the report; the committed copy must already match."""
    report = build_report_for(LOCKED_RESULTS, split_name="locked_test")
    json_path, markdown_path = _committed_report_paths()
    assert json_path.exists(), f"{json_path} is missing"
    assert markdown_path.exists(), f"{markdown_path} is missing"
    assert json_path.read_text(encoding="utf-8") == render_json(report)
    assert markdown_path.read_text(encoding="utf-8") == render_markdown(report)


def test_committed_report_states_its_own_scope() -> None:
    """The artifact has to carry its limits, not rely on a reader knowing."""
    _, markdown_path = _committed_report_paths()
    text = markdown_path.read_text(encoding="utf-8")
    for required in (
        "synthetic",
        "demo scope",
        "single machine",
        "concurrency 1",
        "adoption",
    ):
        assert required in text, f"report does not disclose {required!r}"
    # Every KPI section must carry an N.
    assert "16 decisions" in text


def test_committed_report_avoids_the_banned_word_and_em_dashes() -> None:
    json_path, markdown_path = _committed_report_paths()
    for path in (json_path, markdown_path, *sorted(PROJECT_ROOT.glob("kpi/*.py"))):
        text = path.read_text(encoding="utf-8")
        assert BANNED_WORD not in text.lower(), f"{path} uses a banned word"
        assert EM_DASH not in text, f"{path} contains an em dash"
    # Control: the scan can return a positive, so a clean result means
    # something. A negative result from a check that cannot fail is not
    # evidence.
    assert BANNED_WORD in f"the word {BANNED_WORD} appears here"
    assert EM_DASH in f"an em dash {EM_DASH} here"


def test_report_renders_abstentions_rather_than_hiding_them() -> None:
    report = build_report_for(LOCKED_RESULTS, split_name="locked_test")
    report.cost = None
    report.not_computed.append(
        UnmeasuredKpi(name="cost", reason="No tokens recorded in this run.")
    )
    text = render_markdown(report)
    assert "**cost**: not computed" in text
    assert "No tokens recorded in this run." in text
    assert "Mean cost per decision" not in text


def test_render_is_deterministic() -> None:
    """A drift gate is only meaningful if the render carries no clock."""
    first = build_report_for(LOCKED_RESULTS, split_name="locked_test")
    second = build_report_for(LOCKED_RESULTS, split_name="locked_test")
    assert render_markdown(first) == render_markdown(second)
    assert render_json(first) == render_json(second)


def test_backfill_recovers_signals_without_changing_predictions(
    tmp_path: Path,
) -> None:
    results = EvalResults.model_validate_json(
        LOCKED_RESULTS.read_text(encoding="utf-8")
    )
    before = [
        (result.case_id, result.predicted_action, result.correct)
        for result in results.case_results
    ]
    log_path = tmp_path / "agent_runs.jsonl"
    log_path.write_text(
        "\n".join(
            json.dumps(
                {
                    "case_id": result.case_id,
                    "decision": {
                        "action": result.predicted_action,
                        "confidence": 0.99,
                        "rationale": "recorded decision rationale",
                        "missing_fields": [],
                        "needs_review": [],
                        "proposed_action": None,
                    },
                }
            )
            for result in results.case_results
        ),
        encoding="utf-8",
    )
    summary = backfill_intervention_signals(
        results,
        load_run_log_signals(log_path),
    )
    assert summary.n_cases == len(before)
    after = [
        (result.case_id, result.predicted_action, result.correct)
        for result in results.case_results
    ]
    assert after == before
    assert all(result.approval_required is not None for result in results.case_results)


def test_backfill_refuses_a_run_log_from_a_different_run(tmp_path: Path) -> None:
    """A silently mismatched log would put another run's numbers in the report."""
    results = EvalResults.model_validate_json(
        LOCKED_RESULTS.read_text(encoding="utf-8")
    )
    wrong_action = (
        "deny-risk"
        if results.case_results[0].predicted_action != "deny-risk"
        else "submit"
    )
    log_path = tmp_path / "agent_runs.jsonl"
    log_path.write_text(
        json.dumps(
            {
                "case_id": results.case_results[0].case_id,
                "decision": {
                    "action": wrong_action,
                    "confidence": 0.9,
                    "rationale": "a different run entirely",
                    "missing_fields": [],
                    "needs_review": [],
                    "proposed_action": None,
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RunLogMismatchError):
        backfill_intervention_signals(results, load_run_log_signals(log_path))


def test_backfill_refuses_a_log_missing_cases(tmp_path: Path) -> None:
    results = EvalResults.model_validate_json(
        LOCKED_RESULTS.read_text(encoding="utf-8")
    )
    log_path = tmp_path / "agent_runs.jsonl"
    log_path.write_text("", encoding="utf-8")
    with pytest.raises(RunLogMismatchError):
        backfill_intervention_signals(results, load_run_log_signals(log_path))


def test_cli_check_passes_on_the_committed_report(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "report",
            "--results",
            LOCKED_RESULTS.as_posix(),
            "--out-dir",
            REPORTS_DIR.as_posix(),
            "--split-name",
            "locked_test",
            "--check",
        ]
    )
    assert args.func(args) == 0
    assert "current" in capsys.readouterr().out


def test_cli_check_fails_on_drift(tmp_path: Path) -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "report",
            "--results",
            LOCKED_RESULTS.as_posix(),
            "--out-dir",
            tmp_path.as_posix(),
            "--split-name",
            "locked_test",
            "--check",
        ]
    )
    assert args.func(args) == 1


def test_cli_report_writes_both_artifacts(tmp_path: Path) -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "report",
            "--results",
            LOCKED_RESULTS.as_posix(),
            "--out-dir",
            tmp_path.as_posix(),
            "--split-name",
            "locked_test",
        ]
    )
    assert args.func(args) == 0
    json_path, markdown_path = report_paths(LOCKED_RESULTS, tmp_path)
    assert json_path.exists()
    assert markdown_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["scope"]["n_decisions"] == 16
    assert payload["quality"]["macro_f1"] == pytest.approx(0.9373)


@pytest.mark.anyio
async def test_a_fresh_offline_run_populates_the_kpi_signals() -> None:
    """End-to-end proof that the instrumentation fills the new fields.

    This runs the real eval path with the stub planner and mock MCP host, so
    it calls no model and is safe in CI.
    """
    entries = load_eval_dataset(cases_dir=CASES_DIR, labels_path=LABELS_PATH)
    subset = [
        entry
        for entry in entries
        if entry.case.case_id in {"case-001", "case-007", "case-012"}
    ]
    assert len(subset) == 3
    case_results = await run_dataset_eval(
        subset,
        StubPlanner(),
        host_factory=build_mock_host,
    )
    assert all(result.approval_required is not None for result in case_results)
    assert all(result.guardrail_triggered is not None for result in case_results)

    results = build_eval_results(entries, case_results, planner_model="stub")
    report = compute_kpi_report(
        results,
        source_results_path="offline-run",
        split_name="offline-smoke",
    )
    assert report.human_intervention is not None
    assert report.human_intervention.n_decisions == 3
    assert report.throughput is not None
    assert report.cycle_time is not None
    # The stub planner spends no tokens, so cost must abstain here.
    assert report.cost is None
    assert [item.name for item in report.not_computed] == ["cost"]

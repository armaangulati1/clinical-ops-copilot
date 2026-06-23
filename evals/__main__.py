"""Evaluation harness entry point (`uv run evals`)."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from agent.config import load_config
from agent.llm import AnthropicPlanner, PlannerLlm, StubPlanner
from agent.mcp_host import StdioMcpHost
from agent.run_log import RunLogWriter
from evals.aggregate import build_eval_results, human_judge_agreement
from evals.dataset import load_eval_dataset
from evals.human_ratings import load_human_ratings
from evals.judge import AnthropicEmailJudge, EmailJudge, FixtureEmailJudge
from evals.models import CaseEvalResult
from evals.report import format_results_table, write_results
from evals.runner import build_mock_host, run_dataset_eval


async def _score_validation_emails(
    case_results: list[CaseEvalResult],
    judge: EmailJudge,
    validation_case_ids: set[str],
) -> None:
    for result in case_results:
        if result.case_id not in validation_case_ids:
            continue
        if result.drafted_email is None:
            continue
        subject = result.email_subject or ""
        score = await judge.score_email(
            case_id=result.case_id,
            subject=subject,
            body=result.drafted_email,
            missing_fields=result.missing_fields,
        )
        result.judge_email_score = score.overall_score


async def run_eval(
    *,
    project_root: Path,
    use_live_planner: bool,
    use_stdio_host: bool,
    skip_judge: bool,
    fixture_judge_path: Path | None,
    split_path: Path | None = None,
) -> None:
    entries = load_eval_dataset(
        cases_dir=project_root / "data/cases",
        labels_path=project_root / "data/labels/labels.json",
    )
    split_name = "full"
    if split_path is not None:
        from evals.splits import load_eval_split

        split = load_eval_split(split_path)
        allowed = set(split.case_ids)
        entries = [entry for entry in entries if entry.case.case_id in allowed]
        entries.sort(key=lambda entry: split.case_ids.index(entry.case.case_id))
        split_name = split.name
        if len(entries) != len(split.case_ids):
            msg = f"Split {split_path} missing cases from dataset"
            raise ValueError(msg)
    config = load_config(project_root)
    writer = RunLogWriter(project_root / f"data/runs/eval/{split_name}")

    if use_live_planner:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            msg = "ANTHROPIC_API_KEY is required for live evals"
            raise RuntimeError(msg)
        planner: PlannerLlm = AnthropicPlanner(config.anthropic_model)
        planner_model = config.anthropic_model
    else:
        planner = StubPlanner()
        planner_model = "stub"

    notes: list[str] = []
    if split_path is not None:
        notes.append(f"Eval split: {split_path} ({len(entries)} cases)")
    if use_stdio_host and use_live_planner:
        host = await StdioMcpHost.connect(config)
        try:
            case_results = await run_dataset_eval(
                entries,
                planner,
                host=host,
                config=config,
                writer=writer,
            )
        finally:
            await host.close()
    else:
        notes.append(
            "Used MockMcpHost with stub extraction (offline eval path). "
            "Re-run with --live for full MCP + Claude stack."
        )

        def mock_host_factory(entry: Any) -> Any:
            return build_mock_host(entry, config=config)

        case_results = await run_dataset_eval(
            entries,
            planner,
            host_factory=mock_host_factory,
            config=config,
            writer=writer,
        )

    human_ratings = load_human_ratings(project_root / "evals/human_email_ratings.json")
    validation_ids = set(human_ratings.scores_by_case())

    if not skip_judge:
        judge: EmailJudge | None
        if fixture_judge_path is not None:
            from evals.judge import load_fixture_judge_scores

            judge = FixtureEmailJudge(
                load_fixture_judge_scores(str(fixture_judge_path))
            )
            notes.append(f"Email judge: fixture scores from {fixture_judge_path}")
        elif use_live_planner:
            judge = AnthropicEmailJudge(config.anthropic_model)
            notes.append("Email judge: live Claude rubric scoring.")
        else:
            judge = None
            notes.append("Email judge skipped (no live planner and no fixture judge).")

        if judge is not None:
            await _score_validation_emails(case_results, judge, validation_ids)

    agreement = human_judge_agreement(human_ratings.scores_by_case(), case_results)
    judged_n = sum(1 for result in case_results if result.judge_email_score is not None)

    results = build_eval_results(
        entries,
        case_results,
        judge_agreement=agreement,
        judge_validation_n=judged_n,
        planner_model=planner_model,
        notes=notes,
    )
    results_dir = project_root / "evals/results"
    json_path, summary_path = write_results(
        results,
        json_path=results_dir / f"{split_name}.json",
        summary_path=results_dir / f"{split_name}_summary.md",
    )
    # Also refresh latest.* when running the full 48-case eval.
    if split_name == "full":
        write_results(
            results,
            json_path=results_dir / "latest.json",
            summary_path=results_dir / "latest_summary.md",
        )
    print(format_results_table(results))
    print()
    print(f"Wrote {json_path}")
    print(f"Wrote {summary_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prior-auth agent evaluation harness")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root (default: cwd)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use stub planner + mock MCP (no API key; for CI/dev baselines).",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use live Claude planner and stdio MCP (default unless --offline).",
    )
    parser.add_argument(
        "--skip-judge",
        action="store_true",
        help="Skip LLM-as-judge email scoring.",
    )
    parser.add_argument(
        "--split",
        type=Path,
        default=None,
        help="JSON file of case_ids to evaluate (e.g. evals/splits/dev.json).",
    )
    parser.add_argument(
        "--fixture-judge",
        type=Path,
        default=None,
        help="Path to fixture judge scores JSON (offline judge validation).",
    )
    args = parser.parse_args()

    use_live = not args.offline
    if args.live and args.offline:
        parser.error("Use only one of --live or --offline")

    try:
        asyncio.run(
            run_eval(
                project_root=args.project_root,
                use_live_planner=use_live,
                use_stdio_host=use_live,
                skip_judge=args.skip_judge,
                fixture_judge_path=args.fixture_judge,
                split_path=args.split,
            )
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

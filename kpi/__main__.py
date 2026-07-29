"""KPI harness entry point (`uv run kpi`).

Reads a recorded evaluation run and writes the operational KPI report. No
model is called, so this is safe to run offline and inside CI.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from evals.models import EvalResults
from kpi.backfill import RunLogMismatchError, backfill_results_file
from kpi.compute import compute_kpi_report
from kpi.models import KpiReport
from kpi.report import render_json, render_markdown, write_report

DEFAULT_RESULTS = Path("evals/results/locked_test.json")
DEFAULT_OUT_DIR = Path("kpi/reports")
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def repo_relative(path: Path) -> str:
    """Path as recorded in the report.

    Always repository-relative so the artifact renders identically no matter
    which working directory or absolute prefix produced it. Without this the
    CI drift gate would fire on a checkout path difference alone.
    """
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def report_paths(results_path: Path, out_dir: Path) -> tuple[Path, Path]:
    """Return the (json, markdown) report paths for an eval-results file."""
    stem = results_path.stem
    return out_dir / f"{stem}_kpi.json", out_dir / f"{stem}_kpi.md"


def load_results(results_path: Path) -> EvalResults:
    return EvalResults.model_validate_json(results_path.read_text(encoding="utf-8"))


def build_report_for(
    results_path: Path,
    *,
    split_name: str | None = None,
) -> KpiReport:
    """Load a recorded eval run and compute its KPI report."""
    results = load_results(results_path)
    return compute_kpi_report(
        results,
        source_results_path=repo_relative(results_path),
        split_name=split_name or results_path.stem,
    )


def _run_report(args: argparse.Namespace) -> int:
    results_path: Path = args.results
    out_dir: Path = args.out_dir
    report = build_report_for(results_path, split_name=args.split_name)
    json_path, markdown_path = report_paths(results_path, out_dir)

    if args.check:
        expected_json = render_json(report)
        expected_markdown = render_markdown(report)
        stale: list[str] = []
        for path, expected in (
            (json_path, expected_json),
            (markdown_path, expected_markdown),
        ):
            if not path.exists():
                stale.append(f"{path} is missing")
                continue
            if path.read_text(encoding="utf-8") != expected:
                stale.append(f"{path} is out of date")
        if stale:
            for message in stale:
                print(f"KPI report drift: {message}", file=sys.stderr)
            print(
                "Regenerate with: uv run kpi report "
                f"--results {results_path.as_posix()}",
                file=sys.stderr,
            )
            return 1
        print(f"KPI report is current for {results_path.as_posix()}")
        return 0

    write_report(report, json_path=json_path, markdown_path=markdown_path)
    print(render_markdown(report))
    print(f"Wrote {json_path}")
    print(f"Wrote {markdown_path}")
    return 0


def _run_backfill(args: argparse.Namespace) -> int:
    try:
        summary = backfill_results_file(args.results, args.run_log)
    except RunLogMismatchError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        f"Backfilled {summary.n_cases} decisions in "
        f"{args.results.as_posix()}: "
        f"{summary.n_approval_required} required approval, "
        f"{summary.n_guardrail_triggered} hit the guardrail."
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kpi",
        description="Operational KPI harness over recorded agent eval runs.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    report_parser = subparsers.add_parser(
        "report",
        help="Compute KPIs from a recorded eval run and write the report.",
    )
    report_parser.add_argument(
        "--results",
        type=Path,
        default=DEFAULT_RESULTS,
        help=f"Eval results JSON (default: {DEFAULT_RESULTS}).",
    )
    report_parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Directory for the report (default: {DEFAULT_OUT_DIR}).",
    )
    report_parser.add_argument(
        "--split-name",
        type=str,
        default=None,
        help="Override the split label shown in the report.",
    )
    report_parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if the committed report differs from a fresh render.",
    )
    report_parser.set_defaults(func=_run_report)

    backfill_parser = subparsers.add_parser(
        "backfill",
        help=(
            "Recover approval-gate and guardrail outcomes for a run recorded "
            "before this instrumentation, using its run log. Replays a pure "
            "policy function; calls no model and changes no prediction."
        ),
    )
    backfill_parser.add_argument("--results", type=Path, required=True)
    backfill_parser.add_argument("--run-log", type=Path, required=True)
    backfill_parser.set_defaults(func=_run_backfill)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()

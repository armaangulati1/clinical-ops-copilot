"""CLI entry point for the prior-auth agent."""

from __future__ import annotations

import argparse
from pathlib import Path

import anyio

from agent.config import load_config
from agent.held_out import HELD_OUT_CASE_IDS
from agent.llm import AnthropicPlanner
from agent.mcp_host import StdioMcpHost
from agent.run_log import RunLogWriter
from agent.runner import run_case
from schemas.loader import load_case_file, load_cases


async def _run_cases(case_ids: list[str], project_root: Path) -> None:
    config = load_config(project_root)
    writer = RunLogWriter(config.runs_dir)
    host = await StdioMcpHost.connect(config)
    planner = AnthropicPlanner(config.anthropic_model)
    try:
        cases_by_id = {
            case.case_id: case for case in load_cases(project_root / "data/cases")
        }
        for case_id in case_ids:
            case = cases_by_id[case_id]
            result = await run_case(
                case,
                host,
                planner,
                config=config,
                writer=writer,
            )
            print(
                f"{case_id}: {result.decision.action.value} "
                f"(confidence={result.decision.confidence:.2f})"
            )
    finally:
        await host.close()
    print(f"Run logs appended to {writer.path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prior-auth agent orchestrator")
    parser.add_argument(
        "--held-out",
        action="store_true",
        help="Run the 10 held-out evaluation cases",
    )
    parser.add_argument(
        "--cases",
        type=str,
        default="",
        help="Comma-separated case IDs (e.g. case-001,case-002)",
    )
    parser.add_argument(
        "--case",
        type=str,
        default="",
        help="Run a single case ID (shorthand for --cases)",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root (default: cwd)",
    )
    args = parser.parse_args()

    if args.held_out:
        case_ids = list(HELD_OUT_CASE_IDS)
    elif args.case:
        case_ids = [args.case.strip()]
    elif args.cases:
        case_ids = [part.strip() for part in args.cases.split(",") if part.strip()]
    else:
        parser.error("Provide --held-out or --cases")

    for case_id in case_ids:
        path = args.project_root / "data/cases" / f"{case_id}.json"
        load_case_file(path)

    anyio.run(_run_cases, case_ids, args.project_root)


if __name__ == "__main__":
    main()

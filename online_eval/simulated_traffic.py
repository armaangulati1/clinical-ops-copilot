"""Generate simulated production traffic through the instrumented agent.

Read this docstring before quoting any number this loop produces.

**There is no production deployment behind this.** This repository has no users
and no live workload. This module *manufactures* traffic: it replays the repo's
own synthetic prior-auth cases through the real agent under the existing
``phoenix_obs`` instrumentation, and the resulting OpenInference spans land in
the trace store. Every downstream stage of the loop is identical to what it
would be against real traffic, but the traffic is generated here, and nothing in
this package should be described as monitoring a production system.

What is genuine about it:

* The agent really runs. Decisions are the agent's, not scripted.
* Latency is measured wall clock, never synthesized.
* Spans go through a real OTel processor and exporter.

How drift is produced, and why that is honest: the ``shifted`` profile changes
the **case mix** it draws from, oversampling cases labeled harder. The agent is
untouched and its decisions are not tampered with; the population it faces is
what changes, which is the most common real cause of an online-eval regression.
No decision is ever flipped to fake a drop.

The label file is read here only to weight the sampling. The agent still
receives the case alone, exactly as ``evals.runner`` gives it, so the
repository's rule that labels never reach the agent runtime is preserved.
"""

from __future__ import annotations

import argparse
import asyncio
import random
from pathlib import Path

from agent.llm import PlannerLlm, StubPlanner
from evals.runner import build_mock_host
from online_eval.config import OnlineEvalConfig
from online_eval.otel_sink import build_store_tracer
from phoenix_obs.tracing import traced_run_case
from schemas.cases import Difficulty
from schemas.loader import DatasetEntry, load_dataset

PROFILE_STEADY = "steady"
PROFILE_SHIFTED = "shifted"
PROFILES = (PROFILE_STEADY, PROFILE_SHIFTED)

# Relative draw weight per difficulty tier, per profile.
PROFILE_WEIGHTS: dict[str, dict[Difficulty, float]] = {
    PROFILE_STEADY: {
        Difficulty.EASY: 1.0,
        Difficulty.MEDIUM: 1.0,
        Difficulty.HARD: 1.0,
    },
    PROFILE_SHIFTED: {
        Difficulty.EASY: 0.15,
        Difficulty.MEDIUM: 0.5,
        Difficulty.HARD: 4.0,
    },
}


def build_population(
    entries: list[DatasetEntry],
    profile: str,
) -> tuple[list[DatasetEntry], list[float]]:
    """Return the draw pool and its weights for a traffic profile."""
    if profile not in PROFILE_WEIGHTS:
        msg = f"Unknown traffic profile {profile!r}; expected one of {PROFILES}"
        raise ValueError(msg)
    weights_by_difficulty = PROFILE_WEIGHTS[profile]
    weights = [weights_by_difficulty[entry.label.difficulty] for entry in entries]
    return entries, weights


async def _emit_traffic(
    entries: list[DatasetEntry],
    weights: list[float],
    *,
    n_runs: int,
    planner: PlannerLlm,
    traces_path: Path,
    seed: int,
) -> int:
    tracer, exporter = build_store_tracer(traces_path)
    rng = random.Random(seed)
    emitted = 0
    try:
        for _ in range(n_runs):
            entry = rng.choices(entries, weights=weights, k=1)[0]
            host = build_mock_host(entry)
            await traced_run_case(entry.case, host, planner, tracer)
            emitted += 1
    finally:
        exporter.force_flush()
        exporter.shutdown()
    return emitted


def generate_traffic(
    *,
    config: OnlineEvalConfig,
    n_runs: int,
    profile: str = PROFILE_STEADY,
    seed: int = 0,
    cases_dir: Path = Path("data/cases"),
    planner: PlannerLlm | None = None,
) -> int:
    """Run ``n_runs`` synthetic cases through the traced agent. Returns the count."""
    entries = load_dataset(cases_dir=cases_dir, labels_path=config.labels_path)
    pool, weights = build_population(entries, profile)
    config.ensure_state_dir()
    return asyncio.run(
        _emit_traffic(
            pool,
            weights,
            n_runs=n_runs,
            planner=planner or StubPlanner(),
            traces_path=config.traces_path,
            seed=seed,
        )
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Emit simulated production traffic through the instrumented agent. "
            "Synthetic cases only; this is not a production workload."
        )
    )
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--profile", choices=PROFILES, default=PROFILE_STEADY)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help="Override the online-eval state directory.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    config = OnlineEvalConfig()
    if args.state_dir is not None:
        config = OnlineEvalConfig(state_dir=args.state_dir)
    count = generate_traffic(
        config=config,
        n_runs=args.runs,
        profile=args.profile,
        seed=args.seed,
    )
    print(
        f"Emitted {count} simulated run(s) "
        f"[profile={args.profile}, seed={args.seed}] -> {config.traces_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

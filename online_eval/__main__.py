"""CLI for the online evaluation loop.

    python -m online_eval simulate-traffic --runs 40 --profile steady
    python -m online_eval cycle
    python -m online_eval history
    python -m online_eval reset

``cycle`` runs the same five steps the Airflow DAG runs, in one process. The DAG
and this command share ``online_eval.pipeline``, so a loop that works here works
there and vice versa.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from online_eval.config import OnlineEvalConfig, load_config
from online_eval.pipeline import run_cycle, summarize_cycle
from online_eval.simulated_traffic import PROFILE_STEADY, PROFILES, generate_traffic
from online_eval.store import load_alerts, load_cycles, read_baseline, reset_state


def _config_from_args(args: argparse.Namespace) -> OnlineEvalConfig:
    config = load_config(args.config)
    if args.state_dir is not None:
        config = config.model_copy(update={"state_dir": args.state_dir})
    return config


def _cmd_simulate_traffic(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
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


def _cmd_cycle(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    record = run_cycle(config)
    print(summarize_cycle(record))
    if args.fail_on_alert and record.alerts:
        return 1
    return 0


def _cmd_history(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    cycles = load_cycles(config)
    baseline = read_baseline(config)
    if not cycles:
        print("No cycles recorded yet.")
        return 0
    print(f"{len(cycles)} cycle(s) recorded at {config.cycles_path}")
    if baseline is not None:
        macro = "n/a" if baseline.macro_f1 is None else f"{baseline.macro_f1:.4f}"
        print(
            f"baseline {baseline.window_id}: n={baseline.n_runs} "
            f"labeled={baseline.n_labeled} macro_f1={macro} "
            f"mix={baseline.action_counts}"
        )
    else:
        print("baseline: not frozen yet")
    header = (
        f"{'cycle':<28}{'n':>5}{'lab':>5}{'macroF1':>10}"
        f"{'lowconf':>9}{'guard':>8}{'p95ms':>9}{'alerts':>8}"
    )
    print(header)
    print("-" * len(header))
    for record in cycles:
        window = record.rolling_window
        if window is None:
            continue
        macro = "n/a" if window.macro_f1 is None else f"{window.macro_f1:.4f}"
        print(
            f"{record.cycle_id:<28}{window.n_runs:>5}{window.n_labeled:>5}"
            f"{macro:>10}{window.low_confidence_rate:>9.3f}"
            f"{window.guardrail_rate:>8.3f}{window.p95_latency_ms:>9.1f}"
            f"{len(record.alerts):>8}"
        )
    alerts = load_alerts(config)
    if alerts:
        print(f"\n{len(alerts)} alert(s) in {config.alerts_path}:")
        for alert in alerts:
            print(f"  [{alert.severity.upper()}] {alert.cycle_id} {alert.message}")
    return 0


def _cmd_reset(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    removed = reset_state(config)
    if not removed:
        print("No loop state to remove.")
    for path in removed:
        print(f"removed {path}")
    print(f"Trace store left in place: {config.traces_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="online_eval", description=__doc__)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--state-dir", type=Path, default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)

    traffic = subparsers.add_parser(
        "simulate-traffic",
        help="Emit simulated production traffic through the traced agent.",
    )
    traffic.add_argument("--runs", type=int, default=30)
    traffic.add_argument("--profile", choices=PROFILES, default=PROFILE_STEADY)
    traffic.add_argument("--seed", type=int, default=0)
    traffic.set_defaults(func=_cmd_simulate_traffic)

    cycle = subparsers.add_parser("cycle", help="Run one online-eval cycle.")
    cycle.add_argument(
        "--fail-on-alert",
        action="store_true",
        help="Exit non-zero when the cycle raises any alert condition.",
    )
    cycle.set_defaults(func=_cmd_cycle)

    history = subparsers.add_parser("history", help="Print the recorded trend.")
    history.set_defaults(func=_cmd_history)

    reset = subparsers.add_parser(
        "reset",
        help="Delete loop state (cursor, scored runs, cycles, alerts, baseline).",
    )
    reset.set_defaults(func=_cmd_reset)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())

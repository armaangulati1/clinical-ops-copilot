"""Persistence for the loop: cursor, scored runs, baseline, cycle history.

Without this module the loop would be a one-shot script. With it there is a
trend: every cycle appends, the rolling window is the tail of the scored-run
log, and the baseline is a frozen window on disk rather than "whatever the
previous run happened to see".

Baseline policy, which is a real design choice: the baseline is **frozen**, not
rolling. The first window that clears both the volume and the label minimums is
written to ``baseline.json`` and then stays put until someone explicitly resets
it. A rolling baseline would move with the drift it is supposed to detect, so a
slow degradation would look normal at every single step. The cost of freezing is
that a legitimate, permanent change in the traffic mix keeps alerting until the
baseline is reset on purpose, which is the trade-off worth having: it forces a
human decision instead of quietly absorbing the change.
"""

from __future__ import annotations

import json
from pathlib import Path

from online_eval.config import OnlineEvalConfig
from online_eval.models import AlertEvent, CycleRecord, ScoredRun, WindowMetrics
from online_eval.trace_store import append_jsonl, read_jsonl


def read_cursor(config: OnlineEvalConfig) -> int:
    """Highest span end time already consumed, in unix nanoseconds."""
    path = config.cursor_path
    if not path.exists():
        return 0
    payload = json.loads(path.read_text(encoding="utf-8"))
    value = payload.get("cursor_unix_ns", 0)
    return int(value) if isinstance(value, int | float | str) else 0


def write_cursor(config: OnlineEvalConfig, cursor_unix_ns: int) -> None:
    config.ensure_state_dir()
    config.cursor_path.write_text(
        json.dumps({"cursor_unix_ns": cursor_unix_ns}, indent=2),
        encoding="utf-8",
    )


def existing_trace_ids(config: OnlineEvalConfig) -> set[str]:
    """Trace ids already persisted, used to make appends idempotent.

    A full scan per cycle, which is fine at this scale and would not be at
    production trace volume; a real deployment would put a unique index on
    ``trace_id`` in a real store instead.
    """
    return {item.run.trace_id for item in load_scored_runs(config)}


def append_scored_runs(
    config: OnlineEvalConfig,
    scored: list[ScoredRun],
    *,
    deduplicate: bool = True,
) -> list[ScoredRun]:
    """Append scored runs, skipping trace ids already on disk.

    Idempotency matters because the orchestrator retries tasks. A retried
    aggregate step that appended a second copy of the same runs would bias the
    rolling window toward whatever traffic happened to fail once.
    """
    config.ensure_state_dir()
    if deduplicate:
        seen = existing_trace_ids(config)
        scored = [item for item in scored if item.run.trace_id not in seen]
    if not scored:
        return []
    with config.scored_runs_path.open("a", encoding="utf-8") as handle:
        for item in scored:
            handle.write(item.model_dump_json())
            handle.write("\n")
    return scored


def load_scored_runs(
    config: OnlineEvalConfig, *, tail: int | None = None
) -> list[ScoredRun]:
    """Load persisted scored runs, optionally only the most recent ``tail``."""
    path = config.scored_runs_path
    if not path.exists():
        return []
    rows = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if tail is not None:
        rows = rows[-tail:]
    return [ScoredRun.model_validate_json(row) for row in rows]


def read_baseline(config: OnlineEvalConfig) -> WindowMetrics | None:
    path = config.baseline_path
    if not path.exists():
        return None
    return WindowMetrics.model_validate_json(path.read_text(encoding="utf-8"))


def write_baseline(config: OnlineEvalConfig, window: WindowMetrics) -> None:
    config.ensure_state_dir()
    config.baseline_path.write_text(
        window.model_dump_json(indent=2),
        encoding="utf-8",
    )


def baseline_is_eligible(
    window: WindowMetrics,
    config: OnlineEvalConfig,
) -> bool:
    """Whether a window is allowed to become the frozen baseline.

    Three conditions, each learned rather than assumed:

    * Enough runs, and enough adjudicated runs. A baseline with no accuracy in
      it would permanently disable the two quality detectors, which is worse
      than having no baseline at all, because the board would look green.
    * **Not already breaching the hard floor.** The first real DAG run froze a
      window whose macro-F1 was 0.2963, below the 0.50 floor, which would have
      anchored "normal" at a broken level forever. A system that is already
      failing does not get to define what normal looks like.
    """
    thresholds = config.thresholds
    if window.macro_f1 is None:
        return False
    return (
        window.n_runs >= thresholds.min_window_n
        and window.n_labeled >= thresholds.min_labeled_n
        and window.macro_f1 >= thresholds.macro_f1_floor
    )


def maybe_promote_baseline(
    config: OnlineEvalConfig,
    window: WindowMetrics,
) -> WindowMetrics | None:
    """Freeze this window as the baseline if none exists and it qualifies."""
    existing = read_baseline(config)
    if existing is not None:
        return existing
    if not baseline_is_eligible(window, config):
        return None
    write_baseline(config, window)
    return window


def append_cycle(config: OnlineEvalConfig, record: CycleRecord) -> None:
    config.ensure_state_dir()
    append_jsonl(config.cycles_path, json.loads(record.model_dump_json()))


def load_cycles(config: OnlineEvalConfig) -> list[CycleRecord]:
    return [CycleRecord.model_validate(row) for row in read_jsonl(config.cycles_path)]


def append_alerts(config: OnlineEvalConfig, alerts: list[AlertEvent]) -> None:
    if not alerts:
        return
    config.ensure_state_dir()
    for alert in alerts:
        append_jsonl(config.alerts_path, json.loads(alert.model_dump_json()))


def load_alerts(config: OnlineEvalConfig) -> list[AlertEvent]:
    return [AlertEvent.model_validate(row) for row in read_jsonl(config.alerts_path)]


def reset_state(config: OnlineEvalConfig) -> list[Path]:
    """Delete loop state (not the trace store). Returns the paths removed."""
    removed: list[Path] = []
    for path in (
        config.scored_runs_path,
        config.cycles_path,
        config.alerts_path,
        config.baseline_path,
        config.cursor_path,
    ):
        if path.exists():
            path.unlink()
            removed.append(path)
    return removed

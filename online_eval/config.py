"""Configuration for the online evaluation loop.

Thresholds live in one typed object so the DAG, the CLI and the tests all read
the same numbers, and so a threshold change is a config diff rather than an edit
scattered across detectors.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

DEFAULT_STATE_DIR = Path("data/online_eval")


class DriftThresholds(BaseModel):
    """Alerting thresholds for the rolling window.

    Every value is a judgement call, not a derived constant. The two PSI bands
    (0.10 "investigate", 0.25 "act") are the conventional industry rules of
    thumb, not a statistical test with a false-positive rate. They are used here
    because they are legible, and the finding records the method so a reader is
    never told a convention is an inference.
    """

    macro_f1_abs_drop: float = Field(
        default=0.10,
        ge=0.0,
        le=1.0,
        description="Absolute macro-F1 drop vs the baseline window that alerts.",
    )
    macro_f1_floor: float = Field(
        default=0.50,
        ge=0.0,
        le=1.0,
        description=(
            "Hard floor for rolling macro-F1, matched to the CI regression "
            "gate's macro_f1_min so the online floor cannot be laxer than the "
            "offline one."
        ),
    )
    low_confidence_rate_abs_rise: float = Field(default=0.15, ge=0.0, le=1.0)
    guardrail_rate_abs_rise: float = Field(default=0.20, ge=0.0, le=1.0)
    p95_latency_ratio: float = Field(
        default=2.0,
        gt=1.0,
        description="Alert when rolling p95 latency exceeds baseline p95 x this.",
    )
    p95_latency_floor_ms: float = Field(
        default=25.0,
        ge=0.0,
        description=(
            "Below this baseline p95, the latency ratio is not evaluated at "
            "all. Added after the first real run of this loop alerted on a "
            "'2.95x latency regression' that was 0.9ms -> 2.7ms of scheduler "
            "jitter. A ratio with no absolute floor is a false-positive "
            "generator on a fast path, and an alert nobody can act on trains "
            "its owner to ignore the next one."
        ),
    )
    action_distribution_psi: float = Field(
        default=0.25,
        gt=0.0,
        description="PSI on the decision-action mix above which drift alerts.",
    )
    min_window_n: int = Field(
        default=10,
        ge=1,
        description="Below this many runs a window is reported, never alerted on.",
    )
    min_labeled_n: int = Field(
        default=8,
        ge=1,
        description=(
            "Below this many adjudicated runs, accuracy is not computed at all. "
            "Set from measurement, not taste: at 10 adjudicated runs the "
            "observed macro-F1 of this repo's offline stub planner swung "
            "between 0.30 and 0.61 across cycles on identical traffic."
        ),
    )


class OnlineEvalConfig(BaseModel):
    """Paths and knobs for one online-eval deployment."""

    state_dir: Path = Field(default=DEFAULT_STATE_DIR)
    labels_path: Path = Field(default=Path("data/labels/labels.json"))
    window_size: int = Field(
        default=60,
        ge=1,
        description=(
            "Rolling window length, in scored runs, used for detection. Sized "
            "so that at the configured label coverage the window holds roughly "
            "20 adjudicated runs, which is where the accuracy series stops "
            "swinging on sampling noise alone."
        ),
    )
    sample_limit: int = Field(
        default=60,
        ge=1,
        description="Max runs sampled from the trace store per cycle.",
    )
    sample_seed: int = Field(default=1729)
    confidence_floor: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description=(
            "Decisions below this planner confidence count toward the "
            "low-confidence rate. Label-free, so it works on the unlabeled "
            "majority of traffic."
        ),
    )
    label_coverage: float = Field(
        default=0.35,
        ge=0.0,
        le=1.0,
        description=(
            "Fraction of sampled runs treated as adjudicated. Stands in for the "
            "review queue a real deployment would have; the rest stay unlabeled, "
            "which is the realistic case."
        ),
    )
    thresholds: DriftThresholds = Field(default_factory=DriftThresholds)

    @property
    def traces_path(self) -> Path:
        """Append-only span sink written by the traffic generator."""
        return self.state_dir / "traces.jsonl"

    @property
    def scored_runs_path(self) -> Path:
        """Every scored run, in order. The rolling window is its tail."""
        return self.state_dir / "scored_runs.jsonl"

    @property
    def cycles_path(self) -> Path:
        """One record per loop execution. This is the trend over time."""
        return self.state_dir / "cycles.jsonl"

    @property
    def alerts_path(self) -> Path:
        return self.state_dir / "alerts.jsonl"

    @property
    def baseline_path(self) -> Path:
        """Frozen reference window that drift is measured against."""
        return self.state_dir / "baseline.json"

    @property
    def cursor_path(self) -> Path:
        """High-water mark so a cycle scores only traffic it has not seen."""
        return self.state_dir / "cursor.json"

    def ensure_state_dir(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)


def load_config(path: Path | None = None) -> OnlineEvalConfig:
    """Load config from JSON, or return defaults when no file is given."""
    if path is None:
        return OnlineEvalConfig()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return OnlineEvalConfig.model_validate(payload)

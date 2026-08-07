"""Offline metric functions for the evaluation harness.

Import weight note, added when the online-eval loop was built: every metric
module here needs only pydantic and ``schemas/`` **except** ``trajectory``,
which reaches into ``agent/`` and therefore drags in the MCP client, the
Anthropic SDK and the FHIR stack. Re-exporting it eagerly made
``from evals.metrics.classification import ...`` transitively require the
agent's entire runtime, because importing a submodule runs this file.

That mattered the moment something outside the harness wanted a metric: the
online-eval loop runs in an orchestrator worker that has pydantic and nothing
else, and it could not import macro-F1 without installing a model client. So
``trajectory`` is resolved lazily through PEP 562 ``__getattr__``. The public
API is unchanged, ``from evals.metrics import score_trajectory`` still works,
and the heavy import happens on first use rather than on package import.

``TYPE_CHECKING`` keeps the eager import visible to mypy, so the lazy names are
still fully typed for callers.
"""

from typing import TYPE_CHECKING, Any

from evals.metrics.classification import (
    ClassificationMetrics,
    ConfusionMatrix,
    compute_classification_metrics,
)
from evals.metrics.errors import ErrorTaxonomyEntry, classify_decision_error
from evals.metrics.judge_agreement import JudgeAgreementMetrics, compute_judge_agreement
from evals.metrics.latency import (
    CostSummary,
    LatencySummary,
    compute_cost_summary,
    percentile,
)

if TYPE_CHECKING:
    from evals.metrics.trajectory import TrajectoryScore, score_trajectory

_LAZY_EXPORTS = frozenset({"TrajectoryScore", "score_trajectory"})


def __getattr__(name: str) -> Any:
    """Resolve the agent-dependent trajectory exports on first access."""
    if name in _LAZY_EXPORTS:
        from evals.metrics import trajectory

        return getattr(trajectory, name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


__all__ = [
    "ClassificationMetrics",
    "ConfusionMatrix",
    "CostSummary",
    "ErrorTaxonomyEntry",
    "JudgeAgreementMetrics",
    "LatencySummary",
    "TrajectoryScore",
    "classify_decision_error",
    "compute_classification_metrics",
    "compute_cost_summary",
    "compute_judge_agreement",
    "percentile",
    "score_trajectory",
]

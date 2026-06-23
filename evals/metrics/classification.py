"""Decision classification metrics (precision, recall, F1, macro-F1)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from schemas.decisions import DecisionAction

DECISION_CLASS_ORDER: tuple[DecisionAction, ...] = (
    DecisionAction.SUBMIT,
    DecisionAction.REQUEST_MORE_INFO,
    DecisionAction.DENY_RISK,
)


class ConfusionMatrix(BaseModel):
    """Rows = ground truth, columns = predicted."""

    labels: list[str] = Field(
        default_factory=lambda: [action.value for action in DECISION_CLASS_ORDER]
    )
    counts: dict[str, dict[str, int]] = Field(default_factory=dict)

    def cell(self, truth: str, predicted: str) -> int:
        return self.counts.get(truth, {}).get(predicted, 0)


class PerClassMetrics(BaseModel):
    precision: float
    recall: float
    f1: float
    support: int


class ClassificationMetrics(BaseModel):
    confusion_matrix: ConfusionMatrix
    per_class: dict[str, PerClassMetrics]
    macro_f1: float
    accuracy: float
    n_cases: int


def _zero_matrix() -> dict[str, dict[str, int]]:
    labels = [action.value for action in DECISION_CLASS_ORDER]
    return {truth: dict.fromkeys(labels, 0) for truth in labels}


def build_confusion_matrix(
    y_true: list[str],
    y_pred: list[str],
) -> ConfusionMatrix:
    """Build a confusion matrix from parallel label lists."""
    if len(y_true) != len(y_pred):
        msg = "y_true and y_pred must have the same length"
        raise ValueError(msg)
    counts = _zero_matrix()
    for truth, predicted in zip(y_true, y_pred, strict=True):
        if truth not in counts:
            msg = f"Unknown ground-truth label: {truth!r}"
            raise ValueError(msg)
        if predicted not in counts[truth]:
            msg = f"Unknown predicted label: {predicted!r}"
            raise ValueError(msg)
        counts[truth][predicted] += 1
    return ConfusionMatrix(counts=counts)


def _safe_div(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def compute_classification_metrics(
    y_true: list[str],
    y_pred: list[str],
) -> ClassificationMetrics:
    """Compute per-class and macro-averaged F1 from parallel predictions."""
    matrix = build_confusion_matrix(y_true, y_pred)
    labels = matrix.labels
    per_class: dict[str, PerClassMetrics] = {}
    f1_scores: list[float] = []

    for label in labels:
        tp = matrix.cell(label, label)
        fp = sum(matrix.cell(other, label) for other in labels if other != label)
        fn = sum(matrix.cell(label, other) for other in labels if other != label)
        support = sum(matrix.cell(label, predicted) for predicted in labels)
        precision = _safe_div(tp, tp + fp)
        recall = _safe_div(tp, tp + fn)
        f1 = _safe_div(2 * precision * recall, precision + recall)
        per_class[label] = PerClassMetrics(
            precision=round(precision, 4),
            recall=round(recall, 4),
            f1=round(f1, 4),
            support=support,
        )
        f1_scores.append(f1)

    correct = sum(matrix.cell(label, label) for label in labels)
    n_cases = len(y_true)
    macro_f1 = _safe_div(sum(f1_scores), len(f1_scores))
    accuracy = _safe_div(correct, n_cases)

    return ClassificationMetrics(
        confusion_matrix=matrix,
        per_class=per_class,
        macro_f1=round(macro_f1, 4),
        accuracy=round(accuracy, 4),
        n_cases=n_cases,
    )

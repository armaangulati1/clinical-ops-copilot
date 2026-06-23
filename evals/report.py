"""Format and persist evaluation results."""

from __future__ import annotations

from pathlib import Path

from evals.models import EvalResults

RESULTS_JSON_PATH = Path("evals/results/latest.json")
RESULTS_SUMMARY_PATH = Path("evals/results/latest_summary.md")


def format_results_table(results: EvalResults) -> str:
    """Render a single human-readable results table."""
    cls = results.classification
    lines = [
        "Prior-auth agent evaluation results",
        "===================================",
        f"Cases evaluated: {results.n_cases}",
        f"Planner model: {results.planner_model or 'unknown'}",
        "",
        "Decision accuracy",
        "-----------------",
        f"Accuracy:     {cls.accuracy:.4f}",
        f"Macro-F1:     {cls.macro_f1:.4f}",
        "",
        "Per-class precision / recall / F1",
    ]
    for label, metrics in cls.per_class.items():
        lines.append(
            f"  {label:20s}  P={metrics.precision:.3f}  "
            f"R={metrics.recall:.3f}  F1={metrics.f1:.3f}  "
            f"(n={metrics.support})"
        )

    lines.extend(
        [
            "",
            "Confusion matrix (rows=truth, cols=predicted)",
        ]
    )
    header = "truth \\ pred".ljust(18) + "".join(
        label[:12].rjust(14) for label in cls.confusion_matrix.labels
    )
    lines.append(header)
    for truth in cls.confusion_matrix.labels:
        row = truth.ljust(18)
        for predicted in cls.confusion_matrix.labels:
            row += str(cls.confusion_matrix.cell(truth, predicted)).rjust(14)
        lines.append(row)

    lines.extend(
        [
            "",
            "Trajectory",
            "----------",
            f"Trajectory correctness: {results.trajectory_correct_pct:.1f}%",
            f"Hard violations: {len(results.trajectory_violations)}",
            f"Warnings (non-failing): {len(results.trajectory_warnings)}",
            "",
            "Latency & cost",
            "--------------",
            f"p50 latency:  {results.latency.p50_ms:.1f} ms",
            f"p95 latency:  {results.latency.p95_ms:.1f} ms",
            f"Avg $/case:   ${results.cost.mean_usd_per_case:.4f}",
            "",
        ]
    )

    if results.judge_agreement is not None:
        agreement = results.judge_agreement
        lines.extend(
            [
                "Email judge validation",
                "----------------------",
                f"Validation cases: {results.judge_validation_n}",
                f"Exact agreement: {agreement.exact_agreement_rate:.3f}",
                f"MAE:             {agreement.mean_absolute_error:.3f}",
                (
                    f"Pearson r:       {agreement.pearson_r:.3f}"
                    if agreement.pearson_r is not None
                    else "Pearson r:       n/a"
                ),
                "",
            ]
        )
    else:
        lines.extend(
            [
                "Email judge validation",
                "----------------------",
                "Not run (no drafted emails or judge unavailable).",
                "",
            ]
        )

    if results.error_taxonomy:
        lines.append("Error taxonomy (mis-predictions)")
        lines.append("--------------------------------")
        counts: dict[str, int] = {}
        for entry in results.error_taxonomy:
            counts[entry.category.value] = counts.get(entry.category.value, 0) + 1
        for category, count in sorted(counts.items()):
            lines.append(f"  {category}: {count}")
        lines.append("")

    if results.notes:
        lines.append("Notes")
        lines.append("-----")
        lines.extend(f"- {note}" for note in results.notes)
        lines.append("")

    lines.append("Integrity")
    lines.append("---------")
    lines.append(
        "Labels are read only inside evals/; agent runtime does not access labels."
    )
    lines.append(results.integrity.caveat)

    return "\n".join(lines)


def write_results(
    results: EvalResults,
    *,
    json_path: Path = RESULTS_JSON_PATH,
    summary_path: Path = RESULTS_SUMMARY_PATH,
) -> tuple[Path, Path]:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        results.model_dump_json(indent=2),
        encoding="utf-8",
    )
    summary_path.write_text(format_results_table(results), encoding="utf-8")
    return json_path, summary_path

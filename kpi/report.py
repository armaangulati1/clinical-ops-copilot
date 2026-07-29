"""Render and persist the KPI report.

The rendering is a pure function of the report model with no timestamps or
environment values, so CI can regenerate it and fail on any drift.
"""

from __future__ import annotations

from pathlib import Path

from kpi.models import KpiReport

TITLE = "Agent KPI report"

HEADER_NOTE = (
    "Operational KPIs for the prior-auth agent, named as a deployment "
    "engineer would track them: throughput, quality, cost, human "
    "intervention rate, and cycle time. Every number below is computed from "
    "a recorded evaluation run in this repository. Nothing here is "
    "estimated, and a KPI that cannot be derived honestly is listed as not "
    "computed rather than filled in."
)


def _fmt(value: float) -> str:
    return f"{value:,.4f}".rstrip("0").rstrip(".")


def _summary_table(report: KpiReport) -> list[str]:
    rows: list[tuple[str, str, str]] = []
    if report.throughput is not None:
        rows.append(
            (
                "Throughput",
                f"{_fmt(report.throughput.decisions_per_minute)} decisions/min "
                f"(serial, concurrency {report.throughput.concurrency})",
                str(report.throughput.n_decisions),
            )
        )
    if report.quality is not None:
        rows.append(
            (
                "Quality",
                f"macro-F1 {report.quality.macro_f1:.4f} "
                f"(accuracy {report.quality.accuracy:.4f})",
                str(report.quality.n_decisions),
            )
        )
    if report.cost is not None:
        rows.append(
            (
                "Cost",
                f"${report.cost.mean_usd_per_decision:.6f} per decision "
                f"({_fmt(report.cost.mean_tokens_per_decision)} tokens)",
                str(report.cost.n_decisions_with_usage),
            )
        )
    if report.human_intervention is not None:
        intervention = report.human_intervention
        rows.append(
            (
                "Human intervention rate",
                f"{intervention.rate * 100:.2f}% "
                f"({intervention.n_intervened}/{intervention.n_decisions})",
                str(intervention.n_decisions),
            )
        )
    if report.cycle_time is not None:
        rows.append(
            (
                "Cycle time",
                f"p50 {_fmt(report.cycle_time.p50_s)}s, "
                f"p95 {_fmt(report.cycle_time.p95_s)}s",
                str(report.cycle_time.n_decisions),
            )
        )
    lines = ["| KPI | Measured value | N |", "| --- | --- | --- |"]
    lines.extend(f"| {name} | {value} | {n} |" for name, value, n in rows)
    return lines


def _scope_section(report: KpiReport) -> list[str]:
    scope = report.scope
    lines = [
        "## Scope of these numbers",
        "",
        f"- Source run: `{scope.source_results_path}`",
        f"- Split: {scope.split_name}, {scope.n_decisions} decisions",
        f"- Planner model: {scope.planner_model or 'not recorded'}",
        f"- Data: {scope.data_kind}",
        f"- Execution: {scope.execution}",
        f"- Maturity: {scope.maturity}",
        "",
        "Read the numbers against these limits:",
        "",
    ]
    lines.extend(f"- {caveat}" for caveat in scope.caveats)
    lines.append("")
    return lines


def _detail_sections(report: KpiReport) -> list[str]:
    lines: list[str] = []
    if report.throughput is not None:
        throughput = report.throughput
        lines.extend(
            [
                "### Throughput",
                "",
                f"- {_fmt(throughput.decisions_per_minute)} decisions per minute",
                f"- {_fmt(throughput.decisions_per_hour)} decisions per hour",
                f"- {throughput.n_decisions} decisions, "
                f"{_fmt(throughput.total_wall_clock_s)} seconds of summed "
                "per-decision wall clock",
                f"- Concurrency: {throughput.concurrency}",
                f"- Method: {throughput.method}",
                "",
            ]
        )
    if report.quality is not None:
        quality = report.quality
        lines.extend(
            [
                "### Quality",
                "",
                f"- Macro-F1: {quality.macro_f1:.4f}",
                f"- Accuracy: {quality.accuracy:.4f}",
                f"- N: {quality.n_decisions}",
            ]
        )
        lines.extend(
            f"- F1, {label}: {value:.4f}"
            for label, value in quality.per_class_f1.items()
        )
        lines.extend(
            [
                f"- Source: {quality.source}",
                f"- Method: {quality.method}",
                "",
            ]
        )
    if report.cost is not None:
        cost = report.cost
        lines.extend(
            [
                "### Cost",
                "",
                f"- Mean cost per decision: ${cost.mean_usd_per_decision:.6f}",
                f"- Mean tokens per decision: {_fmt(cost.mean_tokens_per_decision)}",
                f"- Input tokens: {cost.total_input_tokens:,}",
                f"- Output tokens: {cost.total_output_tokens:,}",
                f"- Total for the run: ${cost.total_usd:.6f} across "
                f"{cost.n_decisions_with_usage} decisions",
                "- Arithmetic projection at the measured mean: "
                f"${cost.projected_usd_per_1000_decisions:.4f} per 1,000 "
                "decisions. That is multiplication, not an observation at "
                "that volume.",
                f"- Pricing basis: {cost.pricing_basis}",
                f"- Method: {cost.method}",
                "",
            ]
        )
    if report.human_intervention is not None:
        intervention = report.human_intervention
        lines.extend(
            [
                "### Human intervention rate",
                "",
                f"- Rate: {intervention.rate * 100:.2f}% "
                f"({intervention.n_intervened} of {intervention.n_decisions})",
                f"- Would stop at the human approval gate: "
                f"{intervention.n_approval_gate}",
                f"- Rewritten by the deterministic guardrail: "
                f"{intervention.n_guardrail}",
                f"- Both on the same decision: {intervention.n_both}",
                f"- Definition: {intervention.definition}",
                f"- Method: {intervention.method}",
                "",
            ]
        )
    if report.cycle_time is not None:
        cycle_time = report.cycle_time
        lines.extend(
            [
                "### Cycle time",
                "",
                f"- p50: {_fmt(cycle_time.p50_s)} s",
                f"- p95: {_fmt(cycle_time.p95_s)} s",
                f"- Mean: {_fmt(cycle_time.mean_s)} s",
                f"- Range: {_fmt(cycle_time.min_s)} s to {_fmt(cycle_time.max_s)} s",
                f"- N: {cycle_time.n_decisions}",
                f"- Method: {cycle_time.method}",
                "",
            ]
        )
    return lines


def render_markdown(report: KpiReport) -> str:
    """Render the KPI report as deterministic markdown."""
    lines = [
        f"# {TITLE}: {report.scope.split_name}",
        "",
        HEADER_NOTE,
        "",
        "## Headline",
        "",
    ]
    lines.extend(_summary_table(report))
    lines.append("")
    lines.extend(_scope_section(report))
    lines.append("## KPI detail")
    lines.append("")
    lines.extend(_detail_sections(report))

    lines.append("## What this harness does not measure")
    lines.append("")
    if not report.not_computed and not report.not_measured:
        lines.append("- Nothing withheld for this run.")
        lines.append("")
    for item in report.not_computed:
        lines.append(f"- **{item.name}**: not computed. {item.reason}")
    for item in report.not_measured:
        lines.append(f"- **{item.name}**: not measurable here. {item.reason}")
    lines.append("")
    lines.append(
        "This artifact is generated by `uv run kpi report`. CI regenerates "
        "it and fails if the committed copy has drifted."
    )
    lines.append("")
    return "\n".join(lines)


def write_report(
    report: KpiReport,
    *,
    json_path: Path,
    markdown_path: Path,
) -> tuple[Path, Path]:
    """Persist the KPI report as JSON and markdown."""
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def render_json(report: KpiReport) -> str:
    """Render the KPI report as deterministic JSON."""
    return report.model_dump_json(indent=2)

"""Turn drift findings into alert events.

Scope, stated plainly: this raises an alert *condition* and writes it to an
append-only log that the CLI and the DAG both read. It does not page anyone.
There is no PagerDuty, Slack or email integration in this repository, and the
DAG's alert task failing is the only escalation path. Wiring a real sink is a
one-function change, but it has not been done, so nothing here should be read as
"alerting is hooked up".

Severity is assigned by what the metric means, not by how far it moved:

* ``critical`` -- decision quality itself. A macro-F1 floor breach or a
  macro-F1 regression means the agent is getting cases wrong.
* ``warning`` -- leading indicators. Confidence, guardrail rate, latency and
  population shift can all move without quality moving, and treating them as
  critical is how a monitor teaches its owner to ignore it.
"""

from __future__ import annotations

from datetime import datetime

from online_eval.models import AlertEvent, DriftFinding, WindowMetrics

CRITICAL_METRICS = frozenset({"macro_f1_floor", "macro_f1_regression"})


def severity_for(metric: str) -> str:
    return "critical" if metric in CRITICAL_METRICS else "warning"


def evaluate_alerts(
    findings: list[DriftFinding],
    window: WindowMetrics,
    *,
    cycle_id: str,
    raised_at: datetime,
) -> list[AlertEvent]:
    """Build one alert per breached finding.

    Findings that could not be compared never alert. That is the whole point of
    keeping ``comparable`` separate from ``breached``: an unchecked detector is
    silent here and visible in the cycle record, rather than silently green.
    """
    alerts: list[AlertEvent] = []
    for finding in findings:
        if not (finding.comparable and finding.breached):
            continue
        alerts.append(
            AlertEvent(
                cycle_id=cycle_id,
                raised_at=raised_at,
                severity=severity_for(finding.metric),
                metric=finding.metric,
                message=(
                    f"{finding.metric}: {finding.note} "
                    f"(window {window.window_id}, n={window.n_runs}, "
                    f"labeled={window.n_labeled})"
                ),
            )
        )
    return alerts


def format_alert_summary(alerts: list[AlertEvent]) -> str:
    if not alerts:
        return "No alert conditions raised."
    lines = [f"{len(alerts)} alert condition(s) raised:"]
    for alert in alerts:
        lines.append(f"  [{alert.severity.upper()}] {alert.message}")
    return "\n".join(lines)

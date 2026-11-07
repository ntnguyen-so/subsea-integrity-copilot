"""Numerical warnings are available independently of agent investigation."""

from typing import Literal

from .contracts import Contract, WindowSnapshot


class MonitoringWarning(Contract):
    kind: Literal[
        "waiting",
        "possible_leak",
        "coverage_lost",
        "sensor_telemetry",
        "unresolved",
        "no_qualifying_event",
        "sensor_alerts",
        "no_sensor_alerts",
    ]
    severity: Literal["attention", "warning", "info"]
    snapshot_id: str | None
    title: str
    message: str


def monitoring_warning(
    snapshot: WindowSnapshot | None, *, sensor_alerts_only: bool = False
) -> MonitoringWarning:
    severity: Literal["attention", "warning", "info"]
    kind: Literal[
        "waiting",
        "possible_leak",
        "coverage_lost",
        "sensor_telemetry",
        "unresolved",
        "no_qualifying_event",
        "sensor_alerts",
        "no_sensor_alerts",
    ]
    if snapshot is None or snapshot.quality.status == "WARMING_UP":
        kind, severity = "waiting", "info"
        title = "WARM-UP: no qualified assessment yet"
        message = "Wait for adequate observations; this is not a healthy-pipeline verdict."
    elif snapshot.quality.status == "COVERAGE_LOST":
        kind, severity = "coverage_lost", "warning"
        title = "COVERAGE WARNING: a leak cannot be ruled out"
        message = (
            "Restore observation coverage and follow the operator's review procedure. "
            "Location withheld."
        )
    elif sensor_alerts_only:
        count = len(
            {
                finding.sensor_id
                for finding in snapshot.quality.findings
                if finding.anomaly_count
                or finding.missing
                or finding.hard_excluded
                or finding.spike_count
                or finding.drift_suspected
                or finding.peer_disagreement
            }
        )
        kind, severity = ("sensor_alerts", "warning") if count else ("no_sensor_alerts", "info")
        if count and snapshot.event.hypothesis == "suspected_leak":
            severity = "attention"
        title = f"{count} SENSOR ALERTS: engineer review required" if count else "No sensor alerts"
        message = (
            "Review sensor histories, joint timing and independent observations promptly. "
            "Detector output does not classify leaks versus malfunction "
            "or select an inspection area; "
            "follow existing response procedures. No safety clearance is implied."
        )
    elif snapshot.event.hypothesis == "suspected_leak":
        kind, severity = "possible_leak", "attention"
        title = "POSSIBLE LEAK: prompt integrity review required"
        message = (
            "Related pressure drops warrant review under existing response procedures. "
            "Do not wait for the AI report; this is not a confirmed leak."
        )
    elif snapshot.event.hypothesis == "sensor_or_telemetry_issue":
        kind, severity = "sensor_telemetry", "warning"
        title = "SENSOR / TELEMETRY WARNING: investigate unreliable measurements"
        message = (
            "Review affected instruments and competing physical causes. "
            "A sensor concern does not clear the pipeline of leaks."
        )
    elif snapshot.event.hypothesis == "insufficient_evidence":
        kind, severity = "unresolved", "warning"
        title = "UNRESOLVED WARNING: the cause is not established"
        message = (
            "Review pressure behavior, operating context and independent observations. "
            "Do not infer safety from missing evidence."
        )
    else:
        kind, severity = "no_qualifying_event", "info"
        title = "No qualifying event in the latest window"
        message = (
            "Continue monitoring. This is not a safety clearance or proof that no leak exists."
        )
    return MonitoringWarning(
        kind=kind,
        severity=severity,
        snapshot_id=snapshot.id if snapshot else None,
        title=title,
        message=message,
    )

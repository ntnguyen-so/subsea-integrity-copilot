"""Verify immediate numerical warnings never turn missing evidence into safety clearance."""

import pytest

from subsea_copilot.diagnostics import analyze_window
from subsea_copilot.evaluation import evaluate_warning_timeliness
from subsea_copilot.ingest import normalize_records
from subsea_copilot.synthetic import generate_scenario
from subsea_copilot.warning import monitoring_warning


@pytest.mark.parametrize(
    ("scenario", "kind", "message"),
    [
        ("S1", "possible_leak", "Do not wait"),
        ("S2", "sensor_telemetry", "does not clear"),
        ("S3", "coverage_lost", "Location withheld"),
        ("S4", "unresolved", "Do not infer safety"),
        ("S5", "coverage_lost", "Location withheld"),
        ("S6", "no_qualifying_event", "not a safety clearance"),
    ],
)
def test_numerical_warning_distinguishes_physical_risk_and_unobservable_conditions(
    scenario, kind, message
):
    data = generate_scenario(scenario, duration_seconds=180)
    snapshot = analyze_window(
        data.pack,
        normalize_records(data.baseline, data.pack),
        normalize_records(data.records, data.pack),
        "warning-test",
        180,
        185,
        data.epoch,
    )
    warning = monitoring_warning(snapshot)
    assert warning.kind == kind
    assert message in warning.message
    assert warning.snapshot_id == snapshot.id
    alert_only = monitoring_warning(snapshot, sensor_alerts_only=True)
    assert alert_only.kind == ("coverage_lost" if scenario in {"S3", "S5"} else "sensor_alerts")
    assert alert_only.kind not in {"possible_leak", "sensor_telemetry", "unresolved"}
    assisted = monitoring_warning(snapshot, workflow="agent_assisted")
    assert assisted.kind == alert_only.kind
    assert assisted.severity == alert_only.severity
    assert assisted.snapshot_id == alert_only.snapshot_id
    if assisted.kind == "sensor_alerts":
        assert "sensors flagged by monitoring" in assisted.title
        assert "agent investigation below" in assisted.message
        assert "do not wait for AI" in assisted.message
        assert "does not classify" not in assisted.message
        assert "engineer review required" not in assisted.title
    else:
        assert assisted == alert_only


def test_missing_assessment_is_not_a_healthy_pipeline_warning():
    warning = monitoring_warning(None)
    assert warning.kind == "waiting"
    assert "not a healthy" in warning.message
    assert monitoring_warning(None, sensor_alerts_only=True) == warning
    assert monitoring_warning(None, workflow="agent_assisted") == warning


@pytest.mark.parametrize("count", [0, 1])
def test_agent_banner_counts_unique_sensors_and_handles_no_alerts(count):
    data = generate_scenario("S1", duration_seconds=180)
    snapshot = analyze_window(
        data.pack,
        normalize_records(data.baseline, data.pack),
        normalize_records(data.records, data.pack),
        "warning-count-test", 180, 185, data.epoch,
    )
    finding = snapshot.quality.findings[0].model_copy(update={"anomaly_count": 1})
    snapshot = snapshot.model_copy(update={
        "quality": snapshot.quality.model_copy(update={
            "findings": [finding, finding] if count else [],
        }),
    })
    warning = monitoring_warning(snapshot, workflow="agent_assisted")
    if count:
        assert warning.title == "1 sensor flagged by monitoring"
        assert warning.kind == "sensor_alerts"
        assert warning.severity == "warning"
    else:
        assert warning.title == "No sensors flagged in the latest monitoring window"
        assert warning.kind == "no_sensor_alerts"
        assert warning.severity == "info"
        assert "Continue monitoring" in warning.message
        assert "investigation below" not in warning.message


def test_sliding_warning_measurement_keeps_unobservable_leaks_in_the_denominator():
    report = evaluate_warning_timeliness(1)
    assert report["passed"] is True
    assert report["all_truth_leak_cases"] == 2
    assert report["truth_leak_cases_with_possible_leak_warning"] == 1
    assert report["all_truth_leak_case_recall"] == 0.5
    assert report["source_warning_delay_p95_seconds"] <= 120

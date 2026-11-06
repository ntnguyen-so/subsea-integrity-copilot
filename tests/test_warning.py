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


def test_missing_assessment_is_not_a_healthy_pipeline_warning():
    warning = monitoring_warning(None)
    assert warning.kind == "waiting"
    assert "not a healthy" in warning.message
    assert monitoring_warning(None, sensor_alerts_only=True) == warning


def test_sliding_warning_measurement_keeps_unobservable_leaks_in_the_denominator():
    report = evaluate_warning_timeliness(1)
    assert report["passed"] is True
    assert report["all_truth_leak_cases"] == 2
    assert report["truth_leak_cases_with_possible_leak_warning"] == 1
    assert report["all_truth_leak_case_recall"] == 0.5
    assert report["source_warning_delay_p95_seconds"] <= 120

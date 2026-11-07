import json
from datetime import timedelta
from statistics import median

import pytest

from subsea_copilot.contracts import AgentTask
from subsea_copilot.diagnostics import analyze_window
from subsea_copilot.history_data import EXTENDED_HISTORY_PATH, load_history_corpus
from subsea_copilot.ingest import normalize_records
from subsea_copilot.runtime.gateway import ToolGateway, pressure_regions
from subsea_copilot.runtime.workflow import AgentService
from subsea_copilot.synthetic import EXTENDED_PACK_VERSION, generate_pack, generate_scenario


@pytest.fixture(scope="module", params=[2026, 91000, 91001])
def extended(request):
    dataset = generate_scenario("S7", seed=request.param, duration_seconds=180)
    baseline = normalize_records(dataset.baseline, dataset.pack)
    rows = normalize_records(dataset.records, dataset.pack)
    snapshot = analyze_window(
        dataset.pack, baseline, rows, f"extended-{request.param}", 140, 145, dataset.epoch
    )
    return dataset, baseline, rows, snapshot


def test_extended_network_retains_graded_pressure_evidence_and_location_limits(extended):
    dataset, _, _, snapshot = extended
    assert len(dataset.pack.segments) == 7
    assert sum(segment.length_m for segment in dataset.pack.segments) == 11200
    assert len(dataset.pack.sensors) == 112
    assert dataset.pack.version == EXTENDED_PACK_VERSION
    assert {
        "P5-ST4-A",
        "P5-ST4-B",
        "P5-ST5-A",
        "P5-ST5-B",
    } <= set(snapshot.event.supporting_sensor_ids)
    if snapshot.event.hypothesis == "suspected_leak":
        assert snapshot.event.segment_ids == ["P5"]
        if snapshot.location.status == "located":
            assert snapshot.location.method == "pressure-peak-focus-v1"
            assert snapshot.location.inspection_start_m <= 800 <= snapshot.location.inspection_end_m
            assert (
                snapshot.location.inspection_end_m - snapshot.location.inspection_start_m
                <= dataset.pack.max_location_width_m
            )
        else:
            assert snapshot.location.best is None
    else:
        assert snapshot.event.hypothesis == "insufficient_evidence"
        assert "MULTIPLE_PRESSURE_REGIONS" in snapshot.event.counterevidence
        assert not snapshot.event.eligible_location
    findings = {finding.sensor_id: finding for finding in snapshot.quality.findings}
    assert findings["P1-ST6-A"].drift_suspected
    assert findings["P3-ST7-A"].peer_disagreement
    assert findings["P6-ST3-A"].spike_count
    assert findings["P4-ST8-A"].missing >= 10
    assert findings["P3-ST5-B"].missing >= 10
    assert (
        sum(bool(f.anomaly_count or f.missing or f.hard_excluded) for f in findings.values()) >= 20
    )
    if snapshot.event.hypothesis == "suspected_leak":
        assert not any(sensor.startswith("P7-") for sensor in snapshot.event.supporting_sensor_ids)


def test_shared_gateway_and_other_distractors_cannot_replace_leak_evidence(extended):
    dataset, baseline, rows, _ = extended
    # Removing a single bounded cluster leaves other physically affected P5 stations.
    physical_observers = {sensor.id for sensor in dataset.pack.sensors if sensor.segment_id == "P5"}
    without_leak_observers = [row for row in rows if row.sensor_id not in physical_observers]
    result = analyze_window(
        dataset.pack, baseline, without_leak_observers, "without-leak", 140, 145, dataset.epoch
    )
    assert result.event.hypothesis != "suspected_leak"
    assert not result.event.eligible_location


def test_extended_agent_reads_are_bounded_and_cover_supported_observers(extended):
    _, _, _, snapshot = extended
    task = AgentTask(
        id="extended-quality",
        root_id="extended-quality",
        generation_id=snapshot.generation_id,
        snapshot_id=snapshot.id,
        site_id=snapshot.site_id,
        role="sensor_quality",
        purpose="assess_sensor_health",
        question="Which supporting instruments require review?",
        mode="scripted",
        deadline=snapshot.created_at,
    )
    gateway = ToolGateway(None, task, snapshot, None)
    for name in (
        "quality.coverage",
        "quality.conflicts",
        "quality.sensor_patterns",
        "ontology.neighbors",
    ):
        result = gateway._read(name, {})
        assert len(json.dumps(result).encode()) <= 48 * 1024
    patterns = gateway._read("quality.sensor_patterns", {})
    assert patterns["pagination"]["total"] == 112
    assert patterns["limitations"] == ["partial_health_review"]
    reviewed = {f["sensor_id"] for f in patterns["findings"]}
    while patterns["pagination"]["next_offset"] is not None:
        patterns = gateway._read(
            "quality.sensor_patterns", {"offset": patterns["pagination"]["next_offset"]}
        )
        assert len(json.dumps(patterns).encode()) <= 48 * 1024
        reviewed.update(f["sensor_id"] for f in patterns["findings"])
    assert reviewed == {sensor.id for sensor in extended[0].pack.sensors}
    sensors = AgentService._history_sensors(snapshot)
    assert len(sensors) <= 72
    assert set(snapshot.event.supporting_sensor_ids) <= {s["id"] for s in sensors}
    if len(snapshot.event.supporting_sensor_ids) < 72:
        assert any(not sensor["event_support"] for sensor in sensors)
        assert {sensor["segment_id"] for sensor in sensors} == {
            "P1",
            "P2",
            "P3",
            "P4",
            "P5",
            "P6",
            "P7",
        }
    assert any(sensor["segment_id"] == "P7" and sensor["anomalous_samples"] for sensor in sensors)
    regions = {region["segment_id"]: region for region in pressure_regions(snapshot)}
    assert len(regions["P5"]["drop"]["sensor_ids"]) > 4
    assert len(regions["P5"]["drop"]["failure_domain_ids"]) == 2
    assert len(regions["P7"]["drop"]["sensor_ids"]) == 8
    assert regions["P7"]["drop"]["failure_domain_ids"] == ["gateway-P7-0"]
    assert len(regions["P2"]["rise"]["sensor_ids"]) >= 12
    assert 90 <= regions["P5"]["drop"]["earliest_run_start_seconds"] < 110
    assert regions["P5"]["drop"]["latest_run_end_seconds"] <= snapshot.end_seconds


def test_extended_history_and_original_brief_geometry_remain_distinct():
    original = generate_pack()
    assert len(original.segments) == 3 and len(original.sensors) == 24
    assert sum(segment.length_m for segment in original.segments) == 2400
    extended = generate_pack(version=EXTENDED_PACK_VERSION)
    assert set(sensor.id for sensor in extended.sensors) >= {"P5-ST8-B", "P7-ST8-A"}
    history = load_history_corpus(EXTENDED_HISTORY_PATH)
    assert len(history) == 6
    assert {record.status for record in history} == {"approved", "draft", "superseded"}
    revised = next(record for record in history if record.id == "MAINT-P7-GW-002")
    assert revised.supersedes == "MAINT-P7-GW-001"
    assert revised.scenarios == ["S7"]


def test_discovery_magnitudes_use_the_same_recent_period_for_near_far_and_quiet_instruments():
    dataset = generate_scenario("S7", seed=2026, duration_seconds=180)
    baseline = normalize_records(dataset.baseline, dataset.pack)
    rows = normalize_records(dataset.records, dataset.pack)
    snapshot = analyze_window(dataset.pack, baseline, rows, "uniform", 110, 115, dataset.epoch)
    table = AgentService._network_pressure_table(snapshot)
    assert table["recent_period_seconds"] == [105, 110]
    decoded = {row[0]: dict(zip(table["columns"], row, strict=True)) for row in table["rows"]}
    for instrument in dataset.pack.sensors:
        recent = [
            row.value
            for row in rows
            if row.sensor_id == instrument.id
            and row.validity == "usable"
            and row.value is not None
            and dataset.epoch + timedelta(seconds=105)
            <= row.observed_at
            < dataset.epoch + timedelta(seconds=110)
            and row.received_at <= dataset.epoch + timedelta(seconds=115)
        ]
        reference = [
            row.value
            for row in baseline
            if row.sensor_id == instrument.id and row.validity == "usable" and row.value is not None
        ]
        item = decoded[instrument.id]
        assert item["recent_5s_usable_samples"] == len(recent)
        assert item["recent_5s_pressure_drop_bar"] == (
            pytest.approx(median(reference) - median(recent), abs=0.00005)
            if reference and recent
            else None
        )
    assert decoded["P5-ST4-A"]["recent_5s_pressure_drop_bar"] > 0.9
    assert (
        decoded["P5-ST4-A"]["recent_5s_pressure_drop_bar"]
        > 3 * decoded["P5-ST1-A"]["recent_5s_pressure_drop_bar"]
        > 0
    )

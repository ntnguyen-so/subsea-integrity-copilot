from datetime import timedelta

import pytest

from subsea_copilot.contracts import PipelineSegment, Point
from subsea_copilot.diagnostics import analyze_window
from subsea_copilot.ingest import normalize_records
from subsea_copilot.localization import locate
from subsea_copilot.replay import ReplayClock, completed_endpoints
from subsea_copilot.synthetic import generate_scenario


@pytest.fixture(scope="module")
def runs():
    result = {}
    for scenario in ("S1", "S2", "S3", "S4", "S5", "S6"):
        dataset = generate_scenario(scenario, duration_seconds=180)
        result[scenario] = (
            dataset,
            normalize_records(dataset.baseline, dataset.pack),
            normalize_records(dataset.records, dataset.pack),
        )
    return result


def snapshot(run, end=180, clock=185, observations=None, **kwargs):
    dataset, baseline, rows = run
    return analyze_window(
        dataset.pack,
        baseline,
        rows if observations is None else observations,
        "generation",
        end,
        clock,
        dataset.epoch,
        **kwargs,
    )


@pytest.mark.parametrize(
    ("scenario", "expected"),
    [
        ("S1", "suspected_leak"),
        ("S2", "sensor_or_telemetry_issue"),
        ("S3", "insufficient_evidence"),
        ("S4", "environmental_disturbance"),
        ("S5", "insufficient_evidence"),
        ("S6", "no_event"),
    ],
)
def test_label_free_scenario_inference_and_quality(runs, scenario, expected):
    result = snapshot(runs[scenario])
    assert result.event.hypothesis == expected
    assert result.quality.expected_samples == 72 * 60
    assert any(
        claim.value == {"code": "SYNTHETIC_UNCALIBRATED"} for claim in result.claims.values()
    )
    assert len(result.evidence) < 160
    if scenario == "S1":
        assert result.location.status == "located"
        assert result.location.best.segment_id == "P1"
        assert 350 <= result.location.best.chainage_m <= 450
        assert result.quality.status == "DEGRADED"
        assert not any(
            finding.drift_suspected
            for finding in result.quality.findings
            if finding.sensor_id in result.event.supporting_sensor_ids
        )
    else:
        assert result.location is None
    if scenario == "S3":
        assert result.quality.coverage == 0
        assert result.quality.status == "COVERAGE_LOST"


def test_one_support_removed_rechecks_observers_and_independence(runs):
    run = runs["S1"]
    full = snapshot(run)
    supporting = full.event.supporting_sensor_ids
    rows = [row for row in run[2] if row.sensor_id != supporting[0]]
    result = snapshot(run, observations=rows)
    assert result.event.hypothesis == "suspected_leak"
    assert result.event.failure_domain_count >= 2
    rows = [row for row in rows if row.sensor_id != supporting[1]]
    result = snapshot(run, observations=rows)
    assert result.event.hypothesis != "suspected_leak"
    assert result.location is None


def test_shared_failure_domain_cannot_supply_independent_leak_evidence(runs):
    dataset, baseline, rows = runs["S1"]
    pack = dataset.pack.model_copy(deep=True)
    for sensor in pack.sensors:
        sensor.failure_domain_id = "shared"
    result = analyze_window(pack, baseline, rows, "generation", 180, 185, dataset.epoch)
    assert result.event.hypothesis == "insufficient_evidence"
    assert result.location is None


def test_window_boundaries_arrival_cutoff_warmup_and_snapshot_lineage(runs):
    dataset, baseline, rows = runs["S6"]
    chosen = [row for row in rows if row.observed_at == dataset.epoch + timedelta(seconds=120)]
    boundary = chosen[0].model_copy(
        update={
            "id": "right",
            "observed_at": dataset.epoch + timedelta(seconds=180),
        }
    )
    late = chosen[1].model_copy(
        update={
            "id": "late",
            "received_at": dataset.epoch + timedelta(seconds=190),
        }
    )
    first = snapshot(runs["S6"], observations=[chosen[0], boundary, late])
    assert first.canonical_count == 1
    revised = snapshot(
        runs["S6"],
        clock=190,
        observations=[chosen[0], boundary, late],
        revision=2,
        predecessor_id=first.id,
    )
    assert revised.canonical_count == 2
    assert revised.input_hash != first.input_hash
    assert revised.predecessor_id == first.id
    assert snapshot(runs["S6"], end=55, clock=60).quality.status == "WARMING_UP"
    assert snapshot(runs["S6"], end=60, clock=64).event.hypothesis == "insufficient_evidence"
    stable = snapshot(runs["S6"], clock=190, observations=[chosen[0], boundary, late])
    assert stable.id == snapshot(runs["S6"], clock=195, observations=[late, boundary, chosen[0]]).id


def test_event_requires_raw_duration_not_count_or_simultaneous_spike(runs):
    dataset, baseline, rows = runs["S1"]
    # Preserve many high readings, but interleave missing seconds: no persistent run.
    intermittent = [
        row for row in rows if int((row.observed_at - dataset.epoch).total_seconds()) % 2 == 0
    ]
    pack = dataset.pack.model_copy(update={"min_coverage": 0.4})
    result = analyze_window(pack, baseline, intermittent, "generation", 180, 185, dataset.epoch)
    assert result.event.hypothesis != "suspected_leak"
    assert result.location is None


def test_crossing_candidates_are_ambiguous_and_model_mismatch_abstains(runs):
    pack = runs["S1"][0].pack.model_copy(deep=True)
    pack.segments.append(
        PipelineSegment(
            id="parallel",
            points=[Point(x=0, y=0), Point(x=800, y=0)],
            length_m=800,
        )
    )
    excess = {
        sensor.id: 12000
        / ((sensor.position.x - 400) ** 2 + sensor.position.y**2 + pack.location_r0_m**2)
        for sensor in pack.sensors
    }
    scales = {sensor.id: 0.03 for sensor in pack.sensors}
    fit = locate(pack, excess, scales, ["P1", "parallel"])
    assert fit.status == "ambiguous"
    assert {"P1", "parallel"} <= {candidate.segment_id for candidate in fit.compatible}
    fit = locate(pack, {sensor.id: 0.8 for sensor in pack.sensors}, scales, ["P1"])
    assert fit.status == "withheld"


def test_diagnosis_checks_nearby_crossing_even_without_associated_sensors(runs):
    dataset, baseline, rows = runs["S1"]
    pack = dataset.pack.model_copy(deep=True)
    crossing_x = snapshot(runs["S1"]).location.best.position.x
    pack.segments.append(
        PipelineSegment(
            id="crossing",
            points=[Point(x=crossing_x, y=-400), Point(x=crossing_x, y=400)],
            length_m=800,
        )
    )
    result = analyze_window(pack, baseline, rows, "crossing-run", 180, 185, dataset.epoch)
    assert result.event.hypothesis == "suspected_leak"
    assert result.location.status == "ambiguous"
    assert "crossing" in {candidate.segment_id for candidate in result.location.compatible}


def test_dense_subsecond_samples_do_not_invent_persistence(runs):
    dataset, baseline, rows = runs["S1"]
    counters = {}
    dense = []
    for row in rows:
        if row.observed_at < dataset.epoch + timedelta(seconds=120):
            continue
        key = row.sensor_id, row.channel
        index = counters.get(key, 0)
        counters[key] = index + 1
        dense.append(
            row.model_copy(
                update={
                    "observed_at": dataset.epoch + timedelta(seconds=140 + index * 0.001),
                }
            )
        )
    result = analyze_window(dataset.pack, baseline, dense, "dense", 180, 185, dataset.epoch)
    assert result.event.hypothesis != "suspected_leak"
    assert max(finding.persistence_seconds for finding in result.quality.findings) < 2


def test_downward_usable_spike_is_health_evidence_not_hard_invalidity(runs):
    dataset, baseline, rows = runs["S6"]
    changed = [
        row.model_copy(update={"value": 3.0})
        if row.sensor_id == "P1-ST1-A"
        and row.channel == "temperature"
        and row.observed_at == dataset.epoch + timedelta(seconds=140)
        else row
        for row in rows
    ]
    result = analyze_window(dataset.pack, baseline, changed, "negative", 180, 185, dataset.epoch)
    finding = next(
        finding
        for finding in result.quality.findings
        if finding.sensor_id == "P1-ST1-A" and finding.channel == "temperature"
    )
    assert finding.spike_count == 1
    assert finding.hard_excluded == 0
    assert result.event.hypothesis == "sensor_or_telemetry_issue"


def test_methane_only_never_implies_normal_or_leak(runs):
    dataset, baseline, rows = runs["S6"]
    changed = [
        row.model_copy(update={"value": 0.8})
        if row.sensor_id == "P1-ST1-A" and row.channel == "methane"
        else row
        for row in rows
    ]
    result = analyze_window(
        dataset.pack, baseline, changed, "methane-only", 180, 185, dataset.epoch
    )
    assert result.event.hypothesis == "insufficient_evidence"
    assert result.location is None
    assert any(
        claim.value == {"code": "NO_ACOUSTIC_CORROBORATION"} for claim in result.claims.values()
    )


def test_one_and_ten_speed_have_equal_arrival_filtered_diagnostics(runs):
    run = runs["S1"]
    results = []
    for speed in (1, 10):
        clock = ReplayClock(duration_seconds=190, speed=speed)
        clock.play()
        windows = {}
        last = 0
        while clock.playing:
            clock.advance(1)
            endpoints = completed_endpoints(clock.clock_seconds, run[0].pack, last)
            for endpoint in endpoints:
                if endpoint in {60, 120, 180}:
                    windows[endpoint] = snapshot(run, end=endpoint, clock=clock.clock_seconds)
            if endpoints:
                last = endpoints[-1]
        results.append(windows)
    assert results[0].keys() == results[1].keys() == {60, 120, 180}
    for endpoint in results[0]:
        first, accelerated = results[0][endpoint], results[1][endpoint]
        assert first.id == accelerated.id
        assert first.input_hash == accelerated.input_hash
        assert first.event == accelerated.event
        assert first.quality == accelerated.quality

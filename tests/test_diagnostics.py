"""Check numerical evidence against seeded signals and adversarial measurement mutations.

The analyzer receives normalized readings, not scenario labels. Tests distinguish
coverage, independent sustained drops, faulty peers and topology-limited brackets;
the expected labels here are test assertions, not runtime model instructions.
"""

from datetime import timedelta

import pytest

from subsea_copilot.anomaly import MedianMADDetector
from subsea_copilot.contracts import PipelineSegment, Point
from subsea_copilot.diagnostics import analyze_window
from subsea_copilot.ingest import normalize_records
from subsea_copilot.localization import locate, pipeline_distances
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
        ("S4", "insufficient_evidence"),
        ("S5", "insufficient_evidence"),
        ("S6", "no_event"),
    ],
)
def test_label_free_scenario_inference_and_quality(runs, scenario, expected):
    result = snapshot(runs[scenario])
    assert result.event.hypothesis == expected
    assert result.quality.expected_samples == 24 * 60
    assert any(
        claim.value == {"code": "SYNTHETIC_UNCALIBRATED"} for claim in result.claims.values()
    )
    assert len(result.evidence) < 160
    if scenario == "S1":
        assert result.location.status == "located"
        assert result.location.best.segment_id == "P1"
        assert 350 <= result.location.best.chainage_m <= 450
        assert result.location.inspection_start_m == 200
        assert result.location.inspection_end_m == 600
        assert result.location.best.residual is None
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


def test_inspection_bracket_does_not_invent_coordinates_for_uninstrumented_crossing(runs):
    pack = runs["S1"][0].pack.model_copy(deep=True)
    pack.segments.append(
        PipelineSegment(
            id="parallel",
            points=[Point(x=0, y=0), Point(x=800, y=0)],
            length_m=800,
        )
    )
    excess = {
        sensor.id: 1.0 if sensor.segment_id == "P1" and sensor.chainage_m in {300, 500} else 0
        for sensor in pack.sensors
    }
    scales = {sensor.id: 0.04 for sensor in pack.sensors}
    fit = locate(pack, excess, scales, ["P1", "parallel"])
    assert fit.status == "located"
    assert {candidate.segment_id for candidate in fit.compatible} == {"P1"}
    assert (fit.inspection_start_m, fit.inspection_end_m) == (200, 600)
    fit = locate(pack, {sensor.id: 0.8 for sensor in pack.sensors}, scales, ["P1"])
    assert fit.status == "withheld"


def test_pressure_taps_on_one_pipe_do_not_localize_an_unconnected_crossing(runs):
    dataset, baseline, rows = runs["S1"]
    pack = dataset.pack.model_copy(deep=True)
    crossing_y = snapshot(runs["S1"]).location.best.position.y
    pack.segments.append(
        PipelineSegment(
            id="crossing",
            points=[Point(x=-400, y=crossing_y), Point(x=400, y=crossing_y)],
            length_m=800,
        )
    )
    result = analyze_window(pack, baseline, rows, "crossing-run", 180, 185, dataset.epoch)
    assert result.event.hypothesis == "suspected_leak"
    assert result.location.status == "located"
    assert "crossing" not in {candidate.segment_id for candidate in result.location.compatible}


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
        row.model_copy(update={"value": 75.0})
        if row.sensor_id == "P1-ST1-A"
        and row.channel == "pressure"
        and row.observed_at == dataset.epoch + timedelta(seconds=140)
        else row
        for row in rows
    ]
    result = analyze_window(dataset.pack, baseline, changed, "negative", 180, 185, dataset.epoch)
    finding = next(
        finding
        for finding in result.quality.findings
        if finding.sensor_id == "P1-ST1-A" and finding.channel == "pressure"
    )
    assert finding.spike_count == 1
    assert finding.hard_excluded == 0
    assert result.event.hypothesis == "sensor_or_telemetry_issue"


def test_isolated_pressure_offset_with_healthy_paired_instrument_supports_fault_review(runs):
    dataset, baseline, rows = runs["S6"]
    changed = [
        row.model_copy(update={"value": 78.0})
        if row.sensor_id == "P1-ST1-A" and row.channel == "pressure"
        else row
        for row in rows
    ]
    result = analyze_window(
        dataset.pack, baseline, changed, "isolated-offset", 180, 185, dataset.epoch
    )
    assert result.event.hypothesis == "sensor_or_telemetry_issue"
    assert result.location is None
    assert next(f for f in result.quality.findings if f.sensor_id == "P1-ST1-A").peer_disagreement


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


def test_lightweight_model_uses_normal_preroll_and_does_not_adapt_away_a_drop():
    model = MedianMADDetector.fit([80.0] * 60, 0.04, 5)
    assert model.score(79) < -model.threshold
    assert model.score(81) > model.threshold
    assert model.center == 80
    assert model.scale == 0.04


def test_correlated_fault_in_one_gateway_is_not_independent_leak_evidence(runs):
    dataset, baseline, rows = runs["S1"]
    pack = dataset.pack.model_copy(deep=True)
    for sensor in pack.sensors:
        if sensor.segment_id == "P1" and sensor.chainage_m in {300, 500}:
            sensor.failure_domain_id = "same-broken-gateway"
    result = analyze_window(pack, baseline, rows, "shared-gateway", 180, 185, dataset.epoch)
    assert result.event.hypothesis == "insufficient_evidence"
    assert result.location is None


def test_drops_at_different_times_do_not_form_a_spatial_event(runs):
    dataset, baseline, rows = runs["S6"]
    changed = []
    for row in rows:
        seconds = (row.observed_at - dataset.epoch).total_seconds()
        station = row.sensor_id.rsplit("-", 1)[0]
        if (station == "P1-ST2" and 120 <= seconds < 140) or (
            station == "P1-ST3" and 150 <= seconds < 170
        ):
            row = row.model_copy(update={"value": 78.0})
        changed.append(row)
    result = analyze_window(dataset.pack, baseline, changed, "non-overlap", 180, 185, dataset.epoch)
    assert result.event.hypothesis == "insufficient_evidence"
    assert result.location is None


def test_broad_operating_change_requires_context_not_a_forced_leak_diagnosis(runs):
    result = snapshot(runs["S4"])
    assert result.event.hypothesis == "insufficient_evidence"
    assert "COMMON_MODE_PRESSURE_CHANGE" in result.event.counterevidence
    assert "OPERATING_CONTEXT_REQUIRED" in result.event.counterevidence
    assert result.location is None
    assert sum(f.anomaly_count > 0 for f in result.quality.findings) == 24


@pytest.mark.parametrize("broad", [True, False])
def test_positive_pressure_changes_are_not_called_faults_or_brief_transients(runs, broad):
    dataset, baseline, rows = runs["S6"]
    changed = [
        row.model_copy(update={"value": 82.0})
        if broad or row.sensor_id.startswith(("P1-ST2-", "P1-ST3-"))
        else row
        for row in rows
    ]
    result = analyze_window(dataset.pack, baseline, changed, "positive", 180, 185, dataset.epoch)
    assert result.event.hypothesis == "insufficient_evidence"
    expected = "COMMON_MODE_PRESSURE_CHANGE" if broad else "UNEXPLAINED_PRESSURE_CHANGE"
    assert expected in result.event.counterevidence
    assert "CORRELATED_PRESSURE_TRANSIENT" not in result.event.counterevidence
    assert result.location is None


def test_short_correlated_transient_is_not_called_scattered_sensor_faults(runs):
    dataset, baseline, rows = runs["S6"]
    changed = [
        row.model_copy(update={"value": 78.0})
        if row.sensor_id.startswith(("P1-ST2-", "P1-ST3-"))
        and 145 <= (row.observed_at - dataset.epoch).total_seconds() < 148
        else row
        for row in rows
    ]
    result = analyze_window(dataset.pack, baseline, changed, "transient", 180, 185, dataset.epoch)
    assert result.event.hypothesis == "insufficient_evidence"
    assert "CORRELATED_PRESSURE_TRANSIENT" in result.event.counterevidence
    assert result.location is None


def test_opposite_paired_offsets_are_not_independent_pressure_drop_evidence(runs):
    dataset, baseline, rows = runs["S6"]
    changed = []
    for row in rows:
        if row.sensor_id.startswith(("P1-ST2-", "P1-ST3-")):
            row = row.model_copy(update={"value": 78.0 if row.sensor_id.endswith("-A") else 82.0})
        changed.append(row)
    result = analyze_window(dataset.pack, baseline, changed, "opposite", 180, 185, dataset.epoch)
    assert result.event.hypothesis != "suspected_leak"
    assert result.location is None
    assert all(
        finding.peer_disagreement
        for finding in result.quality.findings
        if finding.sensor_id.startswith(("P1-ST2-", "P1-ST3-"))
    )


def test_no_healthy_reference_on_both_sides_withholds_the_inspection_interval(runs):
    pack = runs["S1"][0].pack
    deficits = {
        sensor.id: 1.0 if sensor.segment_id == "P1" and sensor.chainage_m <= 500 else 0
        for sensor in pack.sensors
    }
    fit = locate(pack, deficits, {sensor.id: 0.04 for sensor in pack.sensors}, ["P1"])
    assert fit.status == "withheld"
    assert fit.inspection_start_m is None and fit.inspection_end_m is None


def test_sustained_pressure_rise_is_not_a_healthy_localization_reference(runs):
    dataset, baseline, rows = runs["S1"]
    changed = [
        row.model_copy(update={"value": 82.0}) if row.sensor_id.startswith("P1-ST4-") else row
        for row in rows
    ]
    result = analyze_window(
        dataset.pack, baseline, changed, "unhealthy-bracket", 180, 185, dataset.epoch
    )
    assert result.event.hypothesis == "suspected_leak"
    assert result.location and result.location.status == "withheld"
    assert result.location.inspection_start_m is None


def test_single_drop_without_a_healthy_peer_abstains_instead_of_declaring_a_fault(runs):
    dataset, baseline, rows = runs["S6"]
    changed = [
        row.model_copy(update={"value": 78.0}) if row.sensor_id == "P1-ST1-A" else row
        for row in rows
        if row.sensor_id != "P1-ST1-B"
    ]
    result = analyze_window(dataset.pack, baseline, changed, "unpaired", 180, 185, dataset.epoch)
    assert result.event.hypothesis == "insufficient_evidence"
    assert result.location is None


def test_geometric_crossing_does_not_create_pipeline_connectivity(runs):
    pack = runs["S1"][0].pack.model_copy(deep=True)
    pack.segments.append(
        PipelineSegment(
            id="crossing",
            points=[Point(x=-400, y=-400), Point(x=400, y=-400)],
            length_m=800,
        )
    )
    pack.sensors.append(
        pack.sensors[0].model_copy(
            update={
                "id": "crossing-sensor",
                "segment_id": "crossing",
                "chainage_m": 400,
                "position": Point(x=0, y=-400),
            }
        )
    )
    assert pipeline_distances(pack)["P1-ST2-A", "crossing-sensor"] == float("inf")


def test_brief_network_is_upright_y_with_pipe_wall_pressure_taps(runs):
    pack = runs["S1"][0].pack
    trunk, left, right = pack.segments
    assert trunk.name == "Trunk" and left.name == "Branch A" and right.name == "Branch B"
    junction = trunk.points[-1]
    assert trunk.points[0].x == junction.x
    assert trunk.points[0].y < junction.y
    assert left.points[0] == right.points[0] == junction
    assert left.points[-1].x < junction.x < right.points[-1].x
    assert left.points[-1].y > junction.y and right.points[-1].y > junction.y
    for segment in pack.segments:
        start, end = segment.points
        dx, dy = end.x - start.x, end.y - start.y
        for sensor in (item for item in pack.sensors if item.segment_id == segment.id):
            axial = (
                (sensor.position.x - start.x) * dx + (sensor.position.y - start.y) * dy
            ) / segment.length_m
            offset = (
                abs(dx * (sensor.position.y - start.y) - dy * (sensor.position.x - start.x))
                / segment.length_m
            )
            assert axial == pytest.approx(sensor.chainage_m)
            assert offset == pytest.approx(segment.diameter_m / 2)


def test_brief_examples_are_actual_demo_evidence_not_a_separate_story(runs):
    import json
    from pathlib import Path

    frozen = json.loads(
        (Path(__file__).parents[1] / "fixtures" / "synthetic" / "brief-evidence.json").read_text(
            encoding="utf-8"
        )
    )
    for scenario in ("S1", "S2"):
        current = snapshot(runs[scenario], end=140, clock=145)
        retained = frozen["examples"][scenario]["snapshot"]
        assert retained["input_hash"] == current.input_hash
        assert retained["quality"] == current.quality.model_dump(mode="json")
        assert retained["event"] == current.event.model_dump(mode="json")
        assert retained["location"] == (
            current.location.model_dump(mode="json") if current.location else None
        )
        dataset, _, rows = runs[scenario]
        for sensor, trace in frozen["examples"][scenario]["traces"].items():
            assert trace == [
                {
                    "seconds": (row.observed_at - dataset.epoch).total_seconds(),
                    "value": row.value if row.validity == "usable" else None,
                }
                for row in sorted(rows, key=lambda row: row.observed_at)
                if row.sensor_id == sensor
                and current.window_start <= row.observed_at < current.window_end
                and row.received_at <= dataset.epoch + timedelta(seconds=145)
            ]
    for trace in frozen["examples"]["S1"]["traces"].values():
        before = [row["value"] for row in trace if row["seconds"] < 90 and row["value"] is not None]
        after = [
            row["value"] for row in trace if row["seconds"] >= 130 and row["value"] is not None
        ]
        assert sum(before) / len(before) - sum(after) / len(after) > 0.5
    findings = {f.sensor_id: f for f in snapshot(runs["S2"], end=140, clock=145).quality.findings}
    assert findings["P2-ST2-A"].spike_count > 0
    assert findings["P3-ST3-A"].missing > 0
    assert findings["P1-ST2-A"].drift_suspected

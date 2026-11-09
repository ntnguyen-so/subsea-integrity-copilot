"""Verify authored spatial patterns actually appear in normalized measured traces.

Connected near/far deficits evolve together; peer, temporal and shared-gateway
comparisons distinguish nuisance faults without treating recipe labels as predictions.
"""

from statistics import correlation, median, pstdev

import pytest

from subsea_copilot.anomaly import MedianMADDetector
from subsea_copilot.ingest import normalize_records
from subsea_copilot.localization import pipeline_distances
from subsea_copilot.synthetic import generate_scenario


@pytest.fixture(scope="module", params=[2026, 91000, 91001])
def pressure_traces(request):
    dataset = generate_scenario("S7", seed=request.param, duration_seconds=180)
    baselines = {sensor.id: [] for sensor in dataset.pack.sensors}
    traces = {sensor.id: {} for sensor in dataset.pack.sensors}
    for row in normalize_records(dataset.baseline, dataset.pack):
        if row.validity == "usable" and row.value is not None:
            baselines[row.sensor_id].append(row.value)
    for row in normalize_records(dataset.records, dataset.pack):
        if row.validity == "usable" and row.value is not None:
            second = int((row.observed_at - dataset.epoch).total_seconds())
            traces[row.sensor_id][second] = row.value
    models = {
        sensor_id: MedianMADDetector.fit(
            values, dataset.pack.minimum_scales["pressure"], dataset.pack.anomaly_threshold
        )
        for sensor_id, values in baselines.items()
    }
    return dataset, models, traces


def _deficit(models, traces, sensor_id, start=120, end=140):
    return models[sensor_id].center - median(
        value for second, value in traces[sensor_id].items() if start <= second < end
    )


def test_connected_pressure_footprint_has_several_above_floor_magnitudes(pressure_traces):
    dataset, models, traces = pressure_traces
    for side in ("A", "B"):
        for stations in ((4, 3, 2, 1), (5, 6, 7, 8)):
            ids = [f"P5-ST{station}-{side}" for station in stations]
            drops = [_deficit(models, traces, sensor_id) for sensor_id in ids]
            assert all(near > far for near, far in zip(drops[:-1], drops[1:], strict=True))
            assert drops[0] > 3 * drops[-1]
            for sensor_id, drop in zip(ids, drops, strict=True):
                model = models[sensor_id]
                assert drop > model.threshold * model.scale
                readings = [
                    value for second, value in traces[sensor_id].items() if 120 <= second < 140
                ]
                assert sum(model.score(value) < -model.threshold for value in readings) >= (
                    0.7 * len(readings)
                )
    distances = pipeline_distances(dataset.pack)
    assert distances["P5-ST4-A", "P4-ST1-A"] < distances["P5-ST4-A", "P6-ST1-A"]
    weak_drop = _deficit(models, traces, "P4-ST1-A")
    weak_model = models["P4-ST1-A"]
    assert 0 < weak_drop < weak_model.threshold * weak_model.scale
    assert weak_drop > _deficit(models, traces, "P6-ST1-A") + 0.07
    for station in range(1, 9):
        assert (
            abs(
                _deficit(models, traces, f"P5-ST{station}-A")
                - _deficit(models, traces, f"P5-ST{station}-B")
            )
            < 0.1
        )


def test_near_and_far_traces_develop_together_then_remain_depressed(pressure_traces):
    _, models, traces = pressure_traces
    for sensor_id in ("P5-ST4-A", "P5-ST1-A", "P5-ST8-B"):
        initial = _deficit(models, traces, sensor_id, 90, 96)
        developing = _deficit(models, traces, sensor_id, 102, 108)
        settled = _deficit(models, traces, sensor_id, 125, 140)
        later = _deficit(models, traces, sensor_id, 155, 175)
        assert initial < developing < settled
        assert abs(later - settled) < 0.15 * later
    near, far = [
        [_deficit(models, traces, sensor_id, second, second + 5) for second in range(90, 140, 5)]
        for sensor_id in ("P5-ST4-A", "P5-ST1-A")
    ]
    assert correlation(near, far) > 0.85
    assert _deficit(models, traces, "P4-ST1-A", 125, 140) > (
        _deficit(models, traces, "P4-ST1-A", 90, 96) + models["P4-ST1-A"].scale
    )


def test_faults_offer_distinct_peer_temporal_and_shared_gateway_comparisons(pressure_traces):
    dataset, models, traces = pressure_traces
    stuck = [value for second, value in traces["P6-ST8-B"].items() if 90 <= second < 175]
    live_peer = [value for second, value in traces["P6-ST8-A"].items() if 90 <= second < 175]
    assert len(stuck) > 75
    assert len(set(stuck)) == 1
    assert pstdev(live_peer) > 0.02

    intermittent = models["P3-ST2-A"]
    scores = {
        second: intermittent.score(value)
        for second, value in traces["P3-ST2-A"].items()
        if 110 <= second < 175
    }
    assert sum(score < -intermittent.threshold for score in scores.values()) >= 15
    assert sum(abs(score) < intermittent.threshold for score in scores.values()) >= 30
    assert abs(_deficit(models, traces, "P3-ST2-B")) < 0.1

    drift_id = "P3-ST7-A"
    assert _deficit(models, traces, drift_id, 155, 175) > (
        _deficit(models, traces, drift_id, 100, 110) + 0.5
    )
    assert abs(_deficit(models, traces, "P3-ST7-B")) < 0.1
    impulse = models["P6-ST3-A"]
    spikes = [
        second
        for second, value in traces["P6-ST3-A"].items()
        if 90 <= second < 175 and impulse.score(value) > impulse.threshold
    ]
    assert len(spikes) >= 2
    assert all(
        abs(impulse.score(traces["P6-ST3-A"][second + offset])) < impulse.threshold
        for second in spikes
        for offset in (-1, 1)
        if second + offset in traces["P6-ST3-A"]
    )
    impulse_times = []
    for sensor_id, peer_id in (
        ("P2-ST2-A", "P2-ST2-B"),
        ("P4-ST7-B", "P4-ST7-A"),
        ("P6-ST3-A", "P6-ST3-B"),
    ):
        times = {
            second
            for second in traces[sensor_id].keys() & traces[peer_id].keys() & set(range(90, 175))
            if traces[sensor_id][second] - traces[peer_id][second] > 1.5
        }
        assert len(times) >= 2
        impulse_times.append(times)
    assert not any(
        first & second
        for index, first in enumerate(impulse_times)
        for second in impulse_times[index + 1 :]
    )

    gateway_ids = [
        sensor.id for sensor in dataset.pack.sensors if sensor.failure_domain_id == "gateway-P7-0"
    ]
    expected_times = set(range(90, 175))
    shared_missing = set.intersection(
        *(expected_times - traces[sensor_id].keys() for sensor_id in gateway_ids)
    )
    assert len(shared_missing) >= 6
    assert len(expected_times - traces["P7-ST2-A"].keys()) < len(shared_missing)
    gateway_drops = [_deficit(models, traces, sensor_id) for sensor_id in gateway_ids]
    assert min(gateway_drops) > 0.6
    assert max(gateway_drops) - min(gateway_drops) < 0.1
    assert abs(_deficit(models, traces, "P7-ST2-A")) < 0.1
    assert _deficit(models, traces, "P2-ST4-A") < -0.3

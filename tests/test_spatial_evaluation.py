from __future__ import annotations

import copy
from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from subsea_copilot.contracts import AgentResult, AgentTask, utc_now
from subsea_copilot.diagnostics import analyze_window
from subsea_copilot.golden_evaluation import install_golden_input
from subsea_copilot.ingest import normalize_records
from subsea_copilot.localization import locate
from subsea_copilot.replay_sources import source_payload
from subsea_copilot.runtime.registry import REGISTRY
from subsea_copilot.runtime.workflow import AgentService
from subsea_copilot.spatial_data import spatial_cases, spatial_dataset, spatial_truth
from subsea_copilot.spatial_evaluation import frame_record, spatial_metrics
from subsea_copilot.synthetic import ReplayDataset
from subsea_copilot.validation import render_result


@pytest.fixture(scope="module")
def network() -> ReplayDataset:
    return spatial_dataset(spatial_cases()[0], 20261109, "northsea")


def test_extended_sources_are_s7_scale_and_truth_is_not_runtime_input(
    network: ReplayDataset,
) -> None:
    assert len(network.pack.sensors) == 112
    assert len(network.pack.segments) == 7
    assert sum(segment.length_m for segment in network.pack.segments) == 11200
    assert len(network.records) > 39000
    assert set(source_payload(network)) == {"pack", "baseline", "records", "epoch"}
    assert not any("source-only" == sensor.id for sensor in network.pack.sensors)
    assert all(row.source_id == "synthetic-gateway" for row in network.records)
    assert any(row.unit == "MPa" for row in network.records)
    assert any(row.value == "not-a-pressure" for row in network.records)


def test_broad_pressure_peak_has_a_bounded_focus_without_unaffected_end_stations(
    network: ReplayDataset,
) -> None:
    profile = [0.3, 0.7, 1.2, 1.8, 1.8, 1.2, 0.7, 0.3]
    deficits = {
        sensor.id: profile[int((sensor.chainage_m - 100) / 200)]
        for sensor in network.pack.sensors if sensor.segment_id == "P5"
    }
    scales = dict.fromkeys(deficits, 0.04)
    assert locate(network.pack, deficits, scales, ["P5"]).status == "withheld"
    focus = locate(
        network.pack, deficits, scales, ["P5"], focus_deficits=deficits,
    )
    assert focus.status == "located"
    assert focus.method == "pressure-peak-focus-v1"
    assert (focus.inspection_start_m, focus.inspection_end_m) == (600, 1000)
    assert focus.station_bracket_m == [500, 700, 900, 1100]


def test_first_call_profiles_cover_anomalies_and_actual_comparison_partners(
    network: ReplayDataset,
) -> None:
    snapshot = analyze_window(
        network.pack, normalize_records(network.baseline, network.pack),
        normalize_records(network.records, network.pack),
        generation_id="paired-intake-test", end_seconds=360, clock_seconds=365,
        epoch=network.epoch,
    )
    groups = AgentService._initial_pressure_comparisons(snapshot)
    reviewed = {identifier for group in groups for identifier in group["sensor_ids"]}
    assert {
        finding.sensor_id for finding in snapshot.quality.findings if finding.anomaly_count
    } <= reviewed
    assert {"P4-ST7-A", "P4-ST7-B", "P6-ST8-A", "P6-ST8-B"} <= reviewed
    assert {"P7-ST1-A", "P7-ST1-B", "P7-ST2-A", "P7-ST2-B"} <= reviewed
    for group in groups:
        ids = set(group["sensor_ids"])
        assert 2 <= len(ids) <= 24
        assert group["paired_only"]
        for sensor in network.pack.sensors:
            if sensor.id in ids:
                assert {
                    other.id for other in network.pack.sensors
                    if other.segment_id == sensor.segment_id
                    and other.station_id == sensor.station_id
                } <= ids
        assert (group["start_seconds"], group["split_seconds"], group["end_seconds"]) == (
            0, 180, 360,
        )


def test_quality_review_keeps_material_gaps_ahead_of_large_pressure_footprints(
    network: ReplayDataset,
) -> None:
    from subsea_copilot.budgets import HEALTH_PAGE_SIZE
    from subsea_copilot.runtime.gateway import ranked_findings

    snapshot = analyze_window(
        network.pack, normalize_records(network.baseline, network.pack),
        normalize_records(network.records, network.pack),
        generation_id="quality-priority-test", end_seconds=360, clock_seconds=365,
        epoch=network.epoch,
    )
    reviewed = {finding.sensor_id for finding in ranked_findings(snapshot)[:HEALTH_PAGE_SIZE]}
    assert {"P1-ST7-B", "P3-ST5-B", "P4-ST8-A"} <= reviewed


def test_pressure_peak_public_explanation_does_not_call_weaker_neighbors_unaffected(
    network: ReplayDataset,
) -> None:
    snapshot = analyze_window(
        network.pack, normalize_records(network.baseline, network.pack),
        normalize_records(network.records, network.pack),
        generation_id="render-focus-test", end_seconds=150, clock_seconds=155,
        epoch=network.epoch,
    )
    refs = [claim.id for claim in snapshot.claims.values() if claim.kind == "location"]
    task = AgentTask(
        id="render-focus", root_id="render-focus", generation_id=snapshot.generation_id,
        snapshot_id=snapshot.id, role="operator_response",
        site_id=snapshot.site_id, mode="scripted",
        purpose=REGISTRY["operator_response"].purpose, question="Where is the focus?",
        deadline=utc_now() + timedelta(seconds=300),
    )
    text = render_result(
        AgentResult(outcome="supported", claim_refs=refs, limitations=[]), task, snapshot,
    )
    assert "weaker neighboring stations at 500/1100 m" in text
    assert "unaffected stations" not in text


@pytest.mark.parametrize(
    "profile",
    [[1.0] * 8, [0.3, 0.7, 1.8, 1.1, 1.1, 1.8, 0.7, 0.3]],
)
def test_uniform_or_disconnected_pressure_peaks_do_not_release_a_focus(
    network: ReplayDataset, profile: list[float],
) -> None:
    deficits = {
        sensor.id: profile[int((sensor.chainage_m - 100) / 200)]
        for sensor in network.pack.sensors if sensor.segment_id == "P5"
    }
    result = locate(
        network.pack, deficits, dict.fromkeys(deficits, 0.04), ["P5"],
        focus_deficits=deficits,
    )
    assert result.status != "located"
    assert result.inspection_start_m is None


def test_pressure_focus_cannot_skip_a_missing_immediate_comparison(
    network: ReplayDataset,
) -> None:
    profile = [0.3, 0.7, 1.2, 1.8, 1.8, 1.2, 0.7, 0.3]
    deficits = {
        sensor.id: profile[int((sensor.chainage_m - 100) / 200)]
        for sensor in network.pack.sensors if sensor.segment_id == "P5"
    }
    focus_values = {
        key: value for key, value in deficits.items() if key not in {"P5-ST3-A", "P5-ST3-B"}
    }
    result = locate(
        network.pack, deficits, dict.fromkeys(deficits, 0.04), ["P5"],
        focus_deficits=focus_values,
    )
    assert result.status == "withheld"
    assert "comparison station is unavailable" in result.reason


def test_pressure_focus_requires_independence_in_its_local_comparisons(
    network: ReplayDataset,
) -> None:
    profile = [0.3, 0.7, 1.2, 1.8, 1.8, 1.2, 0.7, 0.3]
    pack = network.pack.model_copy(update={"sensors": [
        sensor.model_copy(update={"failure_domain_id": "shared-core"})
        if sensor.segment_id == "P5" and 500 <= sensor.chainage_m <= 1100 else sensor
        for sensor in network.pack.sensors
    ]})
    deficits = {
        sensor.id: profile[int((sensor.chainage_m - 100) / 200)]
        for sensor in pack.sensors if sensor.segment_id == "P5"
    }
    result = locate(
        pack, deficits, dict.fromkeys(deficits, 0.04), ["P5"], focus_deficits=deficits,
    )
    assert result.status == "withheld"
    assert "comparisons lack independent" in result.reason


def test_temporal_source_labels_do_not_show_future_faults(network: ReplayDataset) -> None:
    recipe = spatial_cases()[0]
    before = spatial_truth(recipe, network, 90)
    early = spatial_truth(recipe, network, 150)
    late = spatial_truth(recipe, network, 360)
    assert before["leak_source"] is None and before["sensor_issues"] == []
    assert early["leak_source"]["segment_id"] == "P5"
    assert {item["kind"] for item in early["sensor_issues"]} == {"offset"}
    assert len(early["sensor_issues"]) == 8
    assert {item["kind"] for item in late["sensor_issues"]} == {
        "offset",
        "drift",
        "spike",
        "invalid",
        "missing",
        "flatline",
    }
    assert late["operating_change"] is None
    assert early["operating_change"]["segment_id"] == "P2"


def test_extended_install_preserves_full_duration_without_changing_small_default(
    network: ReplayDataset,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        "subsea_copilot.golden_evaluation.freeze_replay_source", lambda dataset: "test-source"
    )
    monitor = SimpleNamespace(
        store=SimpleNamespace(
            tenant_id="test", create_replay=Mock(side_effect=lambda replay: replay)
        ),
        _sources={},
    )
    assert (
        install_golden_input(monitor, network, "live", duration_seconds=360).duration_seconds == 360
    )
    assert install_golden_input(monitor, network, "live").duration_seconds == 120


def test_frame_contains_only_current_detector_data_and_no_final_agent_output(
    network: ReplayDataset,
) -> None:
    observations = normalize_records(network.records, network.pack)
    snapshot = analyze_window(
        network.pack,
        normalize_records(network.baseline, network.pack),
        observations,
        generation_id="test",
        end_seconds=150,
        clock_seconds=155,
        epoch=network.epoch,
    )
    frame = frame_record(snapshot, spatial_truth(spatial_cases()[0], network, 150), "N1@150")
    assert frame["source_seconds"] == 150
    assert frame["review_case_id"] == "N1@150"
    assert "extraction" not in frame and "interpretation" not in frame
    assert "P1-ST6-A" not in frame["detector"]["pressure_anomaly_sensors"]
    assert frame["input_hash"] == snapshot.input_hash


def test_continuous_pressure_region_is_not_split_into_separate_neighborhoods(
    network: ReplayDataset,
) -> None:
    snapshot = analyze_window(
        network.pack,
        normalize_records(network.baseline, network.pack),
        normalize_records(network.records, network.pack),
        generation_id="connected-region",
        end_seconds=150,
        clock_seconds=155,
        epoch=network.epoch,
    )
    assert snapshot.event.hypothesis == "suspected_leak"
    assert snapshot.event.segment_ids == ["P5"]
    assert len(snapshot.event.supporting_sensor_ids) == 16
    assert "MULTIPLE_PRESSURE_REGIONS" not in snapshot.event.counterevidence
    assert snapshot.location is not None and snapshot.location.status == "located"
    assert snapshot.location.method == "pressure-peak-focus-v1"
    assert "not hydraulic leak coordinates" in snapshot.location.reason


def test_short_onset_and_stuck_readings_have_direct_measured_summaries(
    network: ReplayDataset,
) -> None:
    baseline = normalize_records(network.baseline, network.pack)
    observations = normalize_records(network.records, network.pack)
    early = analyze_window(
        network.pack, baseline, observations, generation_id="onset",
        end_seconds=95, clock_seconds=100, epoch=network.epoch,
    )
    summary = next(
        evidence.value for evidence in early.evidence.values()
        if evidence.kind == "channel_summary" and evidence.sensor_id == "P5-ST4-A"
    )
    assert summary["recent_5s_period_seconds"] == [90, 95]
    assert summary["recent_5s_usable_samples"] == 5
    assert summary["recent_5s_pressure_drop_bar"] > summary["recent_pressure_drop_bar"] + 0.3
    assert early.event.persistence_seconds < network.pack.persistence_seconds
    late = analyze_window(
        network.pack, baseline, observations, generation_id="flatline",
        end_seconds=360, clock_seconds=365, epoch=network.epoch,
    )
    summaries = {
        evidence.sensor_id: evidence.value for evidence in late.evidence.values()
        if evidence.kind == "channel_summary"
    }
    assert summaries["P6-ST8-B"]["usable_pressure_range_bar"] == 0
    assert summaries["P6-ST8-A"]["usable_pressure_range_bar"] > 0


def test_withheld_broad_location_and_failed_later_window_are_not_removed(
    network: ReplayDataset,
) -> None:
    row = {
        "case_id": "N1@150",
        "status": "completed",
        "truth": spatial_truth(spatial_cases()[0], network, 150),
        "accepted_report": True,
        "extraction": {
            "mapping": {
                "leaks": [{"segment_id": "P5", "assertion": "suspected", "interval": None}],
                "sensor_issues": [],
                "instrumentation_concern": True,
            }
        },
    }
    failed = copy.deepcopy(row)
    failed.update(case_id="N1@360", status="failed", accepted_report=False, extraction=None)
    metrics = spatial_metrics({"cases": [row, failed], "planned_cases": 2})
    assert metrics["groups"]["leak_recognition"]["recall"]["value"] == 0.5
    assert metrics["rates"]["localization_containment"]["denominator"] == 2
    assert metrics["rates"]["localization_containment"]["numerator"] == 0
    assert metrics["rates"]["accepted_report_coverage"]["value"] == 0.5
    assert not any(name.startswith("detector_") for name in metrics["groups"])

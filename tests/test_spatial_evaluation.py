from __future__ import annotations

import copy
from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from subsea_copilot.contracts import AgentResult, AgentTask, WindowSnapshot, utc_now
from subsea_copilot.diagnostics import analyze_window
from subsea_copilot.golden_evaluation import install_golden_input
from subsea_copilot.ingest import normalize_records
from subsea_copilot.localization import locate
from subsea_copilot.monitoring import instrument_signals, pressure_context_ready
from subsea_copilot.replay import arrived_records
from subsea_copilot.replay_sources import source_payload
from subsea_copilot.runtime.registry import REGISTRY
from subsea_copilot.runtime.workflow import AgentService
from subsea_copilot.spatial_data import (
    spatial_cases,
    spatial_dataset,
    spatial_truth,
    temporal_cases,
)
from subsea_copilot.spatial_evaluation import (
    InstrumentReviews,
    frame_record,
    public_task,
    spatial_metrics,
    spatial_timing,
)
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
    groups = AgentService._initial_pressure_comparisons(snapshot, measurements_only=True)
    reviewed = {identifier for group in groups for identifier in group["sensor_ids"]}
    assert reviewed == {sensor.id for sensor in network.pack.sensors}
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


@pytest.mark.parametrize("case_index,flatline", [(0, "P6-ST8-B"), (1, "P5-ST8-B")])
def test_new_instrument_signals_get_an_early_followup_with_recent_flatline_pairs(
    case_index: int, flatline: str,
) -> None:
    dataset = spatial_dataset(spatial_cases()[case_index], 20261109, "northsea")
    baseline = normalize_records(dataset.baseline, dataset.pack)
    records = normalize_records(dataset.records, dataset.pack)

    def window(end: int) -> WindowSnapshot:
        return analyze_window(
            dataset.pack, baseline, records, generation_id="instrument-followup",
            end_seconds=end, clock_seconds=end + 5, epoch=dataset.epoch,
        )

    reviews = InstrumentReviews()
    reviews.reviewed(window(150), dataset.pack)
    admitted = []
    for end in range(175, 271, 5):
        snapshot = window(end)
        kind = reviews.due(snapshot, dataset.pack)
        if kind:
            admitted.append(end)
            reviews.reviewed(snapshot, dataset.pack)
    assert admitted == [210, 270]
    snapshot = window(210)
    signals = instrument_signals(snapshot, dataset.pack)
    assert ("P4-ST8-A", "invalid") in signals
    assert {kind for _, kind in signals} <= {"anomaly", "missing", "invalid"}
    summary = next(
        item.value for item in snapshot.evidence.values()
        if item.kind == "channel_summary" and item.sensor_id == flatline
    )
    assert summary["usable_pressure_range_bar"] > 0
    assert summary["recent_pressure_range_bar"] == 0
    groups = AgentService._initial_pressure_comparisons(snapshot, measurements_only=True)
    selected = {identifier for group in groups for identifier in group["sensor_ids"]}
    assert {
        "P1-ST6-A", "P3-ST7-A", "P4-ST7-B", "P4-ST8-A",
        "P1-ST7-B", "P3-ST5-B", flatline, flatline[:-1] + "A",
    } <= selected


def test_missing_only_reviews_admit_immediately_without_a_pressure_or_fault_verdict(
    network: ReplayDataset,
) -> None:
    snapshot = analyze_window(
        network.pack, normalize_records(network.baseline, network.pack),
        normalize_records(network.records, network.pack),
        generation_id="quality-only", end_seconds=210, clock_seconds=215, epoch=network.epoch,
    )
    findings = [
        finding.model_copy(update={
            "anomaly_count": 0, "spike_count": 0, "peer_disagreement": False,
            "drift_suspected": False, "hard_excluded": 0,
            "missing": 20 if finding.sensor_id == "P1-ST7-B" else 0,
        }) for finding in snapshot.quality.findings
    ]
    snapshot = snapshot.model_copy(update={
        "quality": snapshot.quality.model_copy(update={"findings": findings}),
        "evidence": {
            key: item for key, item in snapshot.evidence.items() if item.kind != "channel_summary"
        },
    })
    reviews = InstrumentReviews()
    assert reviews.due(snapshot, network.pack) == "automatic_instrument_context"
    reviews.reviewed(snapshot, network.pack)
    assert reviews.due(snapshot.model_copy(update={"end_seconds": 265}), network.pack) is None
    assert reviews.due(
        snapshot.model_copy(update={"end_seconds": 270}), network.pack,
    ) == "periodic_instrument_review"


def test_quality_only_reports_are_scored_as_required_reviews_not_no_agent_controls() -> None:
    row = {
        "case_id": "quality-only", "status": "completed", "root_count": 1, "accepted_report": True,
        "truth": {
            "leak_source": None, "instrumentation_concern": True,
            "pressure_trigger": False, "review_required": True,
            "pressure_anomaly_sensors": [], "missing_value_sensors": ["bad", "gap"],
            "sensor_issues": [
                {"sensor_id": "bad", "kind": "invalid"}, {"sensor_id": "gap", "kind": "missing"},
            ],
        },
        "extraction": {"mapping": {
            "leaks": [], "instrumentation_concern": True,
            "sensor_issues": [
                {"sensor_id": "bad", "kind": "invalid", "assertion": "suspected"},
                {"sensor_id": "gap", "kind": "missing", "assertion": "suspected"},
            ],
        }},
    }
    metrics = spatial_metrics({"cases": [row], "planned_cases": 1})
    assert metrics["groups"]["agent_sensor_concerns"]["tp"] == 1
    assert metrics["groups"]["agent_issue_types"]["tp"] == 2
    assert metrics["rates"]["accepted_report_coverage"]["value"] == 1
    assert metrics["rates"]["no_pressure_no_agent"]["denominator"] == 0
    row.update(status="failed", accepted_report=False, extraction=None)
    failed = spatial_metrics({"cases": [row], "planned_cases": 1})
    assert failed["groups"]["agent_sensor_concerns"]["fn"] == 1
    assert failed["rates"]["accepted_report_coverage"]["value"] == 0


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


@pytest.mark.parametrize("case_index", [0, 1, 2])
@pytest.mark.parametrize("seed", [20261109, 20261110])
def test_first_pressure_review_uses_arrived_data_and_does_not_wait_for_location(
    case_index: int, seed: int,
) -> None:
    data = spatial_dataset(spatial_cases()[case_index], seed, "northsea")
    baseline = normalize_records(data.baseline, data.pack)
    first_alert = None
    ready = []
    for end in range(90, 116, data.pack.hop_seconds):
        snapshot = analyze_window(
            data.pack, baseline, normalize_records(arrived_records(data, end + 5), data.pack),
            generation_id="causal-onset", end_seconds=end, clock_seconds=end + 5,
            epoch=data.epoch,
        )
        if any(finding.anomaly_count for finding in snapshot.quality.findings):
            first_alert = first_alert if first_alert is not None else end
        if first_alert is not None and pressure_context_ready(snapshot, data.pack, first_alert):
            ready.append(end)
    assert first_alert == 95
    assert ready[0] == 110
    if case_index == 2:
        assert snapshot.event.hypothesis != "suspected_leak"
        assert not snapshot.location or snapshot.location.status != "located"


def test_timing_distinguishes_onset_alert_admission_and_correct_branch_model_time() -> None:
    source = {"segment_id": "P6", "chainage_m": 1000, "start_seconds": 90}
    frames = [
        {"source_seconds": end, "truth": {"leak_source": source},
         "review_case_id": f"N2@{end}", "snapshot_id": f"snapshot-{end}",
         "input_hash": f"input-{end}",
         "detector": {"pressure_anomaly_sensors": sensors}}
        for end, sensors in [
            (95, ["P7-ST1-A"]), (100, ["P6-ST5-A"]), (110, ["P6-ST5-A"]), (150, ["P6-ST5-A"]),
        ]
    ]
    rows = [
        {"case_id": "N2@110", "network_id": "N2", "source_seconds": 110, "root_count": 1,
         "snapshot_id": "snapshot-110", "input_hash": "input-110",
         "root_id": "root-110", "agent_started_at": "2026-01-01T00:00:00+00:00",
         "agent_tasks": [{
             "role": "event_diagnosis", "state": "SUCCEEDED", "root_id": "root-110",
             "snapshot_id": "snapshot-110", "checked_finding": {
                 "hypothesis": "suspected_leak", "segment_ids": ["P6"],
                 "snapshot_id": "snapshot-110", "input_hash": "input-110",
                 "available_at": "2026-01-01T00:00:35+00:00",
                 "final_report": False,
             },
         }],
         "accepted_report": True, "agent_elapsed_seconds": 400,
         "extraction": {"status": "completed", "mapping": {"leaks": [{"segment_id": "P7"}]}}},
        {"case_id": "N2@150", "network_id": "N2", "source_seconds": 150, "root_count": 1,
         "snapshot_id": "snapshot-150", "input_hash": "input-150",
         "accepted_report": True, "agent_elapsed_seconds": 420,
         "extraction": {"status": "completed", "mapping": {"leaks": [{"segment_id": "P6"}]}}},
    ]
    report = {"networks": [{"id": "N2", "frames": frames}], "cases": rows}
    result = spatial_timing(report)[0]
    assert result["source_onset_seconds"] == 90
    assert result["first_branch_alert_seconds"] == 100
    assert result["first_agent_admission_seconds"] == 110
    assert result["admission_delay_source_seconds"] == 20
    assert result["first_correct_branch_review_seconds"] == 150
    assert result["correct_branch_delay_source_seconds"] == 60
    assert result["correct_branch_model_wall_seconds"] == 420
    assert result["first_checked_warning_source_seconds"] == 110
    assert result["first_checked_warning_model_wall_seconds"] == 35
    rows[0]["agent_tasks"][0]["checked_finding"]["input_hash"] = "different-input"
    assert spatial_timing(report)[0]["first_checked_warning_source_seconds"] is None
    rows[0]["agent_tasks"][0]["checked_finding"]["input_hash"] = "input-110"
    rows[1]["snapshot_id"] = "different-snapshot"
    assert spatial_timing(report)[0]["first_correct_branch_review_seconds"] is None
    rows[1]["snapshot_id"] = "snapshot-150"
    rows[1]["accepted_report"] = False
    result = spatial_timing(report)[0]
    assert result["first_correct_branch_review_seconds"] is None
    assert result["correct_branch_model_wall_seconds"] is None


def test_only_a_succeeded_checked_diagnosis_releases_a_preliminary_warning(
    network: ReplayDataset,
) -> None:
    snapshot = analyze_window(
        network.pack, normalize_records(network.baseline, network.pack),
        normalize_records(network.records, network.pack),
        generation_id="early-warning", end_seconds=110, clock_seconds=115,
        epoch=network.epoch,
    )
    task = AgentTask(
        id="diagnosis", root_id="root", parent_id="root",
        generation_id=snapshot.generation_id, snapshot_id=snapshot.id,
        role="event_diagnosis", site_id=snapshot.site_id, mode="scripted",
        state="SUCCEEDED", purpose=REGISTRY["event_diagnosis"].purpose,
        question="Leak or instrumentation?", deadline=utc_now() + timedelta(seconds=300),
        result=AgentResult(
            outcome="supported", hypothesis="suspected_leak", limitations=[],
            claim_refs=[
                claim.id for claim in snapshot.claims.values() if claim.kind == "hypothesis"
            ],
        ),
    )
    store = Mock()
    store.get_task.return_value = task
    store.get_window.return_value = snapshot
    finding = public_task(store, {"id": task.id})["checked_finding"]
    assert finding["segment_ids"] == ["P5"]
    assert finding["snapshot_id"] == snapshot.id
    assert finding["input_hash"] == snapshot.input_hash
    assert finding["final_report"] is False
    for state in ["RUNNING", "FAILED", "ABSTAINED"]:
        store.get_task.return_value = task.model_copy(update={"state": state})
        assert public_task(store, {"id": task.id})["checked_finding"] is None


def test_isolated_evaluation_starts_all_networks_without_overwriting_an_active_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any,
) -> None:
    import threading
    from types import SimpleNamespace

    from subsea_copilot import spatial_evaluation as evaluation

    settings = SimpleNamespace(
        runtime_dir=tmp_path, site_id="northsea",
        database_dsn="fixture", tools_dsn="fixture", checkpoint_dsn="fixture",
    )
    monkeypatch.setenv("SUBSEA_TRACE_CONTENT", "1")
    monkeypatch.setenv("SUBSEA_SYNTHETIC_ONLY", "1")
    monkeypatch.setattr(evaluation.Settings, "from_env", lambda: settings)
    monkeypatch.setattr(evaluation, "read_evaluation", lambda: {"status": "running"})
    monkeypatch.setattr(evaluation, "Telemetry", lambda **kwargs: None)
    monkeypatch.setattr(
        evaluation, "qualification_model_factory", lambda *args: lambda *args: None,
    )
    monkeypatch.setattr(evaluation, "mapping_controls", lambda: [])
    monkeypatch.setattr(evaluation, "calibration_packets", lambda *args: [])

    def forbidden_publication(*args: Any) -> None:
        pytest.fail("An isolated run must not overwrite the active dashboard evaluation")

    monkeypatch.setattr(evaluation, "publish_evaluation", forbidden_publication)
    barrier = threading.Barrier(3)
    lock = threading.Lock()
    active = maximum = 0

    class ConcurrentStore:
        def __init__(self, *args: Any, **kwargs: Any):
            pass

        def __exit__(self, *args: Any) -> None:
            pass

        def __enter__(self):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            try:
                barrier.wait(timeout=5)
            finally:
                with lock:
                    active -= 1
            raise RuntimeError("Intentional fixture failure after concurrent admission")

    monkeypatch.setattr(evaluation, "Store", ConcurrentStore)
    report = evaluation.run_spatial_evaluation(
        tmp_path / "isolated", seed=20261121, split="held_out", publish=False,
    )
    assert maximum == 3
    assert report["status"] == "incomplete"
    assert all(network["status"] == "failed" for network in report["networks"])


@pytest.mark.integration
@pytest.mark.parametrize("duration,suite", [(120, "current"), (240, "current"), (240, "recovery")])
def test_spatial_runner_records_an_early_root_before_the_fixed_checkpoint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, duration: int, suite: str,
) -> None:
    import json
    import os
    from contextlib import nullcontext
    from dataclasses import replace

    from langgraph.checkpoint.memory import InMemorySaver

    from subsea_copilot import spatial_evaluation as evaluation
    from subsea_copilot.config import Settings
    from subsea_copilot.runtime.scripted import ScriptedChatModel

    if not os.environ.get("SUBSEA_DB_APP_PASSWORD"):
        pytest.skip("Load the independently bootstrapped PostgreSQL environment")
    monkeypatch.setenv("SUBSEA_TRACE_CONTENT", "1")
    monkeypatch.setenv("SUBSEA_SYNTHETIC_ONLY", "1")
    monkeypatch.setenv("SUBSEA_TELEMETRY_ENABLED", "0")
    settings = replace(Settings.from_env(), runtime_dir=tmp_path)
    monkeypatch.setattr(evaluation.Settings, "from_env", lambda: settings)
    monkeypatch.setattr(evaluation, "read_evaluation", lambda: {"status": "not_run"})
    monkeypatch.setattr(evaluation, "PUBLIC_REPORT", tmp_path / "public.json")
    monkeypatch.setattr(evaluation, "DURATION_SECONDS", duration)
    monkeypatch.setattr(evaluation, "CHECKPOINTS", (120,) if duration == 120 else (150, 240))
    monkeypatch.setattr(evaluation, "spatial_cases", lambda: [spatial_cases()[1]])
    monkeypatch.setattr(
        evaluation, "temporal_cases", lambda _suite: [temporal_cases("recovery")[0]],
    )
    monkeypatch.setattr(evaluation, "mapping_controls", lambda: [])
    monkeypatch.setattr(evaluation, "calibration_packets", lambda *_args: [])
    monkeypatch.setattr(
        evaluation, "postgres_checkpointer", lambda _dsn: nullcontext(InMemorySaver()),
    )
    monkeypatch.setattr(
        evaluation, "qualification_model_factory",
        lambda *_args: lambda role, _mode: ScriptedChatModel(role=role),
    )
    monkeypatch.setattr(
        evaluation, "install_golden_input",
        lambda monitor, dataset, _mode, **kwargs: install_golden_input(
            monitor, dataset, "scripted", **kwargs,
        ),
    )
    held_stages = []

    def assert_source_held(stage: str) -> None:
        published = json.loads((tmp_path / "public.json").read_text())
        if suite != "current":
            published = published["additional_evaluations"][0]
        network = published["networks"][0]
        held = network["held_source_seconds"]
        assert network["frames"][-1]["source_seconds"] == held
        row = next(item for item in published["cases"] if item["source_seconds"] == held)
        assert row["snapshot_id"] == network["frames"][-1]["snapshot_id"]
        assert row["status"] not in {"completed", "failed"}
        held_stages.append((stage, held))

    def mapping(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        assert_source_held("mapping")
        return {
            "status": "completed",
            "mapping": {"leaks": [], "sensor_issues": [], "instrumentation_concern": False},
        }

    def judge(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        assert_source_held("judge")
        return {"status": "completed", "passed": True}

    monkeypatch.setattr(evaluation, "run_mapping", mapping)
    monkeypatch.setattr(evaluation, "run_judge", judge)
    report = evaluation.run_spatial_evaluation(
        tmp_path / "recording", seed=20261110, split="held_out",
        suite=suite,
    )
    early = next(row for row in report["cases"] if row["source_seconds"] == 95)
    assert early["root_count"] == 1
    assert early["admission_kind"] == "automatic_pressure_context"
    assert report["planned_cases"] == len(report["cases"])
    if suite == "current":
        assert report["planned_cases"] == (3 if duration == 120 else 5)
    frames = report["networks"][0]["frames"]
    assert [frame["source_seconds"] for frame in frames] == list(range(60, duration + 1, 5))
    frame = next(frame for frame in frames if frame["source_seconds"] == 95)
    assert (frame["review_case_id"], frame["snapshot_id"], frame["input_hash"]) == (
        early["case_id"], early["snapshot_id"], early["input_hash"],
    )
    assert report["metrics"]["timing"][0]["first_agent_admission_seconds"] == 95
    assert ("mapping", 95) in held_stages and ("judge", 95) in held_stages
    assert early["investigation_elapsed_seconds"] >= early["agent_elapsed_seconds"]
    assert early["result_admitted_at"]
    assert report["networks"][0]["held_source_seconds"] is None
    if duration == 240 and suite == "current":
        followup = next(row for row in report["cases"] if row["source_seconds"] == 210)
        assert followup["root_count"] == 1
        assert followup["admission_kind"] == "automatic_instrument_context"
        assert "P4-ST8-A" in followup["instrument_review_sensors"]
        assert ("mapping", 210) in held_stages and ("judge", 210) in held_stages
    if suite == "recovery":
        reassessment = next(row for row in report["cases"] if row["source_seconds"] == 240)
        assert reassessment["force_review"]
        assert reassessment["truth"]["review_required"]
        assert reassessment["root_count"] == 1
        assert reassessment["agent_audit"]["checks"]
        assert report["agent_process"]["attempted_reviews"] > 0
        assert report["metrics"]["temporal"]["episodes"][0]["stop_seconds"] == 180


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

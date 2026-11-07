"""Pure golden/judge qualification checks: no hosted inference, database or temp files."""

import json
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from subsea_copilot.cli import main
from subsea_copilot.contracts import ReplaySession, content_hash
from subsea_copilot.diagnostics import analyze_window
from subsea_copilot.golden_data import dataset_hash, generate_golden, load_cases, measured_manifest
from subsea_copilot.golden_evaluation import (
    deterministic_golden_checks,
    grounded_case_evidence,
    install_golden_input,
    operator_accuracy_receipt,
)
from subsea_copilot.golden_evidence import content_evidence
from subsea_copilot.golden_judge import (
    DIMENSIONS,
    JUDGE_TRACE_LIMIT,
    JudgeVerdict,
    calibration_packets,
    judge_messages,
    judge_passed,
    run_judge,
)
from subsea_copilot.ingest import normalize_records
from subsea_copilot.monitoring import Monitor
from subsea_copilot.replay_sources import (
    FROZEN_PREFIX,
    freeze_replay_source,
    load_frozen_replay_source,
)
from subsea_copilot.synthetic import generate_pack


@pytest.fixture(scope="module")
def golden():
    corpus = load_cases()
    rows = {}
    for case in corpus["cases"]:
        data = generate_golden(case, corpus["seed"], corpus["duration_seconds"])
        snapshot = analyze_window(
            data.pack, normalize_records(data.baseline, data.pack),
            normalize_records(data.records, data.pack), "test-input", 60, 65, data.epoch,
        )
        rows[case["id"]] = (case, data, snapshot)
    return rows


@pytest.mark.parametrize("case_id", ["G1", "G2", "G3", "G4"])
def test_golden_labels_are_verified_from_actual_normalized_measurements(golden, case_id):
    case, data, snapshot = golden[case_id]
    manifest = measured_manifest(case, data)
    assert manifest["fixture_verified"]
    assert snapshot.event.hypothesis == case["expected"]["hypothesis"]
    assert data.pack == generate_pack()
    if case["source"]:
        assert manifest["source_truth"]["position"]["x"] == 0
        assert manifest["source_truth"]["position"]["y"] == case["source"]["chainage_m"] - 800
        summaries = manifest["first_complete_window"]["pressure_summaries"]
        assert summaries["P1-ST2-A"]["median_pressure_drop_bar"] > 0.5
        assert summaries["P1-ST1-A"]["median_pressure_drop_bar"] < 0.2
        assert snapshot.event.persistence_seconds == 60
    if case_id in {"G2", "G3"}:
        assert any(f.hard_excluded for f in snapshot.quality.findings)
        assert any(f.missing > 0 for f in snapshot.quality.findings)
        assert any(f.spike_count for f in snapshot.quality.findings)
    if case_id == "G4":
        assert snapshot.quality.coverage == 0
        assert not any(f.anomaly_count for f in snapshot.quality.findings)


def test_recipe_mutation_cannot_become_a_precomputed_passing_label(golden):
    case, data, _ = golden["G1"]
    corrupted = deepcopy(case)
    corrupted["source"] = None
    manifest = measured_manifest(case, generate_golden(corrupted))
    assert not manifest["fixture_verified"]
    assert not manifest["deterministic_fixture_checks"]["class"]
    assert dataset_hash(data) == dataset_hash(generate_golden(case))
    assert dataset_hash(data) != manifest["dataset_sha256"]


def test_runtime_source_adapter_does_not_include_hidden_truth_or_case_identity(golden):
    case, data, _ = golden["G3"]
    store = MagicMock()
    store.tenant_id = "unit-golden"
    store.create_replay.side_effect = lambda replay: replay
    monitor = SimpleNamespace(store=store, _sources={})
    replay = install_golden_input(monitor, data, "scripted")
    assert replay.scenario == FROZEN_PREFIX + dataset_hash(data)
    assert replay.pause_on_anomaly
    source = monitor._sources[replay.id]
    runtime = json.dumps({
        "replay": replay.model_dump(mode="json"),
        "records": [r.model_dump(mode="json") for r in source.dataset.records],
        "pack": source.dataset.pack.model_dump(mode="json"),
    })
    assert case["name"] not in runtime
    assert "source_truth" not in runtime
    assert "expected" not in runtime
    assert "chainage_m\": 425" not in runtime
    assert case["id"] not in runtime
    store.save_observations.assert_not_called()


@pytest.mark.parametrize("case_id", ["G1", "G2", "G3", "G4"])
def test_production_first_complete_window_pauses_only_for_pressure(golden, case_id):
    case, data, snapshot = golden[case_id]
    store = MagicMock()
    replay = ReplaySession(
        id="unit-replay", scenario="golden-input", source_version="pressure-v3",
        pause_on_anomaly=True, workflow="agent_assisted", epoch=data.epoch,
    )
    store.get_replay.return_value = replay
    store.save_replay.side_effect = lambda value, **_kwargs: value
    monitor = Monitor(store, MagicMock(), MagicMock())
    assert (
        monitor._pause_for_investigation(replay, snapshot) == case["expected"]["pressure_trigger"]
    )
    saved = store.save_replay.call_args.args[0]
    assert bool(saved.investigation_window_id) == case["expected"]["pressure_trigger"]
    if case_id == "G4":
        monitor._episode(replay, snapshot)
        monitor.agents.submit_question.assert_not_called()
        monitor.agents.health.assert_not_called()


def test_missing_only_grading_requires_absence_of_agent_and_pause(golden):
    case, _, snapshot = golden["G4"]
    checks = deterministic_golden_checks(
        case["expected"], snapshot, None, paused=False, root_count=0,
    )
    assert all(checks.values())
    wrong = deterministic_golden_checks(
        case["expected"], snapshot, None, paused=True, root_count=1,
    )
    assert not wrong["no_pause_for_missing_only"]
    assert not wrong["no_agent_for_missing_only"]


def test_immature_window_does_not_silently_override_production_gate(golden):
    _, data, _ = golden["G1"]
    snapshot = analyze_window(
        data.pack, normalize_records(data.baseline, data.pack),
        normalize_records(data.records, data.pack), "test-input", 55, 60, data.epoch,
    )
    assert snapshot.quality.status == "WARMING_UP"
    monitor = Monitor(MagicMock(), MagicMock(), MagicMock())
    replay = ReplaySession(
        id="unit", scenario="golden-input", pause_on_anomaly=True,
    )
    assert not monitor._pause_for_investigation(replay, snapshot)
    monitor.store.save_replay.assert_not_called()


def test_explained_abstention_is_accepted_but_not_a_leak_classification_pass(golden):
    case, _, snapshot = golden["G1"]
    audit = {
        "report": {
            "completed": True, "physical_decision": "insufficient_evidence",
            "inspection": None, "limitations": ["SYNTHETIC_UNCALIBRATED"],
        },
        "checks": {
            "persisted_results_revalidated": True, "model_receipt_accounting": True,
            "tool_receipt_accounting": True,
        },
    }
    checks = deterministic_golden_checks(
        case["expected"], snapshot, audit, paused=True, root_count=1, state="ABSTAINED",
    )
    assert checks["accepted_report_not_provider_failure"]
    assert checks["class_or_explained_abstention"]
    assert not checks["model_leak_interpretation_not_abstention"]
    audit["report"]["limitations"] = []
    assert not deterministic_golden_checks(
        case["expected"], snapshot, audit, paused=True, root_count=1, state="ABSTAINED",
    )["class_or_explained_abstention"]


def test_failed_provider_and_exact_point_never_pass_deterministic_grading(golden):
    case, _, snapshot = golden["G1"]
    audit = {
        "report": {
            "completed": False, "physical_decision": "suspected_leak",
            "inspection": {"segment_id": "P1", "start_m": 400, "end_m": 400},
        },
        "checks": {"persisted_results_revalidated": False},
    }
    checks = deterministic_golden_checks(
        case["expected"], snapshot, audit, paused=True, root_count=1, state="FAILED",
    )
    assert not checks["accepted_report_not_provider_failure"]
    assert not checks["bounded_location_or_withholding"]


def verdict(score=2, reference="candidate_report.answer"):
    return {
        "rubric_version": "golden-pressure-judge-v1",
        "dimensions": {
            name: {
                "score": score, "reason": "Assessment grounded in the supplied case evidence.",
                "evidence_references": [reference],
            } for name in DIMENSIONS
        },
        "summary": "Independent opinion on supplied synthetic report evidence.",
    }


def test_versioned_judge_schema_does_not_accept_missing_dimensions_or_boolean_scores():
    assert judge_passed(JudgeVerdict.model_validate(verdict()))
    partial = verdict()
    partial["dimensions"]["novice_comprehensibility"]["score"] = 1
    assert judge_passed(JudgeVerdict.model_validate(partial))
    partial["dimensions"]["location_bounds"]["score"] = 1
    assert not judge_passed(JudgeVerdict.model_validate(partial))
    del partial["dimensions"]["references"]
    with pytest.raises(ValidationError):
        JudgeVerdict.model_validate(partial)
    boolean = verdict()
    boolean["dimensions"]["references"]["score"] = True
    with pytest.raises(ValidationError):
        JudgeVerdict.model_validate(boolean)


def test_judge_really_invokes_injected_transport_and_records_opinion_separately(golden):
    case, _, snapshot = golden["G1"]
    evidence = grounded_case_evidence(snapshot, {"report": {}})
    control = calibration_packets(evidence, case["expected"])[0]
    model = MagicMock()
    model.invoke.return_value = AIMessage(
        content=json.dumps(verdict()),
        response_metadata={"mode": "live", "observed_model": "test-hosted-model"},
    )
    telemetry = MagicMock()
    telemetry.trace_metadata.return_value = {"trace_id": "1" * 32, "span_id": "2" * 16}
    result = run_judge(
        model, control["packet"], telemetry,
        identity="unit", tenant_id="unit", generation_id="unit",
    )
    assert result["status"] == "completed"
    assert result["passed"]
    assert result["model_calls"] == 1
    model.invoke.assert_called_once()
    assert model.invoke.call_args.kwargs["timeout"] == 60
    assert result["trace"]["trace_id"] == "1" * 32
    assert result["model_receipt"]["observed_model"] == "test-hosted-model"
    assert "deterministic_checks" not in result
    messages = model.invoke.call_args.args[0]
    assert "hidden_expected_outcomes" in messages[1].content
    assert "EXTERNAL evaluation judge" in messages[0].content
    assert sum(len(str(message.content)) for message in messages) < 48000
    captured = next(
        call.args[1] for call in telemetry.span.return_value.__enter__.return_value
        .set_attribute.call_args_list if call.args[0] == "langfuse.observation.input"
    )
    assert json.loads(captured)["case_packet"] == json.loads(messages[1].content)


@pytest.mark.parametrize("failure", ["provider", "malformed", "non_live", "invented_reference"])
def test_judge_failure_never_counts_as_passing_evidence(failure):
    model = MagicMock()
    if failure == "provider":
        model.invoke.side_effect = RuntimeError("do not expose transport contents")
    else:
        model.invoke.return_value = AIMessage(
            content="not JSON" if failure == "malformed" else json.dumps(
                verdict(reference="secret-fabricated-reference")
                if failure == "invented_reference" else verdict()
            ),
            response_metadata={
                "mode": "scripted" if failure == "non_live" else "live",
                "observed_model": "test-hosted-model",
            },
        )
    result = run_judge(
        model, {"case_evidence": {"event": {}}}, MagicMock(),
        identity="unit", tenant_id="unit", generation_id="unit",
    )
    assert result["status"] == "failed"
    assert result["passed"] is False
    assert result["verdict"] is None
    assert "do not expose" not in json.dumps(result, default=str)


def test_owned_hosted_transport_supplies_mode_identity_when_wire_metadata_omits_it(monkeypatch):
    from subsea_copilot.llm.copilot_cli import CopilotCLIChatModel

    response = AIMessage(
        content=json.dumps(verdict()),
        response_metadata={"observed_model": "gpt-6.1-sol", "model_identity_source": "cli_event"},
    )
    invocation = MagicMock(return_value=response)
    monkeypatch.setattr(CopilotCLIChatModel, "invoke", invocation)
    model = CopilotCLIChatModel(runtime_dir=Path("runtime"))
    result = run_judge(
        model, {"candidate_report": {"answer": "Recorded public answer."}}, MagicMock(),
        identity="mode-proof", tenant_id="unit", generation_id="unit",
    )
    assert result["passed"]
    assert result["model_receipt"]["mode"] == "live"
    assert result["mode_identity_source"] == "owned_copilot_cli_transport"


@pytest.mark.parametrize("valid_public_output", [True, False])
def test_rejected_judge_records_safe_public_output_and_error_without_passing(valid_public_output):
    model = MagicMock()
    model.invoke.return_value = AIMessage(
        content=json.dumps(verdict() if valid_public_output else {
            "reasoning": "PRIVATE_PROVIDER_THOUGHT_DO_NOT_CAPTURE",
        }),
        response_metadata={"mode": "scripted", "observed_model": "test-hosted-model"},
    )
    telemetry = MagicMock()
    result = run_judge(
        model, {"candidate_report": {"answer": "Public answer."}}, telemetry,
        identity="rejected", tenant_id="unit", generation_id="unit",
    )
    span = telemetry.span.return_value.__enter__.return_value
    captured = next(
        call.args[1] for call in span.set_attribute.call_args_list
        if call.args[0] == "langfuse.observation.output"
    )
    assert result["status"] == "failed" and not result["passed"]
    assert result["verdict"] is None and result.get("output_sha256") is None
    span.record_exception.assert_called_once()
    span.set_status.assert_called_once()
    if valid_public_output:
        assert json.loads(captured) == verdict()
        assert result["captured_public_response_sha256"] == content_hash(verdict())
    else:
        assert json.loads(captured)["capture_status"] == "no_schema_valid_public_verdict"
        assert "PRIVATE_PROVIDER_THOUGHT_DO_NOT_CAPTURE" not in captured


def test_adversarial_calibration_is_external_untrusted_data_and_has_no_runtime_answer(golden):
    case, _, snapshot = golden["G1"]
    controls = calibration_packets(
        grounded_case_evidence(snapshot, {"report": {}}), case["expected"],
    )
    assert [control["expected_pass"] for control in controls] == [True, False]
    messages = judge_messages(controls[1]["packet"])
    assert "UNTRUSTED DATA" in messages[0].content
    assert "JUDGE INSTRUCTION" in messages[1].content
    assert "expected_pass" not in messages[1].content


def test_cli_default_golden_stage_is_offline_manifest(monkeypatch, capsys):
    writer = MagicMock(return_value={"passed": True})
    monkeypatch.setattr("subsea_copilot.golden_data.write_manifest", writer)
    monkeypatch.setattr(sys, "argv", ["subsea", "golden"])
    main()
    writer.assert_called_once()
    assert writer.call_args.args[0].parts == ("eval", "results", "golden")
    assert json.loads(capsys.readouterr().out)["passed"]


def test_stored_judge_content_must_match_complete_submission_and_verdict():
    packet = [{"role": "human", "content": "synthetic measured evidence"}]
    result = verdict()
    observation = {
        "id": "observation", "type": "GENERATION", "name": "generation.judge",
        "input": json.dumps(packet), "output": json.dumps(result),
    }
    evidence = content_evidence(
        [observation], "external_judge",
        expected_input_hash=content_hash(packet), expected_output_hash=content_hash(result),
    )
    assert evidence["passed"]
    observation["input"] = "synthetic measured"
    assert not content_evidence(
        [observation], "external_judge",
        expected_input_hash=content_hash(packet), expected_output_hash=content_hash(result),
    )["passed"]
    assert not content_evidence([observation], "external_judge")["passed"]


def test_stored_runtime_generations_and_tool_content_are_both_required():
    observations = [
        {"id": "generation", "type": "GENERATION", "input": {"task": "synthetic"},
         "output": {"answer": "public checked finding"}},
        {"id": "tool", "type": "TOOL", "input": {"sensor_id": "P1-ST2-A"},
         "output": {"pressure_bar": 78.4}},
    ]
    assert content_evidence(observations, "runtime_agent")["passed"]
    observations[1]["output"] = None
    assert not content_evidence(observations, "runtime_agent")["passed"]
    assert not content_evidence(observations[:1], "runtime_agent")["passed"]


@pytest.mark.parametrize("case_id", ["G1", "G2", "G3", "G4"])
def test_frozen_measurement_source_reopens_without_regeneration(golden, case_id):
    _, data, _ = golden[case_id]
    scenario = freeze_replay_source(data)
    session = ReplaySession(
        id="reopen", scenario=scenario, source_version="pressure-v3",
        site_id=data.pack.id, epoch=data.epoch,
    )
    reopened = load_frozen_replay_source(session)
    assert reopened == data
    assert dataset_hash(reopened) == scenario.removeprefix(FROZEN_PREFIX)
    assert load_frozen_replay_source(session.model_copy(update={"scenario": "S1"})) is None


def test_frozen_measurement_corruption_does_not_fall_back_to_generator(golden, monkeypatch):
    _, data, _ = golden["G1"]
    directory = MagicMock()
    directory.__truediv__.return_value.read_text.return_value = '{"records":[]}'
    monkeypatch.setattr("subsea_copilot.replay_sources.FROZEN_SOURCE_DIR", directory)
    session = ReplaySession(
        id="corrupt", scenario=FROZEN_PREFIX + dataset_hash(data),
        site_id=data.pack.id, epoch=data.epoch,
    )
    with pytest.raises(ValueError, match="changed after qualification"):
        load_frozen_replay_source(session)


def test_oversize_judge_packet_is_rejected_before_hosted_call():
    model = MagicMock()
    result = run_judge(
        model, {"candidate_report": {"answer": "x" * JUDGE_TRACE_LIMIT}}, MagicMock(),
        identity="oversize", tenant_id="unit", generation_id="unit",
    )
    assert not result["passed"]
    assert result["model_calls"] == 0
    assert result["error_code"] == "judge_evidence_exceeds_trace_bound"
    model.invoke.assert_not_called()


def test_public_judge_schema_has_no_reasoning_keys_and_bounded_output():
    schema = JudgeVerdict.model_json_schema()
    assert '"reasoning"' not in json.dumps(schema)
    maximum = verdict()
    for score in maximum["dimensions"].values():
        score["reason"] = "\\" * 900
        score["evidence_references"] = ["r" * 180] * 8
    maximum["summary"] = "\\" * 1000
    assert len(JudgeVerdict.model_validate(maximum).model_dump_json()) < JUDGE_TRACE_LIMIT


def test_columnar_judge_quality_preserves_material_counts_and_exclusions(golden):
    _, _, snapshot = golden["G3"]
    packed = grounded_case_evidence(snapshot, {"report": {}})
    quality = packed["quality"]
    restored = [
        dict(zip(quality["finding_columns"], row, strict=True))
        for row in quality["finding_rows"]
    ]
    assert len(restored) == len(snapshot.quality.findings)
    for row, original in zip(restored, snapshot.quality.findings, strict=True):
        assert row["sensor_id"] == original.sensor_id
        assert row["usable"] == original.usable
        assert row["missing"] == original.missing
        assert row["hard_excluded"] == original.hard_excluded
        assert row["anomaly_count"] == original.anomaly_count
        assert row["persistence_seconds"] == original.persistence_seconds
    assert packed["location"]["inspection_start_m"] == 200
    assert packed["location"]["inspection_end_m"] == 600


@pytest.mark.parametrize("case_id", ["G1", "G2", "G3", "G4"])
def test_normal_monitor_reopens_identical_frozen_snapshot_without_new_inference(
    golden, case_id, monkeypatch,
):
    _, data, original = golden[case_id]
    session = ReplaySession(
        id=original.generation_id, scenario=freeze_replay_source(data),
        source_version="pressure-v3", site_id=data.pack.id, epoch=data.epoch,
        duration_seconds=120, clock_seconds=65,
    )
    forbidden = MagicMock(side_effect=AssertionError("Frozen sources must not regenerate"))
    monkeypatch.setattr("subsea_copilot.monitoring.generate_scenario", forbidden)
    monitor = Monitor(MagicMock(), MagicMock(), MagicMock())
    source = monitor._source(session)
    monitor._release(session, source)
    reopened = monitor._snapshot(session, source, 60)
    assert source.dataset == data
    assert reopened.input_hash == original.input_hash
    assert reopened.evidence == original.evidence
    assert reopened.event == original.event
    assert reopened.location == original.location
    monitor.agents.submit_question.assert_not_called()
    monitor.agents.run_once.assert_not_called()
    forbidden.assert_not_called()


def test_normal_monitor_corrupt_frozen_source_never_regenerates(golden, monkeypatch):
    _, data, _ = golden["G1"]
    directory = MagicMock()
    directory.__truediv__.return_value.read_text.return_value = '{"records":[]}'
    monkeypatch.setattr("subsea_copilot.replay_sources.FROZEN_SOURCE_DIR", directory)
    forbidden = MagicMock(side_effect=AssertionError("Never fall back for a corrupt source"))
    monkeypatch.setattr("subsea_copilot.monitoring.generate_scenario", forbidden)
    session = ReplaySession(
        id="corrupt-monitor", scenario=FROZEN_PREFIX + dataset_hash(data),
        source_version="pressure-v3", site_id=data.pack.id, epoch=data.epoch,
    )
    monitor = Monitor(MagicMock(), MagicMock(), MagicMock())
    with pytest.raises(ValueError, match="changed after qualification"):
        monitor._source(session)
    forbidden.assert_not_called()
    monitor.agents.submit_question.assert_not_called()


def test_normal_monitor_retains_original_scenario_generator(golden, monkeypatch):
    _, data, _ = golden["G1"]
    generator = MagicMock(return_value=data)
    monkeypatch.setattr("subsea_copilot.monitoring.generate_scenario", generator)
    session = ReplaySession(
        id="ordinary", scenario="S1", source_version="pressure-v3", seed=2026,
        duration_seconds=360, site_id=data.pack.id, epoch=data.epoch,
    )
    monitor = Monitor(MagicMock(), MagicMock(), MagicMock())
    assert monitor._source(session).dataset == data
    generator.assert_called_once_with("S1", 2026, 360, data.pack.id)


@pytest.mark.parametrize(
    ("state", "stance", "expected_pass"),
    [("ABSTAINED", "possible", False), ("SUCCEEDED", "not_established", False),
     ("SUCCEEDED", "possible", True)],
)
def test_operator_accuracy_does_not_substitute_numeric_leak_eligibility(
    state, stance, expected_pass,
):
    expected = {
        "hypothesis": "suspected_leak",
        "inspection": {"segment_id": "P1", "start_m": 200, "end_m": 600},
    }
    row = {
        "root_ids": ["root"], "snapshot_id": "snapshot", "state": state,
        "agent": {
            "report": {
                "completed": True, "physical_decision": "suspected_leak",
                "inspection": expected["inspection"], "answer": "Published model interpretation.",
                "interpretation": {
                    "competing_causes": [{"cause": "leak", "stance": stance}],
                },
            },
            "checks": {"persisted_results_revalidated": True},
        },
        "external_judge": {
            "verdict": {"dimensions": {"class_and_uncertainty": {"score": 2}}},
        },
    }
    file = {
        "task_id": "root", "snapshot_id": "snapshot", "inspection": expected["inspection"],
    }
    receipt = operator_accuracy_receipt(expected, row, file)
    assert receipt["grounding_acceptance"]
    assert receipt["synthetic_truth_operator_classification_passed"] is expected_pass
    assert receipt["displayed_inspection_matches_golden_interval"]
    file["task_id"] = "different-root"
    assert not operator_accuracy_receipt(expected, row, file)["matching_accepted_casefile"]


def test_runtime_stored_input_rejects_nested_hidden_truth():
    observations = [
        {"type": "GENERATION", "input": {"messages": [
            {"content": json.dumps({"source_truth": {"chainage_m": 425}})},
        ]}, "output": {"answer": "Possible leak."}},
        {"type": "TOOL", "input": {"sensor_id": "P1-ST2-A"}, "output": {"pressure_bar": 78.4}},
    ]
    assert not content_evidence(observations, "runtime_agent")["passed"]
    observations[0]["input"] = {"measurements": {"pressure_bar": 78.4}}
    assert content_evidence(observations, "runtime_agent")["passed"]


@pytest.mark.parametrize("alteration", ["none", "tenant", "hash", "same_root", "abstention"])
def test_recorded_retry_selection_preserves_failure_denominator(alteration):
    from copy import deepcopy

    from subsea_copilot.golden_evaluation import select_recorded_retry

    cases = [
        {
            "case_id": f"G{index}", "root_ids": [f"root-{index}"] if index < 4 else [],
            "state": "FAILED" if index == 3 else "SUCCEEDED",
            "deterministic_passed": index != 3, "input_hash": f"hash-{index}",
            "dataset_sha256": f"data-{index}", "generation_id": f"generation-{index}",
            "external_judge": {"passed": True} if index < 3 else None,
        }
        for index in range(1, 5)
    ]
    previous = {
        "cases": cases, "qualification_tenant_id": "isolated", "site_id": "northsea",
        "model_call_accounting_complete": True, "judge_calibrated": True,
        "model_call_count": {"agent": 25, "external_judge": 8}, "trace_evidence": [],
    }
    fresh = deepcopy(cases[2])
    fresh.update(
        root_ids=["fresh-root"], generation_id="fresh-replay", state="SUCCEEDED",
        deterministic_passed=True,
    )
    retry = {
        "cases": [fresh], "qualification_tenant_id": "isolated", "site_id": "northsea",
        "model_call_accounting_complete": True, "trace_evidence": [],
        "model_call_count": {"agent": 7, "external_judge": 0},
    }
    if alteration == "tenant":
        retry["qualification_tenant_id"] = "main"
    elif alteration == "hash":
        fresh["input_hash"] = "different"
    elif alteration == "same_root":
        fresh["root_ids"] = ["root-3"]
    elif alteration == "abstention":
        fresh["state"] = "ABSTAINED"
    if alteration != "none":
        with pytest.raises(ValueError):
            select_recorded_retry(previous, retry)
        return
    selected = select_recorded_retry(previous, retry)
    assert selected["cases"][2]["root_ids"] == ["fresh-root"]
    assert selected["agent_attempts"][2]["state"] == "FAILED"
    assert not selected["all_agent_attempts_passed"]
    assert selected["substantive_agent_attempt_count"] == 4
    assert selected["failed_agent_attempt_count"] == 1
    assert selected["model_call_count"] == {"agent": 32, "external_judge": 8}
    assert not selected["passed"]
    assert previous["cases"][2]["root_ids"] == ["root-3"]


def test_zero_agent_recording_receipt_never_borrows_a_calibration_trace():
    from subsea_copilot.golden_evaluation import write_recorded_receipts

    output = MagicMock()
    report = {
        "cases": [{
            "case_id": "G4", "generation_id": "missing-only", "root_ids": [],
            "snapshot_id": "snapshot", "input_hash": "hash", "dataset_sha256": "data",
            "state": None, "agent": None,
        }],
        "trace_evidence": [{
            "kind": "external_judge", "trace": {"trace_id": "calibration"},
            "stored_tree_verified": True, "stored_content": {"passed": True},
        }],
        "judge_calibration": [], "passed": True, "run_id": "recorded",
        "qualification_tenant_id": "isolated", "site_id": "northsea",
        "model_call_count": {"agent": 0, "external_judge": 0}, "limitations": [],
    }
    write_recorded_receipts(output, report)
    receipt = json.loads(output.__truediv__.return_value.write_text.call_args.args[0])
    assert receipt["cases"][0]["runtime_root_trace"] is None
    assert receipt["cases"][0]["agent_calls"] == 0
    assert receipt["cases"][0]["judge_trace"] is None


@pytest.mark.parametrize("encoding", ["flat_otel", "nested"])
def test_public_metadata_retains_stored_error_without_credentials(encoding):
    from subsea_copilot.golden_evidence import public_observation_metadata

    values = {
        "error.code": "invalid_judge_output", "observed_model": "test-model",
        "authorization": "DO_NOT_COPY", "credential.model": "DO_NOT_COPY",
    }
    metadata = (
        {"attributes." + key: value for key, value in values.items()}
        if encoding == "flat_otel" else {"attributes": values}
    )
    selected = public_observation_metadata(json.dumps(metadata))
    assert selected == {"error.code": "invalid_judge_output", "observed_model": "test-model"}

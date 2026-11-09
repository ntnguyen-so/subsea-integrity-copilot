from __future__ import annotations

import copy
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage

from subsea_copilot.evaluation_mapping import (
    OutputMapping,
    run_mapping,
    validate_mapping,
)
from subsea_copilot.evaluation_metrics import detection_metrics, score_report
from subsea_copilot.reference_evaluation import (
    reference_cases,
    reference_dataset,
    truth_labels,
)
from subsea_copilot.runtime.agent import model_tool_result
from subsea_copilot.runtime.gateway import ToolGateway
from subsea_copilot.runtime.workflow import AgentService
from subsea_copilot.telemetry import Telemetry
from subsea_copilot.validation import ValidationError


def test_extraction_is_truth_blind_and_rejects_invented_quotes(tmp_path: Any) -> None:
    mapping = {
        "version": "agent-output-mapping-v1",
        "leaks": [],
        "sensor_issues": [
            {
                "sensor_id": "P1-ST1-A",
                "kind": "spike",
                "assertion": "suspected",
                "quote": {"path": "answer.text", "text": "P1-ST1-A has brief spikes."},
            }
        ],
        "instrumentation_concern": True,
        "instrumentation_quote": {
            "path": "answer.text",
            "text": "P1-ST1-A has brief spikes.",
        },
    }
    model = Mock()
    model.invoke.return_value = AIMessage(
        content=json.dumps(mapping),
        response_metadata={"mode": "live", "observed_model": "unit-test-only"},
    )
    catalog = [{"id": "P1-ST1-A", "segment_id": "P1"}]
    result = run_mapping(
        model,
        {"answer": {"text": "P1-ST1-A has brief spikes."}},
        catalog,
        Telemetry(runtime_dir=tmp_path),
        tenant_id="test",
        generation_id="test",
    )
    assert result["status"] == "completed"
    packet = json.loads(model.invoke.call_args.args[0][1].content)
    assert set(packet) == {"public_texts", "sensor_catalog", "quote_choices"}
    assert "ground_truth" not in json.dumps(packet)
    mapping["sensor_issues"][0]["quote"]["text"] = "P1-ST1-A is definitely broken."
    with pytest.raises(ValueError, match="quote_mismatch"):
        validate_mapping(OutputMapping.model_validate(mapping), packet["public_texts"], catalog)


def test_wrong_sensor_or_pipeline_cannot_be_mapped() -> None:
    mapping = OutputMapping.model_validate(
        {
            "version": "agent-output-mapping-v1",
            "leaks": [
                {
                    "segment_id": "P99",
                    "assertion": "suspected",
                    "interval": None,
                    "quote": {"path": "answer.text", "text": "Review pipeline P99."},
                }
            ],
            "sensor_issues": [],
            "instrumentation_concern": False,
            "instrumentation_quote": None,
        }
    )
    with pytest.raises(ValueError, match="unknown_pipeline"):
        validate_mapping(
            mapping,
            {"answer.text": "Review pipeline P99."},
            [{"id": "P1-ST1-A", "segment_id": "P1"}],
        )


def test_failing_report_and_wrong_location_stay_in_denominators() -> None:
    truth = {
        "leak_source": {"segment_id": "P1", "chainage_m": 400},
        "pressure_trigger": True,
        "instrumentation_concern": False,
        "sensor_issues": [],
        "pressure_anomaly_sensors": [],
        "missing_value_sensors": [],
    }
    row = {
        "case_id": "one",
        "status": "completed",
        "truth": truth,
        "accepted_report": True,
        "judge": {"passed": True},
        "extraction": {
            "mapping": {
                "leaks": [
                    {
                        "segment_id": "P3",
                        "assertion": "suspected",
                        "interval": {"start_m": 200, "end_m": 600},
                    }
                ],
                "sensor_issues": [],
                "instrumentation_concern": False,
            }
        },
    }
    failed = copy.deepcopy(row)
    failed.update(
        case_id="two", status="failed", accepted_report=False, extraction=None, judge=None
    )
    report = {"cases": [row, failed], "planned_cases": 2}
    metrics = score_report(report)
    assert metrics["groups"]["leak_recognition"]["recall"]["value"] == 0.5
    assert metrics["groups"]["agent_pipeline_identification"]["recall"]["value"] == 0
    assert metrics["rates"]["localization_containment"]["denominator"] == 2
    assert metrics["rates"]["localization_containment"]["value"] == 0
    assert metrics["rates"]["accepted_report_coverage"]["value"] == 0.5
    assert not metrics["target_met"]


def test_empty_denominators_are_not_perfect_scores() -> None:
    metrics = detection_metrics(set(), set())
    assert metrics["precision"]["value"] is None
    assert metrics["recall"]["value"] is None
    assert metrics["f1"]["value"] is None
    metrics = detection_metrics({"bad"}, {"healthy"})
    assert (metrics["tp"], metrics["fp"], metrics["fn"]) == (0, 1, 1)


def test_new_branch_labels_and_drift_are_declared_from_source_not_predictions() -> None:
    cases = reference_cases()
    assert len(cases) == 8
    sources = {case["source"]["segment_id"] for case in cases if case["source"]}
    assert sources == {"P1", "P2", "P3"}
    drift = cases[-1]
    dataset = reference_dataset(drift, 20261107, "northsea")
    truth = truth_labels(drift, dataset)
    assert {"sensor_id": "P3-ST2-A", "kind": "drift"} in truth["sensor_issues"]
    assert "P3-ST2-B" not in truth["pressure_anomaly_sensors"]
    assert not truth["leak_source"]
    raw = dataset.records[0].model_dump()
    assert not {"truth", "case_id", "leak_source"} & set(raw)


def test_diagnosis_intake_reads_baseline_sources_without_a_model_round_trip() -> None:
    task = Mock(role="event_diagnosis", id="task", history_version="history-v1")
    snapshot = Mock(id="window", event=SimpleNamespace(eligible_location=False))
    context = {
        "scope": {"snapshot_id": "window"},
        "required_tools": [],
        "compatible_tasks": [],
        "history_sensors": [
            {"pressure_summary_evidence_id": "priority-pressure"},
            {"pressure_summary_evidence_id": "quiet-pressure"},
            {"pressure_summary_evidence_id": None},
        ],
    }
    gateway = Mock(task=task)
    gateway.dispatch.return_value = {"result": {"evidence": {}}, "error": None}
    service = AgentService.__new__(AgentService)
    intake, _ = service._required_intake(task, snapshot, context, gateway)
    assert [item["name"] for item in intake] == ["evidence.get"]
    call = gateway.dispatch.call_args.args[0]
    assert call["args"]["ids"] == ["priority-pressure", "quiet-pressure"]
    assert call["origin"] == "application_required_intake"
    gateway.reset_mock()
    context["history_sensors"] = []
    intake, _ = service._required_intake(task, snapshot, context, gateway)
    assert intake == []
    gateway.dispatch.assert_not_called()


def test_extended_intake_reads_original_pressure_sources_in_bounded_batches() -> None:
    task = Mock(role="event_diagnosis", id="task", history_version="history-v1")
    evidence = {
        f"pressure-{index:03}": SimpleNamespace(id=f"pressure-{index:03}", kind="channel_summary")
        for index in range(112)
    }
    snapshot = Mock(
        id="window", evidence=evidence, event=SimpleNamespace(eligible_location=False)
    )
    context = {
        "scope": {"snapshot_id": "window"}, "required_tools": [], "compatible_tasks": [],
        "history_sensors": [], "network_pressure_table": {"total_instruments": 112},
    }
    gateway = Mock(task=task)
    gateway.dispatch.return_value = {"result": {"evidence": {}}, "error": None}
    service = AgentService.__new__(AgentService)
    intake, _ = service._required_intake(task, snapshot, context, gateway)
    calls = [call.args[0] for call in gateway.dispatch.call_args_list]
    assert len(intake) == len(calls) == 5
    assert all(len(call["args"]["ids"]) <= 24 for call in calls)
    assert {identifier for call in calls for identifier in call["args"]["ids"]} == set(evidence)
    assert all(call["origin"] == "application_required_intake" for call in calls)


def test_coordinator_groups_mixed_evidence_for_lossless_bounded_delivery() -> None:
    task = Mock(role="operator_response", id="root")
    evidence = {
        f"ev-{index:03}": SimpleNamespace(
            id=f"ev-{index:03}", kind="channel_summary" if index % 2 else "sensor_health",
            value={"baseline_median": 80, "recent_5s_pressure_drop_bar": 1.5},
        )
        for index in range(224)
    }
    evidence["location"] = SimpleNamespace(
        id="location", kind="location_fit", value={"status": "withheld", "reason": "too wide"},
    )
    snapshot = SimpleNamespace(id="window", evidence=evidence)
    context = {
        "scope": {"snapshot_id": "window"}, "required_tools": ["evidence.get"],
        "compatible_tasks": [{"evidence_ids": [key for key in evidence if key != "location"]}],
    }
    gateway = Mock(task=task)
    def dispatch(call: dict[str, Any]) -> dict[str, Any]:
        return {
            "error": None, "result": {
                "claims": {}, "evidence": {
                    key: {
                        "id": key, "kind": evidence[key].kind, "value": evidence[key].value,
                    } for key in call["args"]["ids"]
                },
            },
        }
    gateway.dispatch.side_effect = dispatch
    service = AgentService.__new__(AgentService)
    intake, _ = service._required_intake(task, snapshot, context, gateway)
    calls = [call.args[0] for call in gateway.dispatch.call_args_list]
    assert {key for call in calls for key in call["args"]["ids"]} == set(evidence)
    assert all(len(call["args"]["ids"]) <= 24 for call in calls)
    assert all(len({evidence[key].kind for key in call["args"]["ids"]}) == 1 for call in calls)
    pressure = [
        model_tool_result(item["output"])["result"] for item in intake
        if "channel_summary" == next(iter(item["output"]["result"]["evidence"].values()))["kind"]
    ]
    assert all("evidence_value_columns" in item for item in pressure)


def test_invalid_check_plan_is_audited_without_reading_and_scope_still_fails(tmp_path: Any) -> None:
    task = Mock(
        role="event_diagnosis",
        id="task",
        generation_id="generation",
        snapshot_id="window",
        lease_token="lease",
        tool_calls=1,
        knowledge_packet=SimpleNamespace(
            cards=[
                SimpleNamespace(id="KN-QUALITY-R1", roles=["event_diagnosis"]),
            ]
        ),
    )
    snapshot = Mock(
        site_id="northsea",
        id="window",
        pack_version="pack",
        baseline_version="baseline",
        parameter_version="parameters",
    )
    store = Mock()
    receipts: list[dict[str, Any]] = []
    store.tool_receipts.side_effect = lambda _: receipts
    store.reserve_tool_call.return_value = task

    def record(
        task_id: str,
        call_id: str,
        name: str,
        arguments: dict[str, Any],
        result: Any,
        error: str,
        **kwargs: Any,
    ) -> None:
        receipts.append(
            {
                "call_id": call_id,
                "name": name,
                "arguments": arguments,
                "result": result,
                "error": error,
                "diagnostic": kwargs.get("diagnostic"),
            }
        )

    store.record_tool_call.side_effect = record
    gateway = ToolGateway(store, task, snapshot, Telemetry(runtime_dir=tmp_path))
    gateway._read = Mock()
    arguments = {
        "site_id": "northsea",
        "snapshot_id": "window",
        "pack_version": "pack",
        "baseline_version": "baseline",
        "parameter_version": "parameters",
        "knowledge_ids": ["KN-QUALITY-R1"],
        "check_question": "x" * 242,
        "intent": "test_instrumentation",
        "query": "instrument calibration",
        "asset_ids": ["P1"],
    }
    call = {"id": "bad-check", "name": "history.search", "args": arguments}
    result = gateway.dispatch(call)
    assert result["result"] is None and result["error"] == "knowledge_check_plan"
    assert result["rejection"]["executed"] is False
    gateway._read.assert_not_called()
    assert receipts[0]["arguments"]["check_question"] == "x" * 242
    assert gateway.dispatch(call) == result
    assert store.reserve_tool_call.call_count == 1
    assert store.record_tool_call.call_count == 1
    with pytest.raises(ValidationError, match="scope"):
        gateway.dispatch(
            {
                "id": "foreign-scope",
                "name": "history.search",
                "args": {**arguments, "site_id": "another-site"},
            }
        )
    assert store.reserve_tool_call.call_count == 1


def test_invalid_evidence_identifiers_are_repairable_but_foreign_scope_is_not(
    tmp_path: Any,
) -> None:
    task = Mock(
        role="event_diagnosis",
        id="task",
        generation_id="generation",
        snapshot_id="window",
        lease_token="lease",
        tool_calls=1,
        knowledge_packet=None,
    )
    snapshot = Mock(
        site_id="northsea",
        id="window",
        pack_version="pack",
        baseline_version="baseline",
        parameter_version="parameters",
        evidence={"ev-current": Mock()},
    )
    store = Mock()
    receipts: list[dict[str, Any]] = []
    store.tool_receipts.side_effect = lambda _: receipts
    store.reserve_tool_call.return_value = task

    def record(
        task_id: str,
        call_id: str,
        name: str,
        arguments: dict[str, Any],
        result: Any,
        error: str,
        **kwargs: Any,
    ) -> None:
        receipts.append(
            {
                "call_id": call_id,
                "name": name,
                "arguments": arguments,
                "result": result,
                "error": error,
                "diagnostic": kwargs.get("diagnostic"),
            }
        )

    store.record_tool_call.side_effect = record
    gateway = ToolGateway(store, task, snapshot, Telemetry(runtime_dir=tmp_path))
    gateway._read = Mock()
    arguments = {
        "site_id": "northsea",
        "snapshot_id": "window",
        "pack_version": "pack",
        "baseline_version": "baseline",
        "parameter_version": "parameters",
        "ids": ["claim-000"],
    }
    call = {"id": "invalid-evidence", "name": "evidence.get", "args": arguments}
    rejected = gateway.dispatch(call)
    assert rejected["result"] is None and rejected["error"] == "tool_arguments"
    assert rejected["rejection"]["executed"] is False
    gateway._read.assert_not_called()
    assert gateway.dispatch(call) == rejected
    assert store.reserve_tool_call.call_count == 1
    assert store.record_tool_call.call_count == 1
    with pytest.raises(ValidationError, match="scope"):
        gateway.dispatch(
            {
                "id": "foreign",
                "name": "evidence.get",
                "args": {**arguments, "snapshot_id": "another-window"},
            }
        )
    assert store.reserve_tool_call.call_count == 1

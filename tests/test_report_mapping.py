import json
from datetime import timedelta
from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage

from subsea_copilot.contracts import AgentResult, AgentTask, EngineerInterpretation, utc_now
from subsea_copilot.report_mapping import load_report_mapping, prepare_report_mapping
from subsea_copilot.synthetic import generate_pack
from subsea_copilot.telemetry import Telemetry


@pytest.fixture
def report():
    pack = generate_pack()
    text = "P1-ST1-A has a brief spike; P1-ST1-B is a healthy comparison."
    interpretation = EngineerInterpretation(
        focus="sensor_quality", answer={"text": text, "references": ["ev-1"]},
        competing_causes=[{
            "cause": "leak", "stance": "not_established",
            "text": "No joint loss.", "references": ["ev-1"],
        }], follow_up_questions=["Did the instrument recover?"],
        regional_assessments=[{
            "hypothesis": "instrumentation_or_telemetry",
            "sensor_ids": ["P2-ST1-A", "P2-ST1-B"],
            "text": "Hidden group metadata claims P2-ST1-A has an offset.",
            "references": ["ev-2"],
        }],
    )
    task = AgentTask(
        id="mapped", root_id="mapped", site_id=pack.id, generation_id="recorded",
        snapshot_id="snapshot-110", role="operator_response", mode="live",
        question="Which instruments need attention?", purpose="answer_question",
        state="SUCCEEDED", deadline=utc_now() + timedelta(seconds=300),
        result=AgentResult(
            outcome="supported", claim_refs=[], limitations=[], interpretation=interpretation,
        ),
    )
    mapping = {
        "version": "agent-output-mapping-v1", "leaks": [],
        "sensor_issues": [{
            "sensor_id": "P1-ST1-A", "kind": "spike", "assertion": "suspected",
            "quote": {"path": "answer.text", "text": text},
        }],
        "instrumentation_concern": True,
        "instrumentation_quote": {"path": "answer.text", "text": text},
    }
    model = Mock()
    model.invoke.return_value = AIMessage(
        content=json.dumps(mapping),
        response_metadata={"mode": "live", "observed_model": "unit-test-only"},
    )
    return task, pack, model


def test_saved_labels_reuse_evaluation_extraction_without_reading_detectors(report, tmp_path):
    task, pack, model = report
    telemetry = Telemetry(runtime_dir=tmp_path)
    try:
        first = prepare_report_mapping(tmp_path, task, pack, model, telemetry)
        second = prepare_report_mapping(tmp_path, task, pack, model, telemetry)
    finally:
        telemetry.close()
    assert first == second == load_report_mapping(tmp_path, task, pack)
    assert model.invoke.call_count == 1
    assert [item["sensor_id"] for item in first["mapping"]["sensor_issues"]] == ["P1-ST1-A"]
    packet = json.loads(model.invoke.call_args.args[0][1].content)
    assert set(packet) == {"public_texts", "sensor_catalog", "quote_choices"}
    assert set(packet["sensor_catalog"][0]) == {"id", "station_id", "segment_id"}
    assert "healthy comparison" in packet["public_texts"]["answer.text"]
    assert "Hidden group metadata" not in json.dumps(packet)


def test_changed_report_or_snapshot_cannot_reuse_old_labels(report, tmp_path):
    task, pack, model = report
    telemetry = Telemetry(runtime_dir=tmp_path)
    try:
        prepare_report_mapping(tmp_path, task, pack, model, telemetry)
    finally:
        telemetry.close()
    altered = task.model_copy(update={"snapshot_id": "another-window"})
    with pytest.raises(ValueError, match="does not match"):
        load_report_mapping(tmp_path, altered, pack)
    changed = task.model_copy(deep=True)
    changed.result.interpretation.answer.text = "There is no instrument issue."
    with pytest.raises(ValueError, match="does not match"):
        load_report_mapping(tmp_path, changed, pack)


def test_saved_extraction_reprices_original_usage_without_new_inference(report, tmp_path):
    task, pack, model = report
    model.invoke.return_value.response_metadata.update({
        "observed_model": "gpt-6.1-sol",
        "usage": {"input_tokens": 1000, "output_tokens": 100},
    })
    telemetry = Telemetry(runtime_dir=tmp_path)
    try:
        original = prepare_report_mapping(tmp_path, task, pack, model, telemetry)
    finally:
        telemetry.close()
    path = next((tmp_path / "incident-report-mappings").glob("*.json"))
    saved = json.loads(path.read_text())
    saved["extraction"]["execution_usage"] = {
        "cost_min_usd": 0.00277, "cost_max_usd": 0.00352,
    }
    path.write_text(json.dumps(saved))
    reloaded = load_report_mapping(tmp_path, task, pack)
    assert reloaded["execution_usage"]["cost_usd"] == pytest.approx(0.003)
    assert reloaded["mapping"] == original["mapping"]
    assert model.invoke.call_count == 1


def test_invalid_quote_has_one_bounded_correction_and_no_playback_retry(report, tmp_path):
    task, pack, model = report
    response = json.loads(model.invoke.return_value.content)
    response["sensor_issues"][0]["quote"]["text"] = "Invented instrument diagnosis."
    model.invoke.return_value.content = json.dumps(response)
    telemetry = Telemetry(runtime_dir=tmp_path)
    try:
        result = prepare_report_mapping(tmp_path, task, pack, model, telemetry)
        assert prepare_report_mapping(tmp_path, task, pack, model, telemetry) == result
    finally:
        telemetry.close()
    assert result["status"] == "failed" and result["mapping"] is None
    assert model.invoke.call_count == 2


def test_quote_pointer_binds_original_report_text_without_model_recopying(report, tmp_path):
    task, pack, model = report
    response = json.loads(model.invoke.return_value.content)
    response["sensor_issues"][0]["quote"] = {"paragraph_id": "paragraph-0"}
    response["instrumentation_quote"] = {"paragraph_id": "paragraph-0"}
    model.invoke.return_value.content = json.dumps(response)
    telemetry = Telemetry(runtime_dir=tmp_path)
    try:
        result = prepare_report_mapping(tmp_path, task, pack, model, telemetry)
    finally:
        telemetry.close()
    assert result["status"] == "completed"
    assert result["mapping"]["sensor_issues"][0]["quote"]["text"] == (
        task.result.interpretation.answer.text
    )

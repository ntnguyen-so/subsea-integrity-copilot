"""Verify authored factual labels before inference and reject fact/reference errors.

Controlled fake transport checks pre-inference manifest persistence and failed-case
denominators; passing these tests is not hosted-model accuracy evidence.
"""

import json
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage

from subsea_copilot.agent_reference_evaluation import (
    ReferenceAnswer,
    independently_derived_reference,
    load_dataset,
    score_answer,
)


def test_authored_ground_truth_is_independent_and_covers_positive_negative_and_uncertain_cases():
    dataset = load_dataset()
    assert any(case.expected.leak_claim.status == "confirmed" for case in dataset.cases)
    assert any(case.family == "insufficient_evidence" for case in dataset.cases)
    assert {case.split for case in dataset.cases} == {"development", "held_out"}
    for case in dataset.cases:
        assert all(
            score_answer(case.expected, independently_derived_reference(case.input)).values()
        )


@pytest.mark.parametrize("error", ["value", "citation", "duplicate", "confirmed_cause"])
def test_fact_and_reference_errors_fail_without_an_llm_judge(error):
    case = load_dataset().cases[0]
    value = case.expected.model_dump(mode="json")
    if error == "value":
        value["measurements"][0]["pressure_bar"] = 8000
    elif error == "citation":
        value["measurements"][0]["evidence_id"] = "invented-source"
    elif error == "duplicate":
        value["measurements"].append(deepcopy(value["measurements"][0]))
    else:
        value["leak_claim"] = {
            "status": "confirmed",
            "segment_id": "P1",
            "document_ids": [],
        }
    assert not all(score_answer(case.expected, ReferenceAnswer.model_validate(value)).values())


def test_bad_authored_labels_are_rejected_before_inference(tmp_path):
    dataset = load_dataset().model_dump(mode="json")
    dataset["cases"][0]["expected"]["measurements"][0]["pressure_bar"] = 123
    path = tmp_path / "bad-reference.json"
    path.write_text(json.dumps(dataset))
    with pytest.raises(ValueError, match="Authored ground truth"):
        load_dataset(path)


def test_reference_run_freezes_labels_before_model_creation_and_counts_failed_cases(
    tmp_path,
    monkeypatch,
):
    from subsea_copilot import qualification, reference_evaluation
    from subsea_copilot.agent_reference_evaluation import run_reference_evaluation
    from subsea_copilot.config import Settings
    from subsea_copilot.llm.copilot_cli import ProviderError

    dataset = load_dataset()
    output = tmp_path / "run"
    public = tmp_path / "public.json"
    public.write_text(
        json.dumps(
            {
                "version": "spatial-evaluation-v1",
                "status": "completed",
                "cases": [],
                "run_id": "preserved",
                "agent_process": {"obsolete": True},
            }
        )
    )
    monkeypatch.setattr(reference_evaluation, "PUBLIC_REPORT", public)
    monkeypatch.setattr(Settings, "from_env", lambda: object())
    monkeypatch.setenv("SUBSEA_SYNTHETIC_ONLY", "1")
    monkeypatch.setenv("SUBSEA_TRACE_CONTENT", "1")

    class Model:
        def invoke(self, messages, **kwargs):
            packet = json.loads(messages[1].content)
            assert "expected" not in packet
            assert set(packet) == {"as_of_seconds", "sensor_ids", "measurements", "documents"}
            case = next(
                case for case in dataset.cases if case.input.model_dump(mode="json") == packet
            )
            if case.id == "AR-H3":
                raise ProviderError("timeout")
            return AIMessage(
                content=case.expected.model_dump_json(),
                response_metadata={"observed_model": "unit-test-only", "mode": "live"},
            )

    def factory(*args):
        manifest = json.loads((output / "reference-manifest.json").read_text())
        assert manifest["dataset"]["cases"] == dataset.model_dump(mode="json")["cases"]
        return lambda *args: Model()

    monkeypatch.setattr(qualification, "qualification_model_factory", factory)
    report = run_reference_evaluation(output, split="all")
    assert report["metrics"]["planned"] == 8
    assert report["metrics"]["failed"] == 1
    assert report["metrics"]["all_checks_passed"] == 7
    assert all(check["denominator"] == 8 for check in report["metrics"]["checks"].values())
    published = json.loads(public.read_text())
    assert published["run_id"] == "preserved"
    assert "agent_process" not in published
    assert published["agent_reference_evaluation"]["run_id"] == report["run_id"]
    assert (public.parent / "agent-reference-report.json").exists()
    reference_evaluation.write_report(public, {
        "version": "spatial-evaluation-v1", "status": "completed", "cases": [],
        "run_id": "new-detection", "agent_process": {"obsolete": True},
    })
    refreshed = reference_evaluation.read_evaluation()
    assert refreshed["run_id"] == "new-detection"
    assert "agent_process" not in refreshed
    assert refreshed["agent_reference_evaluation"]["run_id"] == report["run_id"]

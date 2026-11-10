"""Keep deterministic reference checks separate from advisory six-dimension opinions.

Authored synthetic packets and mocked author/judge responses verify frozen labels,
quote/citation checks and missing-score denominators, not live-model reliability.
"""

import json
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from subsea_copilot.agent_answer_quality import (
    DIMENSIONS,
    ExplainedAnswer,
    JudgeVerdict,
    quality_metrics,
    run_answer_quality_evaluation,
    validate_judgment,
)
from subsea_copilot.agent_reference_evaluation import DATASET_PATH, load_dataset


def opinion():
    return {
        "summary": "The answer follows the supplied facts.",
        "dimensions": [
            {
                "dimension": key,
                "status": "supported",
                "score": 5,
                "rationale": "Supported by the frozen reference.",
                "evidence_ids": [],
                "answer_excerpt": "Read the recorded pressure.",
            }
            for key in DIMENSIONS
        ],
    }


def answer(case):
    return ExplainedAnswer(
        facts=case.expected,
        explanation="Read the recorded pressure.",
        next_steps=["Compare an independent measurement before acting."],
        limitations=["This synthetic packet does not establish field safety."],
    )


@pytest.mark.parametrize(
    "error",
    [
        "duplicate",
        "unscored",
        "missing-score",
        "citation",
        "duplicate-citation",
        "quote",
        "numeric",
    ],
)
def test_quality_opinions_require_a_complete_rubric_and_frozen_reference_provenance(error):
    case = load_dataset().cases[0]
    actual = answer(case)
    value = opinion()
    if error == "duplicate":
        value["dimensions"][1]["dimension"] = "grounding"
    elif error == "unscored":
        value["dimensions"][0]["status"] = "insufficient_evidence"
    elif error == "missing-score":
        value["dimensions"][0]["score"] = None
    elif error == "citation":
        value["dimensions"][0]["evidence_ids"] = ["invented"]
    elif error == "duplicate-citation":
        value["dimensions"][0]["evidence_ids"] = [case.input.measurements[0].id] * 2
    elif error == "quote":
        value["dimensions"][0]["answer_excerpt"] = "Invented quotation"
    else:
        actual = actual.model_copy(deep=True)
        actual.facts.measurements[0].pressure_bar = 0
    with pytest.raises((ValidationError, ValueError)):
        validate_judgment(case, actual, JudgeVerdict.model_validate(value))


def test_unscored_and_failed_reviews_never_become_zero_scores_or_passes():
    value = opinion()
    for dimension in value["dimensions"]:
        dimension.update(status="not_applicable", score=None)
    rows = [
        {"judge": {"status": "completed", "verdict": value}},
        {"judge": {"status": "execution_failed", "verdict": None}},
        {"judge": {"status": "not_evaluated", "verdict": None}},
    ]
    result = quality_metrics(rows)
    assert result["reviewed"] == 1
    assert result["execution_failed"] == 1
    assert result["not_reviewed"] == 2
    assert result["no_concerns"] == 0
    assert all(
        item["average"] is None and item["scored"] == 0 for item in result["dimensions"].values()
    )


def test_quality_run_reuses_original_labels_hides_them_from_author_and_preserves_detection(
    tmp_path,
    monkeypatch,
):
    import threading

    from subsea_copilot import qualification, reference_evaluation
    from subsea_copilot.config import Settings
    from subsea_copilot.llm.copilot_cli import ProviderError

    dataset = load_dataset()
    original_dataset = DATASET_PATH.read_bytes()
    public = tmp_path / "evaluation-report.json"
    detection = {"run_id": "unchanged-detection", "cases": [], "metrics": {"score": 0.25}}
    public.write_text(json.dumps(detection), encoding="utf-8")
    original_detection = public.read_bytes()
    authors_started = threading.Barrier(len(dataset.cases))
    output = tmp_path / "quality"
    monkeypatch.setattr(reference_evaluation, "PUBLIC_REPORT", public)
    monkeypatch.setattr(Settings, "from_env", lambda: object())
    monkeypatch.setenv("SUBSEA_SYNTHETIC_ONLY", "1")
    monkeypatch.setenv("SUBSEA_TRACE_CONTENT", "1")

    class Model:
        def __init__(self, role):
            self.role = role

        def invoke(self, messages, **kwargs):
            packet = json.loads(messages[1].content)
            if self.role == "author":
                authors_started.wait(timeout=5)
                assert "original_ground_truth" not in packet and "expected" not in packet
                case = next(
                    case for case in dataset.cases if case.input.model_dump(mode="json") == packet
                )
                if case.id == "AR-H3":
                    raise ProviderError("timeout")
                actual = answer(case)
                if case.id == "AR-H2":
                    actual = actual.model_copy(deep=True)
                    actual.facts.measurements[0].pressure_bar = 0
                content = actual.model_dump_json()
            else:
                case = next(case for case in dataset.cases if case.id == packet["case_id"])
                assert packet["original_ground_truth"] == case.expected.model_dump(mode="json")
                index = dataset.cases.index(case)
                saved = json.loads((output / "answers" / f"{index:02d}.json").read_text())
                assert saved == packet["saved_answer"]
                if case.id == "AR-H4":
                    raise ProviderError("timeout")
                value = deepcopy(opinion())
                if case.id == "AR-H2":
                    value["dimensions"][1].update(status="concern", score=2)
                if case.id == "AR-H6":
                    value["dimensions"][-1].update(status="insufficient_evidence", score=None)
                content = json.dumps(value)
            return AIMessage(
                content=content, response_metadata={"observed_model": self.role, "mode": "live"}
            )

    def factory(settings, model_id):
        manifest = json.loads((output / "reference-manifest.json").read_text())
        assert manifest["dataset"] == dataset.model_dump(mode="json")
        assert set(manifest["rubric"]) == set(DIMENSIONS)
        return lambda *args: Model(model_id)

    monkeypatch.setattr(qualification, "qualification_model_factory", factory)
    report = run_answer_quality_evaluation(
        output, split="all", model_id="author", judge_model_id="judge"
    )
    assert report["metrics"]["planned"] == 8
    assert report["metrics"]["failed"] == 1
    assert report["metrics"]["all_checks_passed"] == 6
    quality = report["answer_quality"]["metrics"]
    assert quality["reviewed"] == 6
    assert quality["execution_failed"] == 1
    assert quality["with_concerns"] == 1
    assert quality["insufficient_evidence"] == 1
    assert quality["no_concerns"] == 4
    assert quality["dimensions"]["usefulness"]["scored"] == 5
    assert quality["dimensions"]["numeric_accuracy"]["average"] == 4.5
    assert quality["by_split"]["development"]["reviewed"] == 2
    assert quality["by_split"]["held_out"]["reviewed"] == 4
    assert report["dataset_unchanged"] is True
    assert all(check["denominator"] == 8 for check in report["metrics"]["checks"].values())
    assert DATASET_PATH.read_bytes() == original_dataset
    assert public.read_bytes() == original_detection
    sidecar = json.loads((public.parent / "agent-reference-report.json").read_text())
    assert sidecar["run_id"] == report["run_id"]
    with pytest.raises(ValueError, match="fresh"):
        run_answer_quality_evaluation(output)

"""Protect matched report rubrics, bounded reviewer sequences and planned denominators.

Abstention/context remain separate, exact-point claims fail, and slow, interrupted,
failed or unattempted reports cannot disappear from timely-success accounting.
"""

from collections import Counter
from copy import deepcopy

import pytest

from subsea_copilot.evaluation import EXPECTED
from subsea_copilot.operations_evaluation import (
    EXPECTED_ACTIONS,
    EXPECTED_CONTEXT,
    EXPECTED_RECORDS,
    report_rubric,
    review_sequence_complete,
    summarize,
)


def test_review_audit_counts_indexed_reflections_and_still_requires_each_critic():
    phases = Counter({"critic-0": 1, "critic-1": 1, "critic-2": 1,
                      "reflection": 1, "reflection-1": 1})
    assert review_sequence_complete(["revise", "revise", "accept"], phases)
    phases["critic-1"] = 0
    assert not review_sequence_complete(["revise", "revise", "accept"], phases)
    phases["critic-1"] = 1
    phases["reflection-1"] = 0
    assert not review_sequence_complete(["revise", "revise", "accept"], phases)


def test_review_audit_preserves_legacy_repeated_reflections():
    phases = Counter({"critic-0": 1, "critic-1": 1, "critic-2": 1, "reflection": 2})
    assert review_sequence_complete(["revise", "revise", "accept"], phases)
    phases["reflection"] = 1
    assert not review_sequence_complete(["revise", "revise", "accept"], phases)


def report(scenario="S1"):
    identifiers = sorted(EXPECTED_RECORDS[scenario])
    return {
        "completed": True,
        "physical_decision": EXPECTED[scenario],
        "inspection": {"segment_id": "P1", "start_m": 200.0, "end_m": 600.0}
        if scenario == "S1"
        else None,
        "context_assessment": sorted(EXPECTED_CONTEXT[scenario])[0],
        "next_action": sorted(EXPECTED_ACTIONS[scenario])[0],
        "documents": [{"id": identifiers[0], "admissible": True}],
        "cited_document_ids": [identifiers[0]],
        "comparisons": [{"sensors": ["example"]}],
        "coverage_disclosed": True,
        "limitations_disclosed": True,
    }


@pytest.mark.parametrize("scenario", EXPECTED)
def test_common_rubric_retains_physical_abstention_and_context_separately(scenario):
    assert all(report_rubric(scenario, 2, report(scenario)).values())
    candidate = report(scenario)
    if scenario in {"S3", "S4", "S5"}:
        candidate["physical_decision"] = "no_event"
        assert not report_rubric(scenario, 2, candidate)["physical_decision"]
        candidate = report(scenario)
        candidate["inspection"] = {"segment_id": "P1", "start_m": 200.0, "end_m": 600.0}
        assert not report_rubric(scenario, 2, candidate)["inspection_or_withholding"]


def test_common_rubric_rejects_exact_point_and_requires_fully_read_current_evidence():
    candidate = report()
    candidate["inspection"]["start_m"] = candidate["inspection"]["end_m"] = 400
    checks = report_rubric("S1", 2, candidate)
    assert not checks["inspection_or_withholding"]
    candidate = report()
    candidate["documents"][0]["admissible"] = False
    assert not report_rubric("S1", 2, candidate)["source_authority"]
    candidate = report()
    candidate["documents"] = []
    checks = report_rubric("S1", 2, candidate)
    assert not checks["relevant_history_read"]
    assert not checks["source_authority"]


def test_failure_and_unattempted_reports_stay_in_latency_success_denominator():
    passed = {
        "report": report(),
        "rubric": {"physical_decision": True},
        "rubric_passed": True,
        "elapsed_seconds": 200,
        "checks": {"bounded_execution": True},
        "fresh_model_calls": 7,
        "critic_decisions": ["accept"],
    }
    fixed = deepcopy(passed)
    fixed["elapsed_seconds"] = 0.1
    failed = deepcopy(passed)
    failed.update(
        report={"completed": False},
        rubric={"physical_decision": False},
        rubric_passed=False,
        elapsed_seconds=40,
        checks={"bounded_execution": True},
    )
    rows = [
        {"agent": passed, "deterministic": fixed},
        {"agent": failed, "deterministic": fixed},
    ]
    summary = summarize(rows, expected_count=3)
    assert summary["planned"] == 3
    assert summary["not_attempted"] == 1
    assert summary["agent_correct_reports"] == 1
    assert summary["latency"]["agent"]["correct_reports_within_300s"] == 1
    assert summary["latency"]["agent"]["denominator"] == 3
    assert summary["latency"]["agent"]["p50_seconds"] == 120
    assert summary["report_checks"]["agent"]["physical_decision"] == {"passed": 1, "denominator": 3}
    assert summary["agent_faster_on_matched_correct_pairs"] == 0
    assert not summary["passed"]
    assert not summary["superiority_demonstrated"]


def test_slow_correct_report_fails_timely_delivery_without_becoming_inaccurate():
    row = {
        "report": report(),
        "rubric": {"physical_decision": True},
        "rubric_passed": True,
        "elapsed_seconds": 301,
        "checks": {"bounded_execution": True},
        "fresh_model_calls": 7,
        "critic_decisions": ["accept"],
    }
    fixed = {**row, "elapsed_seconds": 0.1}
    summary = summarize([{"agent": row, "deterministic": fixed}], 1)
    assert summary["agent_correct_reports"] == 1
    assert summary["latency"]["agent"]["correct_reports_within_300s"] == 0
    assert not summary["passed"]


def test_interrupted_attempt_is_not_relabelled_as_unattempted_or_excluded():
    summary = summarize([], 18, attempted_count=1)
    assert summary["attempted"] == 1
    assert summary["unscored_attempts"] == 1
    assert summary["not_attempted"] == 17
    assert summary["latency"]["agent"]["denominator"] == 18
    assert not summary["passed"]

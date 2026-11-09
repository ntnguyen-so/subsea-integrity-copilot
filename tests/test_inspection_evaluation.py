"""Check measured inspection candidates and conservative context-based demotions.

Missing references/bad taps cannot create locations; only incident-time approved
matching citations can partition candidates. Metadata authority is not prose entailment.
"""

import pytest

from subsea_copilot.inspection_evaluation import (
    Demotion,
    InspectionDecision,
    case_snapshot,
    fixed_inspection_baseline,
    inspection_candidates,
    load_inspection_suite,
    validate_inspection_decision,
    visible_records,
)
from subsea_copilot.validation import ValidationError


@pytest.fixture(scope="module")
def prepared_cases():
    return {
        case.id: (case, inspection_candidates(*case_snapshot(case)))
        for case in load_inspection_suite().cases
    }


def test_conditional_candidates_are_computed_on_all_three_original_pipes(prepared_cases):
    observed = set()
    for case, candidates in prepared_cases.values():
        if case.id in {"LC13", "LC14"}:
            continue
        assert {candidate.segment_id for candidate in candidates} == set(case.segments)
        for candidate in candidates:
            observed.add(candidate.segment_id)
            assert candidate.inspection_start_m == 200
            assert candidate.inspection_end_m == 600
            assert len(candidate.supporting_sensors) == 4
    assert observed == {"P1", "P2", "P3"}


def test_missing_outer_reference_and_isolated_bad_tap_cannot_create_location(prepared_cases):
    assert prepared_cases["LC13"][1] == []
    assert prepared_cases["LC14"][1] == []


def test_fixed_policy_handles_execution_cancellation_future_and_draft(prepared_cases):
    for key in ("LC01", "LC02", "LC03", "LC04", "LC12", "LC15", "LC16"):
        case, candidates = prepared_cases[key]
        decision = fixed_inspection_baseline(candidates, visible_records(case))
        validate_inspection_decision(decision, candidates, visible_records(case))
        assert set(decision.first_priority) == set(case.expected_first)
    assert visible_records(prepared_cases["LC04"][0]) == []


def test_demotion_requires_current_approved_matching_source_and_complete_partition(prepared_cases):
    case, candidates = prepared_cases["LC02"]
    decision = fixed_inspection_baseline(candidates, visible_records(case))
    for record in (
        case.records[0].model_copy(update={"status": "draft"}),
        case.records[0].model_copy(update={"available": 360}),
        case.records[0].model_copy(update={"assets": ["P3"]}),
        case.records[0].model_copy(update={"status": "superseded"}),
    ):
        with pytest.raises(ValidationError, match="citation"):
            validate_inspection_decision(decision, candidates, [record])
    incomplete = decision.model_copy(update={"deprioritized": []})
    with pytest.raises(ValidationError, match="Partition"):
        validate_inspection_decision(incomplete, candidates, visible_records(case))


def test_correction_invalidates_earlier_source_even_when_old_row_says_approved(prepared_cases):
    case, candidates = prepared_cases["LC08"]
    wrong = InspectionDecision(
        first_priority=["P3"],
        deprioritized=[Demotion(segment_id="P1", document_ids=["ENTRY-G1"], reason="Old tag")],
        explanation="This citation is superseded.",
    )
    with pytest.raises(ValidationError, match="citation"):
        validate_inspection_decision(wrong, candidates, visible_records(case))


def test_metadata_checks_are_not_misrepresented_as_semantic_entailment(prepared_cases):
    case, candidates = prepared_cases["LC06"]
    # A parent-asset tag passes mechanical membership checks, but the skid
    # narrative does not justify demoting the live subsea branch.
    misleading = InspectionDecision(
        first_priority=["P1"],
        deprioritized=[Demotion(segment_id="P3", document_ids=["SHIFT-E"], reason="Misread scope")],
        explanation="A semantic error that must be scored, not hidden by schema acceptance.",
    )
    validate_inspection_decision(misleading, candidates, visible_records(case))
    assert set(misleading.first_priority) != set(case.expected_first)


def test_future_correction_cannot_silently_supersede_the_current_record(prepared_cases):
    case, candidates = prepared_cases["LC08"]
    records = [
        case.records[0],
        case.records[1].model_copy(update={"available": 360}),
    ]
    decision = fixed_inspection_baseline(candidates, records)
    assert decision.first_priority == ["P3"]
    assert decision.deprioritized[0].document_ids == ["ENTRY-G1"]
    validate_inspection_decision(decision, candidates, records)

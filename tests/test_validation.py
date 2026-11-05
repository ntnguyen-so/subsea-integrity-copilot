from datetime import timedelta

import pytest
from test_agents import snapshot as snapshot_fixture

from subsea_copilot.contracts import AgentResult, AgentTask, Claim, utc_now
from subsea_copilot.runtime.registry import REGISTRY
from subsea_copilot.validation import ValidationError, render_result, validate_result


@pytest.fixture(name="snapshot")
def ledger_snapshot():
    return snapshot_fixture.__wrapped__()


def quality_task(snapshot):
    return AgentTask(
        id="quality",
        root_id="root",
        parent_id="root",
        site_id=snapshot.site_id,
        generation_id=snapshot.generation_id,
        snapshot_id=snapshot.id,
        role="sensor_quality",
        purpose=REGISTRY["sensor_quality"].purpose,
        question="health",
        mode="scripted",
        deadline=utc_now() + timedelta(seconds=300),
    )


def valid_result():
    return AgentResult(
        outcome="supported",
        claim_refs=["coverage", "health", "limit"],
        evidence_ids=["coverage-e", "health-e", "limit-e"],
        limitations=["synthetic_data"],
    )


def receipts():
    return [
        {
            "name": name,
            "error": None,
            "result": {
                "metadata": [{"id": "sensor", "failure_domain_id": "gateway"}],
                "findings": [{"sensor_id": "sensor", "channel": "acoustic"}],
            },
        }
        for name in REGISTRY["sensor_quality"].required
    ]


@pytest.mark.parametrize(
    "change,code",
    [
        ({"summary": "confirmed leak; safe to operate; shutdown"}, "certainty"),
        ({"claim_refs": ["fabricated"]}, "citations"),
        ({"evidence_ids": ["foreign"]}, "evidence"),
        ({"limitations": []}, "limitations"),
        ({"recommendation_ids": ["shutdown"]}, "role"),
        ({"hypothesis": "suspected_leak"}, "hypothesis"),
    ],
)
def test_rejects_unsupported_scope_citations_and_certainty(snapshot, change, code):
    with pytest.raises(ValidationError) as error:
        validate_result(
            valid_result().model_copy(update=change), quality_task(snapshot), snapshot, receipts()
        )
    assert error.value.code == code


def test_numbers_units_cannot_be_smuggled_as_fields_or_commentary(snapshot):
    task = quality_task(snapshot)
    payload = valid_result().model_dump()
    payload["coverage"] = {"value": 1000, "unit": "m"}
    with pytest.raises(ValidationError) as error:
        validate_result(payload, task, snapshot, receipts())
    assert error.value.code == "structure"
    payload = valid_result().model_copy(update={"summary": "Coverage 10 m"})
    with pytest.raises(ValidationError):
        validate_result(payload, task, snapshot, receipts())


def test_accepts_equivalent_supported_ledger_unit_representations(snapshot):
    snapshot.claims["coverage-percent"] = Claim(
        id="coverage-percent",
        kind="coverage",
        value={"coverage": 100, "unit": "%"},
        evidence_ids=["coverage-e"],
    )
    original = valid_result()
    equivalent = original.model_copy(update={"claim_refs": ["coverage-percent", "health", "limit"]})
    task = quality_task(snapshot)
    first = validate_result(original, task, snapshot, receipts())
    second = validate_result(equivalent, task, snapshot, receipts())
    assert render_result(first, task, snapshot) == render_result(second, task, snapshot)
    assert "100.0%" in render_result(second, task, snapshot)
    assert "2 usable spikes" in render_result(first, task, snapshot)


def test_required_receipts_and_cross_snapshot_fail(snapshot):
    task = quality_task(snapshot)
    with pytest.raises(ValidationError) as error:
        validate_result(valid_result(), task, snapshot, [])
    assert error.value.code == "required_receipts"
    task.snapshot_id = "another"
    with pytest.raises(ValidationError) as error:
        validate_result(valid_result(), task, snapshot, receipts())
    assert error.value.code == "scope"


@pytest.mark.parametrize(
    "payload",
    [
        '{"outcome":"supported","outcome":"insufficient_evidence"}',
        '{"outcome":"supported","claim_refs":[],"limitations":[],"extra":NaN}',
    ],
)
def test_ambiguous_inner_json_is_rejected(snapshot, payload):
    with pytest.raises(ValidationError) as error:
        validate_result(payload, quality_task(snapshot), snapshot, receipts())
    assert error.value.code == "structure"


def test_section_answer_requires_computed_location_or_explicit_abstention(snapshot):
    from test_agents import located_snapshot

    from subsea_copilot.runtime.baseline import BASELINE_CLAIMS
    from subsea_copilot.validation import validate_grounded_result

    snapshot = located_snapshot(snapshot)
    task = quality_task(snapshot).model_copy(
        update={
            "role": "operator_response",
            "purpose": "evaluate_single_agent_baseline",
            "question": "Which pipeline section should the engineer inspect first?",
        }
    )
    result = AgentResult(
        outcome="supported",
        claim_refs=["coverage", "event", "limit"],
        evidence_ids=["coverage-e", "event-e", "limit-e"],
        limitations=["synthetic_data"],
        hypothesis="suspected_leak",
    )
    with pytest.raises(ValidationError) as error:
        validate_grounded_result(result, task, snapshot, [], claim_kinds=BASELINE_CLAIMS)
    assert error.value.code == "location_required"
    located = result.model_copy(
        update={
            "claim_refs": [*result.claim_refs, "location"],
            "evidence_ids": [*result.evidence_ids, "location-e"],
        }
    )
    assert (
        validate_grounded_result(
            located,
            task,
            snapshot,
            [{"name": "location.fit"}],
            claim_kinds=BASELINE_CLAIMS,
        )
        == located
    )
    unsupported = AgentResult(
        outcome="insufficient_evidence",
        claim_refs=["coverage", "limit"],
        evidence_ids=["coverage-e", "limit-e"],
        limitations=["synthetic_data", "location_withheld"],
    )
    assert (
        validate_grounded_result(
            unsupported,
            task,
            snapshot,
            [],
            claim_kinds=BASELINE_CLAIMS,
        )
        == unsupported
    )


def test_quality_support_is_about_sensor_findings_not_physical_corroboration(snapshot):
    snapshot.event.hypothesis = "insufficient_evidence"
    task = quality_task(snapshot)
    assert validate_result(valid_result(), task, snapshot, receipts()).outcome == "supported"
    with pytest.raises(ValidationError) as error:
        validate_result(
            valid_result().model_copy(update={"outcome": "insufficient_evidence"}),
            task,
            snapshot,
            receipts(),
        )
    assert error.value.code == "quality_outcome"
    with pytest.raises(ValidationError) as error:
        validate_result(
            valid_result().model_copy(
                update={"claim_refs": ["limit"], "evidence_ids": ["limit-e"]}
            ),
            task,
            snapshot,
            receipts(),
        )
    assert error.value.code == "quality_scope"


@pytest.mark.parametrize(
    "hypothesis",
    ["suspected_leak", "sensor_or_telemetry_issue", "environmental_disturbance", "no_event"],
)
def test_abstention_still_rejects_categorical_hypothesis_claims(snapshot, hypothesis):
    from subsea_copilot.runtime.baseline import BASELINE_CLAIMS
    from subsea_copilot.validation import validate_grounded_result

    task = quality_task(snapshot).model_copy(
        update={
            "role": "operator_response",
            "purpose": "evaluate_single_agent_baseline",
        }
    )
    snapshot.claims["event"].value = hypothesis
    result = valid_result().model_copy(
        update={
            "outcome": "insufficient_evidence",
            "claim_refs": ["coverage", "event", "limit"],
            "evidence_ids": ["coverage-e", "event-e", "limit-e"],
            "hypothesis": None,
        }
    )
    with pytest.raises(ValidationError) as error:
        validate_grounded_result(result, task, snapshot, [], claim_kinds=BASELINE_CLAIMS)
    assert error.value.code == "abstention"


def test_abstention_still_rejects_position_even_with_withheld_limitation(snapshot):
    from test_agents import located_snapshot

    from subsea_copilot.runtime.baseline import BASELINE_CLAIMS
    from subsea_copilot.validation import validate_grounded_result

    snapshot = located_snapshot(snapshot)
    task = quality_task(snapshot).model_copy(
        update={
            "role": "operator_response",
            "purpose": "evaluate_single_agent_baseline",
        }
    )
    result = AgentResult(
        outcome="insufficient_evidence",
        claim_refs=["coverage", "location", "limit"],
        evidence_ids=["coverage-e", "location-e", "limit-e"],
        limitations=["synthetic_data", "location_withheld"],
    )
    with pytest.raises(ValidationError) as error:
        validate_grounded_result(
            result,
            task,
            snapshot,
            [{"name": "location.fit"}],
            claim_kinds=BASELINE_CLAIMS,
        )
    assert error.value.code == "abstention"

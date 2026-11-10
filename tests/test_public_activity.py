"""Check that public activity separates requested intent, observations and failure.

Local payload fixtures require no model/tool execution; failed reads must never
publish successful findings or unchecked claim references.
"""

from subsea_copilot.public_activity import public_check, tool_selection


def test_public_checks_separate_agent_question_from_observed_output():
    question = "Do neighboring sensors change together or only one shared connection?"
    requested = public_check(
        "event_diagnosis",
        "call-1",
        "history.compare",
        {"check_question": question, "knowledge_ids": ["KN-INDEPENDENCE-R1"]},
    )
    assert requested["status"] == "requested"
    assert requested["agent_question"] == question
    assert "observation" not in requested
    completed = public_check(
        "sensor_quality",
        "call-2",
        "quality.coverage",
        {},
        {"quality": {"usable_samples": 50, "expected_samples": 60}, "claims": {"claim-1": {}}},
        completed=True,
    )
    assert completed["status"] == "completed"
    assert "50 usable readings out of 60 expected" in completed["observation"]
    assert completed["claim_refs"] == ["claim-1"]
    assert "not zero" in completed["purpose"]


def test_failed_public_check_does_not_publish_success_or_unchecked_claims():
    failed = public_check(
        "event_diagnosis",
        "call-3",
        "history.compare",
        {},
        {"claims": {"unverified": {}}},
        "context_budget_exceeded",
        completed=True,
    )
    assert failed["status"] == "failed"
    assert "No successful finding" in failed["observation"]
    assert "claim_refs" not in failed


def test_tool_selection_does_not_invent_model_reasons_or_mislabel_required_intake():
    call = {"id": "call", "name": "history.compare", "args": {
        "check_question": "Do independent neighbors change together?", "intent": "test_leak",
    }}
    missing = tool_selection("event_diagnosis", call)
    assert missing["decision_summary"] is None
    assert missing["decision_provenance"] == "not_recorded"
    assert missing["check_question"] == call["args"]["check_question"]
    public = tool_selection("event_diagnosis", {
        **call, "decision_summary": "Compare the independent reference pair.",
        "model_call_id": "turn", "model_span_id": "span", "model_turn_index": 2,
    })
    assert public["decision_provenance"] == "model_public"
    assert public["model_call_id"] == "turn"
    required = tool_selection("event_diagnosis", {
        **call, "origin": "application_required_intake",
        "decision_summary": "Not a model decision.", "model_call_id": "not-applicable",
    })
    assert required["decision_provenance"] == "application_required_intake"
    assert required["model_call_id"] is None
    assert "Not a model decision." not in required["decision_summary"]
    assert missing["parameter_summary"] is None
    assert missing["parameter_provenance"] == "not_recorded"


def test_selection_keeps_parameter_reasons_and_declared_sources_separate_from_authority():
    selection = tool_selection("event_diagnosis", {
        "id": "compare", "name": "history.compare", "args": {},
        "decision_summary": "Resolve whether the late change is isolated.",
        "parameter_summary": "Compare paired taps over [100,120), split at 110.",
        "source_references": ["prior-profile"],
    })
    assert selection["parameter_provenance"] == "model_public"
    assert selection["parameter_summary"] == "Compare paired taps over [100,120), split at 110."
    assert selection["declared_source_references"] == ["prior-profile"]
    assert "not validated" in selection["source_reference_authority"]

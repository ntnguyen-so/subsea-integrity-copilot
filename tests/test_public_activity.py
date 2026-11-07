from subsea_copilot.public_activity import public_check


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

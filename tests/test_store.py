from datetime import timedelta

import pytest

from subsea_copilot.contracts import AgentTask, utc_now
from subsea_copilot.store import BudgetExceeded, Conflict, QueueFull, ScopeError, Store


def task(**updates: object) -> AgentTask:
    values = {
        "id": "root",
        "root_id": "root",
        "site_id": "northsea",
        "generation_id": "generation",
        "snapshot_id": "window",
        "role": "operator_response",
        "purpose": "operator_question",
        "question": "Explain the evidence",
        "mode": "scripted",
        "deadline": utc_now() + timedelta(seconds=299),
    }
    values.update(updates)
    return AgentTask.model_validate(values)


def test_retry_identity_keeps_execution_inputs() -> None:
    original = task(idempotency_key="question-1")
    retry = task(id="new-id", root_id="new-id", idempotency_key="question-1")
    assert Store._compatible(original.model_dump(mode="json"), retry)
    changed = retry.model_copy(update={"question": "Different evidence question"})
    assert not Store._compatible(original.model_dump(mode="json"), changed)
    changed = retry.model_copy(update={"snapshot_id": "different-window"})
    assert not Store._compatible(original.model_dump(mode="json"), changed)


def test_store_refuses_unbounded_scope_before_connecting() -> None:
    with pytest.raises(ScopeError):
        Store("not a database", tenant_id="")


def test_admission_errors_are_distinguishable() -> None:
    assert isinstance(BudgetExceeded(), Conflict)
    assert BudgetExceeded().code == "budget_blocked"
    assert QueueFull().code == "queue_full"
    assert ScopeError().code == "forbidden"

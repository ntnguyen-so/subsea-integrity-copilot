"""Memory persistence is a unit-test fake only; the application uses PostgreSQL."""

from contextlib import contextmanager
from datetime import timedelta
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from subsea_copilot.contracts import (
    Claim,
    EventAssessment,
    EvidenceItem,
    QualityFinding,
    QualityReport,
    ReplaySession,
    WindowSnapshot,
    utc_now,
)
from subsea_copilot.runtime.agent import repair_model_messages
from subsea_copilot.runtime.gateway import ToolGateway
from subsea_copilot.runtime.scripted import ScriptedChatModel
from subsea_copilot.runtime.workflow import AgentService
from subsea_copilot.validation import ValidationError


class FakeSpan:
    def set_attribute(self, *args):
        pass


def test_detailed_engineering_briefing_preserves_paragraphs_and_citation_checks():
    from subsea_copilot.contracts import AgentResult, AgentTask, EngineerInterpretation
    from subsea_copilot.interpretation import validate_interpretation

    briefing = "\n\n".join(
        [
            "Recommended next step\n"
            "Review the connected pressure pattern with the integrity engineer.",
            "What the readings show\n" + "Compare the nearby instruments and their timing. " * 20,
            "What would resolve the remaining question\n"
            "Review the operating records before deciding on an inspection area.",
        ]
    )
    result = AgentResult(
        outcome="supported",
        claim_refs=["measured-pressure"],
        limitations=[],
        interpretation=EngineerInterpretation(
            focus="inspection_rationale",
            answer={"text": briefing, "references": ["measured-pressure"]},
            competing_causes=[
                {
                    "cause": "leak",
                    "stance": "possible",
                    "text": "Review the pressure pattern before identifying its cause.",
                    "references": ["measured-pressure"],
                }
            ],
            follow_up_questions=["Can the engineer review the pressure timing?"],
        ),
    )
    task = AgentTask(
        id="brief",
        root_id="brief",
        generation_id="generation",
        snapshot_id="snapshot",
        site_id="northsea",
        role="operator_response",
        purpose="answer_incident_question",
        question="Where to review?",
        mode="live",
        deadline=utc_now(),
        response_protocol="engineer-v2",
    )
    validate_interpretation(result, task)
    assert result.model_dump()["interpretation"]["answer"]["text"] == briefing
    result.interpretation.answer.references = ["invented-evidence"]
    with pytest.raises(ValidationError, match="accepted claims") as rejected:
        validate_interpretation(result, task)
    assert "invented-evidence" in str(rejected.value)


def test_baseline_citations_require_a_successful_read_and_reach_the_reviewer(snapshot):
    import json

    from subsea_copilot.contracts import AgentResult, AgentTask, EngineerInterpretation
    from subsea_copilot.grounding import source_texts
    from subsea_copilot.interpretation import validate_interpretation

    baseline = EvidenceItem(
        id="baseline-e",
        kind="channel_summary",
        sensor_id="sensor",
        value={"baseline_median": 80, "median_pressure_drop_bar": 1.1},
    )
    snapshot.evidence[baseline.id] = baseline
    result = AgentResult(
        outcome="supported",
        claim_refs=["health"],
        evidence_ids=["health-e", baseline.id],
        limitations=[],
        interpretation=EngineerInterpretation(
            focus="inspection_rationale",
            answer={
                "text": "The pressure is about 1.1 bar below its normal reference.",
                "references": [baseline.id],
            },
            competing_causes=[
                {
                    "cause": "leak",
                    "stance": "possible",
                    "text": "An independent reference can help distinguish the physical cause.",
                    "references": ["health"],
                }
            ],
            follow_up_questions=["Can the engineer check an independent pressure reference?"],
        ),
    )
    task = AgentTask(
        id="baseline",
        root_id="baseline",
        generation_id="generation",
        snapshot_id=snapshot.id,
        site_id=snapshot.site_id,
        role="operator_response",
        purpose="answer_incident_question",
        question="What does this pattern show?",
        mode="live",
        deadline=utc_now(),
        response_protocol="engineer-v2",
    )
    receipt = {
        "name": "evidence.get",
        "result": {"evidence": {baseline.id: baseline.model_dump(mode="json")}},
        "error": None,
    }
    validate_interpretation(result, task, [receipt])
    sources = source_texts(result, snapshot, [receipt])
    assert json.loads(sources[baseline.id])["value"]["median_pressure_drop_bar"] == 1.1
    from subsea_copilot.profiles import expanded_evidence

    uncited = baseline.model_copy(update={"id": "uncited-baseline-e", "sensor_id": "peer"})
    unread = baseline.model_copy(update={"id": "unread-baseline-e", "sensor_id": "unread"})
    snapshot.evidence.update({uncited.id: uncited, unread.id: unread})
    result.evidence_ids.extend([uncited.id, unread.id])
    receipts = [{
        **receipt, "result": {"evidence": {
            baseline.id: baseline.model_dump(mode="json"),
            uncited.id: uncited.model_dump(mode="json"),
        }},
    }]
    audited = expanded_evidence(json.loads(
        source_texts(result, snapshot, receipts)["audited_pressure_summaries"],
    ))
    assert audited["evidence"][uncited.id] == uncited.model_dump(mode="json")
    assert unread.id not in audited["evidence"]
    assert uncited.id not in sources
    paired_sources = [
        baseline.model_copy(update={"id": f"paired-baseline-{index}"})
        for index in range(8)
    ]
    for item in paired_sources:
        snapshot.evidence[item.id] = item
    expanded_result = result.model_copy(deep=True)
    expanded_result.evidence_ids = [item.id for item in paired_sources]
    expanded_result.interpretation = expanded_result.interpretation.model_copy(update={
        "competing_causes": [
            expanded_result.interpretation.competing_causes[0].model_copy(update={
                "references": [item.id for item in paired_sources],
            }),
        ],
    })
    expanded_result = AgentResult.model_validate(expanded_result.model_dump())
    complete_reads = {
        **receipt, "result": {"evidence": {
            item.id: item.model_dump(mode="json") for item in [baseline, *paired_sources]
        }},
    }
    expanded_result.evidence_ids.append(baseline.id)
    validate_interpretation(expanded_result, task, [complete_reads])
    for receipts in ([], [{**receipt, "error": "tool_result_size"}]):
        with pytest.raises(ValidationError, match="accepted claims"):
            validate_interpretation(result, task, receipts)
        with pytest.raises(ValidationError, match="source"):
            source_texts(result, snapshot, receipts)


def test_checked_health_distinguishes_unavailable_values_from_invalid_received_records(snapshot):
    from subsea_copilot.contracts import AgentResult, AgentTask
    from subsea_copilot.validation import render_result

    snapshot.quality.findings[0] = snapshot.quality.findings[0].model_copy(
        update={"received": 60, "usable": 45, "missing": 15, "hard_excluded": 15}
    )
    task = AgentTask(
        id="health",
        root_id="health",
        generation_id="generation",
        snapshot_id=snapshot.id,
        site_id=snapshot.site_id,
        role="sensor_quality",
        purpose="assess_sensor_health",
        question="Which values need checking?",
        mode="live",
        deadline=utc_now(),
    )
    text = render_result(
        AgentResult(outcome="supported", claim_refs=["health"], limitations=[]), task, snapshot
    )
    assert "15 unavailable values" in text
    assert "15 invalid received observations" in text
    assert "15 missing;" not in text


def test_repair_projection_retains_source_receipts_and_audited_invalid_draft():
    source = SystemMessage(content="Complete scoped source context")
    receipt = ToolMessage(content='{"pressure": [null, 79.5]}', tool_call_id="read-1")
    draft = AIMessage(content="invalid result " * 1000)
    repair = HumanMessage(
        content='{"repair": "limitations", "validator_feedback": "Missing required limitation"}',
        additional_kwargs={"validation_repair": True},
    )
    messages = [source, receipt, draft, repair]
    assert repair_model_messages(messages) == [source, receipt, repair]
    assert messages == [source, receipt, draft, repair]
    assert repair_model_messages([source, draft, HumanMessage(content="Follow-up")]) == [
        source,
        draft,
        HumanMessage(content="Follow-up"),
    ]


def test_repeated_repairs_keep_evidence_and_feedback_without_accumulating_invalid_drafts():
    import json

    source = SystemMessage(content="Complete scoped source context")
    request = AIMessage(
        content="", tool_calls=[{"id": "read-1", "name": "history.read", "args": {}}]
    )
    receipt = ToolMessage(content='{"pressure": [null, 79.5]}', tool_call_id="read-1")
    messages = [source, request, receipt]
    repairs = []
    for error in ("regional_evidence", "evidence", "interpretation_citations"):
        repair = HumanMessage(
            content=json.dumps({"repair": error}),
            additional_kwargs={"validation_repair": True},
        )
        repairs.append(repair)
        messages.extend([AIMessage(content="invalid result " * 1000), repair])
    original = list(messages)
    assert repair_model_messages(messages) == [source, request, receipt, *repairs]
    assert messages == original


def test_repair_projection_rejects_malformed_historical_repair_pair():
    repair = HumanMessage(content="repair", additional_kwargs={"validation_repair": True})
    with pytest.raises(ValidationError, match="Repair must follow"):
        repair_model_messages([repair, AIMessage(content="later final")])


@pytest.mark.parametrize("detail", ["Use only fully reviewed current sources.", "x" * 1500])
def test_reflection_receives_bounded_specific_criticism_and_cannot_retry_forever(detail):
    import json

    from langgraph.types import Command

    from subsea_copilot.runtime.agent import build_graph

    def reject(_value):
        raise ValidationError("interpretation_citations", detail)

    graph = build_graph(validator=reject)
    config = {"configurable": {"thread_id": uuid4().hex}}
    graph.invoke({"messages": [], "phase": "answer", "repairs": 0}, config)
    revised = graph.invoke(Command(resume=AIMessage(content="{}")), config)
    feedback = json.loads(revised["__interrupt__"][0].value["messages"][-1].content)
    assert feedback["repair"] == "interpretation_citations"
    assert feedback["validator_feedback"] == detail[:1000]
    for _ in range(2):
        repaired = graph.invoke(Command(resume=AIMessage(content="{}")), config)
        assert not repaired.get("failure")
    rejected = graph.invoke(Command(resume=AIMessage(content="{}")), config)
    assert rejected["failure"] == "interpretation_citations"
    assert not rejected.get("parsed")


class FakeTelemetry:
    @contextmanager
    def span(self, *args, **kwargs):
        yield FakeSpan()


class MemoryStore:
    """No production fallback: implements only the frozen API for these unit tests."""

    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.tasks = {}
        self.receipts = {}
        self.events = []
        self.generation_model_calls = 0
        self.reuse_links = {}
        self.qualification = False
        self.provider_error = None

    def get_window(self, identifier):
        return self.snapshot.model_copy(deep=True) if identifier == self.snapshot.id else None

    def get_replay(self, identifier):
        return ReplaySession(id=identifier, tenant_id=self.snapshot.tenant_id, scenario="unit")

    def get_provider_failure(self):
        return self.provider_error

    def clear_provider_failure(self):
        self.provider_error = None

    def record_model_call(self, identifier, token, call_id, metadata):
        self._fence(identifier, token)
        if metadata["mode"] == "live" and metadata.get("error") in {"proxy_auth", "proxy_quota"}:
            self.provider_error = metadata["error"]

    def get_task(self, identifier):
        task = self.tasks.get(identifier)
        return task.model_copy(deep=True) if task else None

    def list_tasks(self, generation_id):
        return [
            t.model_copy(deep=True) for t in self.tasks.values() if t.generation_id == generation_id
        ]

    def create_task(self, task):
        existing = self.get_task(task.id)
        if existing:
            if existing.question != task.question or existing.snapshot_id != task.snapshot_id:
                raise ValidationError("idempotency_conflict", "Changed request.")
            return existing
        self.tasks[task.id] = task.model_copy(deep=True)
        return self.get_task(task.id)

    def claim_task(self, owner, ttl_seconds=360, *, task_id=None):
        for task in self.tasks.values():
            if task_id is not None and task.id != task_id:
                continue
            if task.state == "QUEUED":
                task.state = "RUNNING"
                task.lease_token = uuid4().hex
                task.lease_expires_at = utc_now() + timedelta(seconds=ttl_seconds)
                task.version += 1
                return task.model_copy(deep=True)
        return None

    def _fence(self, identifier, token):
        task = self.tasks[identifier]
        if task.lease_token != token or task.lease_expires_at <= utc_now():
            raise ValidationError("stale_lease", "Lease changed.")
        return task

    def save_task(self, task, expected_version=None, lease_token=None):
        previous = self._fence(task.id, lease_token)
        if previous.version != expected_version:
            raise ValidationError("stale_version", "Version changed.")
        task = task.model_copy(deep=True)
        task.version += 1
        self.tasks[task.id] = task
        if task.state in {"SUCCEEDED", "ABSTAINED", "FAILED", "CANCELLED"} and task.parent_id:
            parent = self.tasks[task.parent_id]
            if parent.state == "WAITING_ON_CHILD":
                parent.state = "QUEUED"
                parent.version += 1
        return task.model_copy(deep=True)

    def create_child(self, child, step_index, plan_revision=1, lease_token=None):
        parent = self._fence(child.parent_id, lease_token)
        created = self.create_task(child)
        parent.state = "WAITING_ON_CHILD"
        parent.version += 1
        return created

    def authorize_reuse(self, parent_id, task_ids, lease_token):
        self._fence(parent_id, lease_token)
        existing = self.reuse_links.get(parent_id)
        if existing is not None and existing != task_ids:
            raise ValidationError("reuse_conflict", "Pinned reuse bindings changed.")
        self.reuse_links[parent_id] = list(task_ids)
        return [self.get_task(identifier) for identifier in task_ids]

    def reuse_task_ids(self, parent_id):
        return self.reuse_links.get(parent_id, [])

    def _reserve(self, identifier, token, limit, field, root_limit):
        task = self._fence(identifier, token)
        root = self.tasks[task.root_id]
        total = sum(getattr(t, field) for t in self.tasks.values() if t.root_id == root.id)
        if (
            getattr(task, field) >= limit
            or total >= root_limit
            or task.deadline <= utc_now()
            or field == "model_calls"
            and self.generation_model_calls >= 100
        ):
            raise ValidationError("budget_blocked", "Persisted budget exhausted.")
        setattr(task, field, getattr(task, field) + 1)
        task.version += 1
        if field == "model_calls":
            self.generation_model_calls += 1
        return task.model_copy(deep=True)

    def reserve_model_call(self, identifier, token, limit):
        return self._reserve(identifier, token, limit, "model_calls", 10)

    def reserve_tool_call(self, identifier, token, limit):
        return self._reserve(identifier, token, limit, "tool_calls", 18)

    def record_tool_call(
        self, identifier, call_id, name, arguments, result, error=None, lease_token=None
    ):
        self._fence(identifier, lease_token)
        self.receipts.setdefault(identifier, []).append(
            {
                "call_id": call_id,
                "name": name,
                "arguments": arguments,
                "result": result,
                "error": error,
            }
        )

    def tool_receipts(self, identifier):
        return self.receipts.get(identifier, [])

    def publish_event(self, generation, name, payload, **kwargs):
        self.events.append((name, payload))


@pytest.fixture
def snapshot():
    now = utc_now()
    evidence = {
        "coverage-e": EvidenceItem(id="coverage-e", kind="coverage", value={"coverage": 1}),
        "health-e": EvidenceItem(id="health-e", kind="sensor_health", value={"spike_count": 2}),
        "event-e": EvidenceItem(id="event-e", kind="event", value={"hypothesis": "suspected_leak"}),
        "limit-e": EvidenceItem(id="limit-e", kind="limitation", value={"code": "synthetic_data"}),
        "metadata-e": EvidenceItem(
            id="metadata-e",
            kind="sensor_metadata",
            value={"sensors": [{"id": "sensor", "failure_domain_id": "gateway"}]},
        ),
    }
    return WindowSnapshot(
        id="window",
        site_id="northsea",
        generation_id="generation",
        window_start=now,
        window_end=now + timedelta(seconds=60),
        end_seconds=60,
        input_hash="abc",
        pack_version="pack-v1",
        clock_seconds=65,
        watermark_seconds=60,
        canonical_count=60,
        quality=QualityReport(
            status="NORMAL",
            expected_samples=60,
            received_samples=60,
            usable_samples=60,
            coverage=1,
            failure_domains_available=2,
            findings=[
                QualityFinding(
                    sensor_id="sensor",
                    channel="acoustic",
                    expected=60,
                    received=60,
                    usable=60,
                    missing=0,
                    spike_count=2,
                ),
            ],
        ),
        event=EventAssessment(
            hypothesis="suspected_leak",
            eligible_hypotheses=["suspected_leak"],
            supporting_sensor_ids=["sensor"],
            evidence_ids=["event-e"],
        ),
        evidence=evidence,
        claims={
            "coverage": Claim(
                id="coverage",
                kind="coverage",
                value={"coverage": 1, "unit": "fraction"},
                evidence_ids=["coverage-e"],
            ),
            "health": Claim(
                id="health",
                kind="sensor_health",
                value={"sensor_id": "sensor", "channel": "acoustic", "spike_count": 2},
                evidence_ids=["health-e"],
            ),
            "event": Claim(
                id="event",
                kind="hypothesis",
                value={"hypothesis": "suspected_leak"},
                evidence_ids=["event-e"],
            ),
            "limit": Claim(
                id="limit",
                kind="limitation",
                value={"code": "synthetic_data"},
                evidence_ids=["limit-e"],
            ),
        },
    )


def service_for(snapshot, model_factory=None, checkpointer=None):
    store = MemoryStore(snapshot)
    service = AgentService(
        store,
        model_factory or (lambda role, mode: ScriptedChatModel(role=role)),
        checkpointer,
        FakeTelemetry(),
    )
    return store, service


def submit(service, snapshot, question, key="first"):
    return service.submit_question(
        ReplaySession(id="generation", scenario="unit"), snapshot, question, key
    )


def drain(service):
    for _ in range(12):
        if not service.run_once():
            return
    pytest.fail("Workflow did not reach an idle queue.")


def test_fresh_children_are_real_separate_graph_tasks_and_preserve_anomalies(snapshot):
    store, service = service_for(snapshot, checkpointer=InMemorySaver())
    root = submit(service, snapshot, "What caused this leak?")
    drain(service)
    tasks = store.list_tasks("generation")
    assert {t.role for t in tasks} == {
        "operator_response",
        "sensor_quality",
        "event_diagnosis",
    }
    assert all(t.state == "SUCCEEDED" for t in tasks), [(t.role, t.error_code) for t in tasks]
    assert store.get_task(root.id).model_calls == 2
    assert sum(t.model_calls for t in tasks) == 4
    assert "2 spike-screening flags" in store.get_task(root.id).answer
    diagnosis = next(t for t in tasks if t.role == "event_diagnosis")
    quality = next(t for t in tasks if t.role == "sensor_quality")
    assert any(
        r["arguments"].get("task_id") == quality.id for r in store.tool_receipts(diagnosis.id)
    )
    assert "SCRIPTED" in store.get_task(root.id).answer


def test_health_only_then_compatible_reuse_creates_no_extra_children(snapshot):
    store, service = service_for(snapshot)
    health = submit(service, snapshot, "Which sensors need a health review?")
    drain(service)
    assert store.get_task(health.id).state == "SUCCEEDED"
    assert len(store.tasks) == 2
    summary = submit(service, snapshot, "Summarize saved findings", "summary")
    drain(service)
    assert store.get_task(summary.id).state == "SUCCEEDED"
    assert len(store.tasks) == 3
    assert store.get_task(summary.id).plan == ["reuse", "answer"]
    assert store.reuse_task_ids(summary.id) == [
        next(t.id for t in store.tasks.values() if t.role == "sensor_quality")
    ]


def test_reuse_authorizes_original_quality_diagnosis_pair_without_new_children(snapshot):
    store, service = service_for(snapshot, checkpointer=InMemorySaver())
    original = submit(service, snapshot, "What happened and where is the leak?")
    drain(service)
    summary = submit(service, snapshot, "Summarize the saved investigation", "summary-pair")
    drain(service)
    assert store.get_task(summary.id).state == "SUCCEEDED"
    linked = [store.get_task(identifier) for identifier in store.reuse_task_ids(summary.id)]
    assert {t.role for t in linked} == {"sensor_quality", "event_diagnosis"}
    assert all(t.parent_id == original.id for t in linked)
    assert len(store.tasks) == 4
    assert store.get_task(summary.id).tool_calls == 4
    repeated = submit(service, snapshot, "What happened and where is the leak?", "repeated")
    drain(service)
    assert store.get_task(repeated.id).plan == ["reuse", "answer"]
    assert len(store.tasks) == 5


def test_wait_resume_retains_budget_and_child_identity(snapshot):
    store, service = service_for(snapshot, checkpointer=InMemorySaver())
    root = submit(service, snapshot, "What caused this event?")
    service.run_once()
    assert store.get_task(root.id).state == "WAITING_ON_CHILD"
    assert store.get_task(root.id).model_calls == 1
    child_ids = [t.id for t in store.tasks.values() if t.parent_id]
    resumed_service = AgentService(
        store, service.model_factory, service.checkpointer, FakeTelemetry()
    )
    drain(resumed_service)
    assert store.get_task(root.id).model_calls == 2
    assert set(child_ids) <= set(store.tasks)
    assert len([t for t in store.tasks.values() if t.parent_id]) == 2
    assert submit(service, snapshot, "What caused this event?").id == root.id


class InvalidQuality(ScriptedChatModel):
    def _generate(self, *args, **kwargs):
        result = super()._generate(*args, **kwargs)
        if not result.generations[0].message.tool_calls:
            result.generations[0].message = AIMessage(
                content='{"summary":"confirmed safe shutdown"}'
            )
        return result


def test_failed_child_blocks_successful_response(snapshot):
    store, service = service_for(
        snapshot,
        lambda role, mode: (
            InvalidQuality(role=role) if role == "sensor_quality" else ScriptedChatModel(role=role)
        ),
    )
    root = submit(service, snapshot, "What caused this leak?")
    drain(service)
    assert store.get_task(root.id).state == "FAILED"
    assert store.get_task(root.id).error_code == "child_failed"
    assert len(store.tasks) == 2


def test_exhausted_root_budget_is_not_reset_by_new_service(snapshot):
    store, service = service_for(snapshot)
    root = submit(service, snapshot, "Sensor health?")
    store.tasks[root.id].model_calls = 9
    service.run_once()
    assert store.get_task(root.id).state == "FAILED"
    assert store.get_task(root.id).error_code == "budget_blocked"
    assert store.get_task(root.id).model_calls == 9


def test_gateway_scope_authority_and_idempotent_receipt(snapshot):
    store, service = service_for(snapshot)
    root = submit(service, snapshot, "Health?")
    service.run_once()
    child = store.claim_task("unit")
    gateway = ToolGateway(store, child, snapshot, FakeTelemetry())
    scope = {
        k: getattr(snapshot, k)
        for k in (
            "site_id",
            "pack_version",
            "baseline_version",
            "parameter_version",
        )
    }
    scope["snapshot_id"] = snapshot.id
    call = {"id": "once", "name": "quality.coverage", "args": scope}
    assert gateway.dispatch(call) == gateway.dispatch(call)
    assert store.get_task(child.id).tool_calls == 1
    with pytest.raises(ValidationError, match="scope"):
        gateway.dispatch({**call, "id": "bad", "args": {**scope, "site_id": "other"}})
    with pytest.raises(ValidationError):
        gateway.dispatch({**call, "id": "shell", "name": "shell"})
    assert store.get_task(root.id).state == "WAITING_ON_CHILD"


def test_oversized_tool_result_is_recorded_as_error_not_success(snapshot, monkeypatch):
    from subsea_copilot.contracts import TOOL_RESULT_MAX_BYTES

    store, service = service_for(snapshot)
    submit(service, snapshot, "Health?")
    service.run_once()
    child = store.claim_task("unit")
    gateway = ToolGateway(store, child, snapshot, FakeTelemetry())
    monkeypatch.setattr(gateway, "_read", lambda *_args: {"payload": "x" * TOOL_RESULT_MAX_BYTES})
    arguments = {
        key: getattr(snapshot, key)
        for key in ("site_id", "pack_version", "baseline_version", "parameter_version")
    }
    arguments["snapshot_id"] = snapshot.id
    call = {"id": "oversized", "name": "quality.coverage", "args": arguments}
    assert gateway.dispatch(call) == {"result": None, "error": "payload_too_large"}
    assert gateway.dispatch(call) == {"result": None, "error": "payload_too_large"}
    assert store.get_task(child.id).tool_calls == 1
    receipt = store.tool_receipts(child.id)[0]
    assert receipt["result"] is None and receipt["error"] == "payload_too_large"


def test_diagnosis_aggregate_read_budget_records_an_explicit_gap(snapshot, monkeypatch):
    store, service = service_for(snapshot)
    submit(service, snapshot, "What caused the event?")
    for _ in range(5):
        diagnosis = next(
            (task for task in store.tasks.values() if task.role == "event_diagnosis"), None
        )
        if diagnosis:
            break
        service.run_once()
    assert diagnosis is not None
    task = store.claim_task("unit", task_id=diagnosis.id)
    gateway = ToolGateway(store, task, snapshot, FakeTelemetry())
    monkeypatch.setattr(gateway, "_read", lambda *_args: {"payload": "x" * (24 * 1024)})
    scope = {
        key: getattr(snapshot, key)
        for key in ("site_id", "pack_version", "baseline_version", "parameter_version")
    }
    scope["snapshot_id"] = snapshot.id
    for index in range(3):
        result = gateway.dispatch({"id": f"bounded-{index}", "name": "evidence.get", "args": scope})
        if index < 2:
            assert result["error"] is None
        else:
            assert result == {"result": None, "error": "context_budget_exceeded"}
    assert store.tool_receipts(task.id)[-1]["error"] == "context_budget_exceeded"


@pytest.mark.parametrize("scenario", ["S1", "S2", "S5"])
def test_scripted_contract_smoke_with_actual_numerical_ledger(scenario):
    from subsea_copilot.diagnostics import analyze_window
    from subsea_copilot.ingest import normalize_records
    from subsea_copilot.synthetic import generate_scenario

    dataset = generate_scenario(scenario, duration_seconds=180)
    snapshot = analyze_window(
        dataset.pack,
        normalize_records(dataset.baseline, dataset.pack),
        normalize_records(dataset.records, dataset.pack),
        "generation",
        180,
        185,
        dataset.epoch,
    )
    store, service = service_for(snapshot, checkpointer=InMemorySaver())
    root = submit(service, snapshot, "What happened and where is the event?")
    drain(service)
    assert store.get_task(root.id).state in {"SUCCEEDED", "ABSTAINED"}, [
        (t.role, t.error_code, t.model_calls, t.tool_calls) for t in store.tasks.values()
    ]
    assert len(store.tasks) == 3
    if scenario in {"S1", "S2"}:
        result = store.get_task(root.id).result
        assert result is not None
        assert (
            result.hypothesis
            == {
                "S1": "suspected_leak",
                "S2": "sensor_or_telemetry_issue",
            }[scenario]
        )
        has_location = any(snapshot.claims[ref].kind == "location" for ref in result.claim_refs)
        assert has_location == (scenario == "S1")
    assert all(
        len(str(r["result"]).encode()) <= 48 * 1024
        for task in store.tasks.values()
        for r in store.tool_receipts(task.id)
    )
    from subsea_copilot.runtime.baseline import run_single_agent_baseline

    store.qualification = True
    baseline = run_single_agent_baseline(
        store,
        snapshot,
        "scripted",
        lambda role, mode: ScriptedChatModel(role=role),
        FakeTelemetry(),
        checkpointer=InMemorySaver(),
    )
    assert baseline["check_accepted"] is True, baseline
    if snapshot.event.hypothesis == "insufficient_evidence":
        assert baseline["outcome"] == "insufficient_evidence"
        assert baseline["hypothesis"] is None
    else:
        assert baseline["hypothesis"] == snapshot.event.hypothesis
    assert baseline["child_count"] == 0
    quality = next(t for t in store.tasks.values() if t.role == "sensor_quality")
    assert "partial_health_review" not in quality.result.limitations
    refreshed = submit(service, snapshot, "Which sensors need a health review?", "current-contract")
    drain(service)
    assert store.get_task(refreshed.id).state == "SUCCEEDED"
    assert store.get_task(refreshed.id).plan == ["reuse", "answer"]
    assert "partial_health_review" not in store.get_task(refreshed.id).result.limitations


def test_provider_quota_is_durable_unavailability_without_retry(snapshot):
    class QuotaModel(ScriptedChatModel):
        def _generate(self, *args, **kwargs):
            raise ValidationError("proxy_quota", "Synthetic provider failure.")

    store, service = service_for(snapshot, lambda role, mode: QuotaModel(role=role))
    session = ReplaySession(id="generation", scenario="unit", mode="live")
    root = service.submit_question(session, snapshot, "Health?", "quota")
    service.run_once()
    assert store.get_task(root.id).error_code == "proxy_quota"
    assert service.health()["available"] is False
    restarted = AgentService(store, service.model_factory, InMemorySaver(), FakeTelemetry())
    with pytest.raises(ValidationError) as error:
        restarted.submit_question(session, snapshot, "Health again?", "another")
    assert error.value.code == "proxy_quota"
    assert store.get_task(root.id).model_calls == 1
    later = snapshot.model_copy(update={"id": "next-window", "generation_id": "next-generation"})
    store.snapshot = later
    next_session = ReplaySession(id=later.generation_id, scenario="unit", mode="live")
    next_worker = AgentService(store, service.model_factory, InMemorySaver(), FakeTelemetry())
    assert next_worker.health()["available"] is False
    with pytest.raises(ValidationError) as error:
        next_worker.submit_question(next_session, later, "Health in new replay?", "new-replay")
    assert error.value.code == "proxy_quota"
    assert len(store.tasks) == 1
    store.clear_provider_failure()  # Explicit successful CLI provider check.
    assert service.health()["available"] is True
    service._check_provider(next_session.id, "live")
    next_worker.reset_provider_availability(next_session.id)
    assert next_worker.health()["available"] is True


def test_checkpoint_tool_interrupt_replays_receipts_without_dispatch_twice(snapshot):
    store, service = service_for(snapshot, checkpointer=InMemorySaver())
    root = submit(service, snapshot, "What caused this leak?")
    service.run_once()
    original = store.record_tool_call
    crashed = False

    def crash_after_receipt(*args, **kwargs):
        nonlocal crashed
        original(*args, **kwargs)
        if not crashed:
            crashed = True
            raise KeyboardInterrupt("Simulated termination after committing a receipt.")

    store.record_tool_call = crash_after_receipt
    with pytest.raises(KeyboardInterrupt):
        service.run_once()
    quality = next(t for t in store.tasks.values() if t.role == "sensor_quality")
    assert quality.tool_calls == 1
    first_call_id = store.tool_receipts(quality.id)[0]["call_id"]
    quality.state = "QUEUED"  # Unit fake simulates persisted expired-lease reclamation.
    store.record_tool_call = original
    restarted = AgentService(store, service.model_factory, service.checkpointer, FakeTelemetry())
    drain(restarted)
    assert store.get_task(root.id).state == "SUCCEEDED"
    assert store.get_task(quality.id).tool_calls == 4
    assert sum(r["call_id"] == first_call_id for r in store.tool_receipts(quality.id)) == 1


def test_child_commit_survives_crash_before_runtime_returns(snapshot):
    store, service = service_for(snapshot, checkpointer=InMemorySaver())
    root = submit(service, snapshot, "What caused this leak?")
    original = store.create_child

    def crash_after_atomic_child(*args, **kwargs):
        original(*args, **kwargs)
        raise KeyboardInterrupt("Termination after child/link/parent-wait commit.")

    store.create_child = crash_after_atomic_child
    with pytest.raises(KeyboardInterrupt):
        service.run_once()
    assert store.get_task(root.id).state == "WAITING_ON_CHILD"
    assert len(store.tasks) == 2
    assert store.get_task(root.id).model_calls == 1
    store.create_child = original
    restarted = AgentService(store, service.model_factory, service.checkpointer, FakeTelemetry())
    drain(restarted)
    assert store.get_task(root.id).state == "SUCCEEDED"
    assert len(store.tasks) == 3
    assert store.get_task(root.id).model_calls == 2


def test_abstained_child_permits_only_explicit_unsupported_response(snapshot):
    contexts = []

    class InspectingAbstention(ScriptedChatModel):
        def _generate(self, messages, *args, **kwargs):
            import json

            from langchain_core.messages import SystemMessage

            context = json.loads(
                next(
                    m.content.split("\nBOUND_CONTEXT\n", 1)[1]
                    for m in messages
                    if isinstance(m, SystemMessage) and "\nBOUND_CONTEXT\n" in m.content
                )
            )
            if context["phase"] == "answer":
                contexts.append(context)
            return super()._generate(messages, *args, **kwargs)

    class AbstainedQuality(ScriptedChatModel):
        def _generate(self, *args, **kwargs):
            import json

            result = super()._generate(*args, **kwargs)
            message = result.generations[0].message
            if not message.tool_calls:
                payload = json.loads(message.content)
                payload["outcome"] = "insufficient_evidence"
                message.content = json.dumps(payload)
            return result

    snapshot.claims = {
        ref: claim
        for ref, claim in snapshot.claims.items()
        if claim.kind not in {"coverage", "sensor_health"}
    }
    store, service = service_for(
        snapshot,
        lambda role, mode: (
            AbstainedQuality(role=role)
            if role == "sensor_quality"
            else InspectingAbstention(role=role)
        ),
    )
    root = submit(service, snapshot, "What caused this leak?")
    drain(service)
    answer = store.get_task(root.id)
    assert answer.state == "ABSTAINED"
    assert "child_abstained" in answer.result.limitations
    assert answer.result.hypothesis is None
    assert "event" not in answer.result.claim_refs
    assert {context["role"] for context in contexts} == {
        "event_diagnosis",
        "operator_response",
    }
    for context in contexts:
        properties = context["result_schema"]["properties"]
        assert properties["outcome"]["const"] == "insufficient_evidence"
        assert properties["hypothesis"] == {"type": "null"}
        assert properties["limitations"]["contains"] == {"const": "child_abstained"}
        assert "event" not in properties["claim_refs"]["items"]["enum"]
    diagnosis = next(t for t in store.tasks.values() if t.role == "event_diagnosis")
    from subsea_copilot.validation import validate_result

    with pytest.raises(ValidationError) as error:
        validate_result(
            diagnosis.result.model_copy(
                update={
                    "limitations": [
                        code for code in diagnosis.result.limitations if code != "child_abstained"
                    ],
                }
            ),
            diagnosis,
            snapshot,
            store.tool_receipts(diagnosis.id),
            ToolGateway(store, diagnosis, snapshot, FakeTelemetry()).dependencies(),
        )
    assert error.value.code == "abstention"


def postgres_settings():
    import os

    from subsea_copilot.config import Settings

    required = (
        "SUBSEA_DB_ADMIN_PASSWORD",
        "SUBSEA_DB_APP_PASSWORD",
        "SUBSEA_DB_TOOL_PASSWORD",
        "SUBSEA_DB_CHECKPOINT_PASSWORD",
        "SUBSEA_OPERATOR_PASSWORD",
    )
    if any(not os.environ.get(name) for name in required):
        pytest.skip("Requires independently bootstrapped PostgreSQL and owned role environment.")
    return Settings.from_env()


@pytest.mark.integration
def test_real_postgres_saver_runs_fresh_scripted_root_and_reopens():
    from subsea_copilot.diagnostics import analyze_window
    from subsea_copilot.ingest import normalize_records
    from subsea_copilot.runtime.checkpointer import postgres_checkpointer
    from subsea_copilot.store import Store
    from subsea_copilot.synthetic import generate_scenario

    settings = postgres_settings()
    source = generate_scenario("S1", duration_seconds=180)
    tenant = "agent-integration-" + uuid4().hex
    with Store(
        settings.database_dsn, tenant_id=tenant, tools_dsn=settings.tools_dsn, qualification=True
    ) as store:
        session = store.create_replay(
            ReplaySession(
                id="generation-" + uuid4().hex,
                tenant_id=tenant,
                scenario="S1",
                clock_seconds=185,
                epoch=source.epoch,
            )
        )
        pinned = store.save_window(
            analyze_window(
                source.pack,
                normalize_records(source.baseline, source.pack),
                normalize_records(source.records, source.pack),
                session.id,
                180,
                185,
                source.epoch,
                tenant_id=tenant,
            )
        )
        with postgres_checkpointer(settings.checkpoint_dsn, setup=True) as saver:
            service = AgentService(
                store,
                lambda role, mode: ScriptedChatModel(role=role),
                saver,
                FakeTelemetry(),
            )
            root = service.submit_question(session, pinned, "What caused this leak?", "fresh")
            original_create_child = store.create_child

            def crash_after_child_commit(*args, **kwargs):
                original_create_child(*args, **kwargs)
                raise KeyboardInterrupt("Termination after PostgreSQL child/wait commit.")

            store.create_child = crash_after_child_commit
            try:
                with pytest.raises(KeyboardInterrupt):
                    service.run_once()
            finally:
                store.create_child = original_create_child
            assert store.get_task(root.id).state == "WAITING_ON_CHILD"
            assert len(store.list_tasks(session.id)) == 2
        with postgres_checkpointer(settings.checkpoint_dsn) as saver:
            restarted = AgentService(
                store,
                lambda role, mode: ScriptedChatModel(role=role),
                saver,
                FakeTelemetry(),
            )
            drain(restarted)
            tasks = store.list_tasks(session.id)
            assert store.get_task(root.id).state == "SUCCEEDED", restarted.health()
            assert len(tasks) == 3
            assert sum(t.model_calls for t in tasks) == 4
            assert sum(t.tool_calls for t in tasks) <= 18
            reused = restarted.submit_question(
                session,
                pinned,
                "Which pipeline section should our integrity engineer inspect first, and why?",
                "reused",
            )
            drain(restarted)
            assert store.get_task(reused.id).state == "SUCCEEDED", restarted.health()
            assert store.get_task(reused.id).plan == ["reuse", "answer"]
            assert any(
                pinned.claims[ref].kind == "location"
                for ref in store.get_task(reused.id).result.claim_refs
            )
            assert len(store.list_tasks(session.id)) == 4
            from subsea_copilot.runtime.baseline import run_single_agent_baseline

            baseline = run_single_agent_baseline(
                store,
                pinned,
                "scripted",
                lambda role, mode: ScriptedChatModel(role=role),
                FakeTelemetry(),
                checkpointer=saver,
            )
            assert baseline["check_accepted"] is True, baseline
            assert baseline["model_calls"] == 1
            assert baseline["child_count"] == 0
            assert len(store.list_tasks(session.id)) == 5


@pytest.mark.integration
def test_checkpoint_default_fails_fast_for_unbootstrapped_owned_schema():
    import psycopg
    from psycopg import sql

    from subsea_copilot.runtime.checkpointer import CheckpointError, postgres_checkpointer

    settings = postgres_settings()
    schema = "test_checkpoints_" + uuid4().hex
    with psycopg.connect(settings.admin_dsn, autocommit=True) as connection:
        connection.execute(
            sql.SQL("CREATE SCHEMA {} AUTHORIZATION subsea_checkpoint").format(
                sql.Identifier(schema),
            )
        )
        try:
            with pytest.raises(CheckpointError) as error:
                with postgres_checkpointer(settings.checkpoint_dsn, schema=schema):
                    pytest.fail("Uninitialized checkpoint schema must fail at construction.")
            assert error.value.code == "checkpoint_uninitialized"
        finally:
            connection.execute(sql.SQL("DROP SCHEMA {}").format(sql.Identifier(schema)))


def test_single_agent_baseline_counts_real_requests_without_widening_production(snapshot):
    from subsea_copilot.runtime.baseline import run_single_agent_baseline

    store = MemoryStore(snapshot)
    store.qualification = True
    result = run_single_agent_baseline(
        store,
        snapshot,
        "scripted",
        lambda role, mode: ScriptedChatModel(role=role),
        FakeTelemetry(),
        checkpointer=InMemorySaver(),
    )
    assert result["check_accepted"] is True
    assert result["hypothesis"] == "suspected_leak"
    assert result["model_calls"] == 1
    assert result["tool_calls"] == 3
    assert result["live_model_evidence"] is False
    assert len(store.tasks) == 1
    task = next(iter(store.tasks.values()))
    production = task.model_copy(update={"purpose": "answer_incident_question"})
    gateway = ToolGateway(store, production, snapshot, FakeTelemetry())
    with pytest.raises(ValidationError):
        gateway._authorize(
            "event.assess",
            {
                "site_id": snapshot.site_id,
                "snapshot_id": snapshot.id,
                "pack_version": snapshot.pack_version,
                "baseline_version": snapshot.baseline_version,
                "parameter_version": snapshot.parameter_version,
            },
        )


def test_single_agent_baseline_rejects_unsafe_output_and_nonqualification_store(snapshot):
    from subsea_copilot.runtime.baseline import run_single_agent_baseline

    store = MemoryStore(snapshot)
    with pytest.raises(ValidationError) as error:
        run_single_agent_baseline(
            store,
            snapshot,
            "scripted",
            lambda role, mode: ScriptedChatModel(role=role),
            FakeTelemetry(),
        )
    assert error.value.code == "baseline_authority"
    store.qualification = True
    result = run_single_agent_baseline(
        store,
        snapshot,
        "scripted",
        lambda role, mode: InvalidQuality(role=role),
        FakeTelemetry(),
    )
    assert result["check_accepted"] is False
    assert result["model_calls"] == 4
    assert result["error_code"] == "structure"


def test_unexpected_failure_finalization_is_not_silently_swallowed(snapshot, caplog):
    class BrokenModel(ScriptedChatModel):
        def _generate(self, *args, **kwargs):
            raise ValidationError("proxy_quota", "fixture-sensitive-marker")

    store, service = service_for(snapshot, lambda role, mode: BrokenModel(role=role))
    submit(service, snapshot, "Health?")
    original_save = store.save_task

    def broken_save(task, *args, **kwargs):
        if task.state == "FAILED":
            raise RuntimeError("fixture-sensitive-marker")
        return original_save(task, *args, **kwargs)

    store.save_task = broken_save
    with pytest.raises(RuntimeError):
        service.run_once()
    assert "fixture-sensitive-marker" not in caplog.text
    assert service.health()["last_error"]["error_type"] == "ValidationError"


def located_snapshot(snapshot):
    from subsea_copilot.contracts import LocationCandidate, LocationFit, Point

    candidate = LocationCandidate(
        segment_id="P1",
        chainage_m=400,
        position=Point(x=400, y=0),
        residual=0.1,
        strength=10,
    )
    snapshot.event.eligible_location = True
    snapshot.location = LocationFit(
        status="located",
        best=candidate,
        compatible=[candidate],
        reason="Frozen computed fit.",
    )
    snapshot.evidence["location-e"] = EvidenceItem(
        id="location-e",
        kind="location",
        value=candidate.model_dump(mode="json"),
    )
    snapshot.claims["location"] = Claim(
        id="location",
        kind="location",
        value=snapshot.location.model_dump(mode="json"),
        evidence_ids=["location-e"],
    )
    return snapshot


def test_section_question_cannot_reuse_diagnosis_that_omitted_location(snapshot):
    import json

    from langchain_core.messages import SystemMessage

    class EventOnlyDiagnosis(ScriptedChatModel):
        def _generate(self, *args, **kwargs):
            result = super()._generate(*args, **kwargs)
            context = json.loads(
                next(
                    m.content.split("\nBOUND_CONTEXT\n", 1)[1]
                    for m in args[0]
                    if isinstance(m, SystemMessage)
                )
            )
            message = result.generations[0].message
            if not message.tool_calls and not context["requires_location"]:
                payload = json.loads(message.content)
                payload["claim_refs"] = [r for r in payload["claim_refs"] if r != "location"]
                payload["evidence_ids"] = [r for r in payload["evidence_ids"] if r != "location-e"]
                message.content = json.dumps(payload)
            return result

    snapshot = located_snapshot(snapshot)
    store, service = service_for(
        snapshot,
        lambda role, mode: (
            EventOnlyDiagnosis(role=role)
            if role == "event_diagnosis"
            else ScriptedChatModel(role=role)
        ),
        checkpointer=InMemorySaver(),
    )
    cause = submit(service, snapshot, "What caused this leak?", "cause")
    drain(service)
    assert store.get_task(cause.id).state == "SUCCEEDED"
    assert "location" not in store.get_task(cause.id).result.claim_refs
    section = submit(
        service,
        snapshot,
        "Which pipeline section should our integrity engineer inspect first, and why?",
        "section",
    )
    drain(service)
    answer = store.get_task(section.id)
    assert answer.state == "SUCCEEDED"
    assert answer.plan == ["quality", "diagnosis", "answer"]
    assert "location" in answer.result.claim_refs
    assert len(store.tasks) == 6


@pytest.mark.parametrize("behavior", ["extra_read", "malformed_final", "never_final"])
def test_prefetched_quality_handles_extra_round_and_repair_without_spending_final_turn(
    snapshot,
    behavior,
):
    import json

    from langchain_core.messages import SystemMessage

    class MultiRoundQuality(ScriptedChatModel):
        def _generate(self, *args, **kwargs):
            result = super()._generate(*args, **kwargs)
            context = json.loads(
                next(
                    m.content.split("\nBOUND_CONTEXT\n", 1)[1]
                    for m in args[0]
                    if isinstance(m, SystemMessage) and "\nBOUND_CONTEXT\n" in m.content
                )
            )
            constraints = json.loads(
                next(
                    m.content.split("RUNTIME_REPLY_CONSTRAINTS\n", 1)[1]
                    for m in reversed(args[0])
                    if isinstance(m, SystemMessage)
                    and m.content.startswith("RUNTIME_REPLY_CONSTRAINTS\n")
                )
            )
            remaining = constraints["model_turns_after_this_reply"]
            message = result.generations[0].message
            if behavior in {"malformed_final", "never_final"} and remaining == 8:
                payload = json.loads(message.content)
                payload["status"] = payload.pop("outcome")
                message.content = json.dumps(payload)
            elif (
                behavior == "extra_read"
                and remaining == 8
                or (behavior == "never_final" and remaining < 8)
            ):
                replacement = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": uuid4().hex,
                            "name": "quality.sensor_patterns",
                            "args": {**context["scope"], "offset": 0},
                        }
                    ],
                )
                replacement.response_metadata = message.response_metadata
                result.generations[0].message = replacement
            return result

    store, service = service_for(
        snapshot,
        lambda role, mode: (
            MultiRoundQuality(role=role)
            if role == "sensor_quality"
            else ScriptedChatModel(role=role)
        ),
        checkpointer=InMemorySaver(),
    )
    root = submit(service, snapshot, "What caused this leak?")
    drain(service)
    quality = next(t for t in store.tasks.values() if t.role == "sensor_quality")
    if behavior == "never_final":
        assert quality.error_code == "final_turn_reserved"
        assert quality.model_calls == 9
        assert quality.tool_calls == 11
        assert store.get_task(root.id).state == "FAILED"
    else:
        assert store.get_task(root.id).state == "SUCCEEDED"
        assert quality.model_calls == 2
        assert quality.tool_calls == (5 if behavior == "extra_read" else 4)
    assert sum(t.model_calls for t in store.tasks.values()) <= 10


def test_actual_s2_quality_decline_is_repaired_without_relaxing_event_abstention():
    import json

    from langchain_core.messages import SystemMessage

    from subsea_copilot.diagnostics import analyze_window
    from subsea_copilot.ingest import normalize_records
    from subsea_copilot.synthetic import generate_scenario

    class InitiallyDeclinesQuality(ScriptedChatModel):
        def _generate(self, *args, **kwargs):
            result = super()._generate(*args, **kwargs)
            constraints = json.loads(
                next(
                    m.content.split("RUNTIME_REPLY_CONSTRAINTS\n", 1)[1]
                    for m in reversed(args[0])
                    if isinstance(m, SystemMessage)
                    and m.content.startswith("RUNTIME_REPLY_CONSTRAINTS\n")
                )
            )
            if constraints["model_turns_after_this_reply"] == 8:
                payload = json.loads(result.generations[0].message.content)
                payload["outcome"] = "insufficient_evidence"
                result.generations[0].message.content = json.dumps(payload)
            return result

    source = generate_scenario("S2", duration_seconds=180)
    snapshot = analyze_window(
        source.pack,
        normalize_records(source.baseline, source.pack),
        normalize_records(source.records, source.pack),
        "generation",
        180,
        185,
        source.epoch,
    )
    store, service = service_for(
        snapshot,
        lambda role, mode: (
            InitiallyDeclinesQuality(role=role)
            if role == "sensor_quality"
            else ScriptedChatModel(role=role)
        ),
        checkpointer=InMemorySaver(),
    )
    root = submit(service, snapshot, "Possible leak or instrumentation issue?")
    drain(service)
    quality = next(t for t in store.tasks.values() if t.role == "sensor_quality")
    assert quality.state == "SUCCEEDED"
    assert quality.model_calls == 2
    answer = store.get_task(root.id)
    assert answer.state == "SUCCEEDED"
    assert answer.result.hypothesis == "sensor_or_telemetry_issue"


def test_read_evidence_bundle_is_scoped_and_contains_only_successful_reads(snapshot):
    import json

    from subsea_copilot.contracts import AgentResult, AgentTask, EngineerInterpretation
    from subsea_copilot.grounding import source_texts
    from subsea_copilot.interpretation import validate_interpretation
    from subsea_copilot.profiles import expanded_evidence
    from subsea_copilot.runtime.registry import REGISTRY
    from subsea_copilot.validation import read_evidence_reference

    pressure = EvidenceItem(
        id="pressure-bundle-e", kind="channel_summary", sensor_id="sensor",
        value={"recent_5s_pressure_drop_bar": 1.1, "recent_5s_period_seconds": [95, 100]},
    )
    unread = pressure.model_copy(update={"id": "unread-pressure-bundle-e"})
    snapshot.evidence.update({pressure.id: pressure, unread.id: unread})
    receipts = [{
        "name": "evidence.get", "result": {"evidence": {
            pressure.id: pressure.model_dump(mode="json"),
        }},
    }]
    task = AgentTask(
        id="bundle", root_id="bundle", generation_id=snapshot.generation_id,
        snapshot_id=snapshot.id, site_id=snapshot.site_id, role="operator_response",
        purpose=REGISTRY["operator_response"].purpose, question="What changed?",
        mode="live", deadline=utc_now(), response_protocol="engineer-v2",
    )
    reference = read_evidence_reference(snapshot.id, receipts)
    assert reference is not None
    result = AgentResult(
        outcome="supported", claim_refs=["health"], evidence_ids=["health-e"], limitations=[],
        interpretation=EngineerInterpretation(
            focus="root_cause",
            answer={"text": "The final five-second deficit is 1.1 bar.",
                    "references": [reference]},
            competing_causes=[{
                "cause": "leak", "stance": "possible",
                "text": "Pressure loss alone does not confirm a physical leak.",
                "references": [reference],
            }],
            follow_up_questions=["Is an independent pressure measurement available?"],
        ),
    )
    validate_interpretation(result, task, receipts)
    sources = source_texts(result, snapshot, receipts)
    original = {
        ref: item
        for group in json.loads(sources[reference])["evidence_groups"].values()
        for ref, item in expanded_evidence(group)["evidence"].items()
    }
    assert original[pressure.id] == pressure.model_dump(mode="json")
    assert unread.id not in original
    assert read_evidence_reference(snapshot.id + "-other", receipts) != reference
    for failed in ([], [{**receipts[0], "error": "context_budget_exceeded"}]):
        with pytest.raises(ValidationError, match="accepted claims"):
            validate_interpretation(result, task, failed)

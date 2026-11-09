"""Exercise incident-time retrieval and accepted handoffs with real PostgreSQL roles.

Scripted model fixtures test governance rather than hosted answer quality: future
records, wrong scopes, unread citations and changed grounding must fail closed.
"""

import json
import os
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg
import pytest

from subsea_copilot.budgets import BUDGET_MULTIPLIER
from subsea_copilot.casefile import build_casefile
from subsea_copilot.config import Settings
from subsea_copilot.contracts import AgentTask, EngineerInterpretation, ReplaySession, utc_now
from subsea_copilot.diagnostics import analyze_window
from subsea_copilot.grounding import (
    source_texts,
    validate_assessment,
    validate_review,
    validate_revision,
)
from subsea_copilot.history import read_history
from subsea_copilot.history_evaluation import fixed_history_baseline, history_answer_supported
from subsea_copilot.ingest import normalize_records
from subsea_copilot.interpretation import validate_interpretation
from subsea_copilot.investigation import validate_investigation
from subsea_copilot.llm.copilot_cli import CopilotCLIChatModel, ProviderError
from subsea_copilot.profiles import (
    compact_comparison,
    compact_documents,
    comparison_documents,
    comparison_sensors,
)
from subsea_copilot.runtime.checkpointer import postgres_checkpointer
from subsea_copilot.runtime.gateway import ToolGateway
from subsea_copilot.runtime.scripted import ScriptedChatModel
from subsea_copilot.runtime.workflow import AgentService
from subsea_copilot.store import Conflict, Store, migrate
from subsea_copilot.synthetic import EXTENDED_PACK_VERSION, SOURCE_VERSION, generate_scenario
from subsea_copilot.telemetry import Telemetry
from subsea_copilot.validation import ValidationError, compatible

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def settings():
    if not os.environ.get("SUBSEA_DB_ADMIN_PASSWORD"):
        pytest.skip("Requires the owned PostgreSQL environment.")
    configured = Settings.from_env()
    migrate(
        configured.admin_dsn,
        configured.app_password,
        configured.tools_password,
        configured.checkpoint_password,
    )
    return configured


class PromptBoundedScripted(ScriptedChatModel):
    runtime_dir: Path

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        wire = CopilotCLIChatModel(runtime_dir=self.runtime_dir)
        with patch("subsea_copilot.llm.copilot_cli.shutil.which", return_value=None):
            with pytest.raises(ProviderError) as failure:
                wire._generate(messages, tools=self.bound_schemas)
            if failure.value.code != "cli_missing":
                pytest.fail(
                    f"{self.role}: {failure.value.code}; "
                    f"message sizes={[len(m.content) for m in messages]}"
                )
        response = super()._generate(messages, stop, run_manager, **kwargs)
        message = response.generations[0].message
        context = json.loads(messages[0].content.split("\nBOUND_CONTEXT\n", 1)[1])
        if (
            self.role == "operator_response"
            and context["phase"] == "answer"
            and context["scope"]["pack_version"] == EXTENDED_PACK_VERSION
        ):
            candidate = json.loads(message.content)
            candidate["interpretation"]["answer"]["text"] = (
                "An independent inspection photograph confirms a pipe-wall crack."
            )
            message.content = json.dumps(candidate)
        if (
            self.role == "event_diagnosis"
            and '"network_pressure_table":{' in messages[0].content
            and not message.tool_calls
            and not any(m.type == "human" and '"repair"' in m.content for m in messages)
        ):
            candidate = json.loads(message.content)
            candidate["limitations"].append("unsupported_test_code")
            message.content = json.dumps(candidate)
        return response

    def _history_action(self, messages, outputs, context):
        action, review = super()._history_action(messages, outputs, context)
        if (
            action
            and action.tool_calls[0]["name"] == "history.read"
            and context.get("network_pressure_table")
        ):
            table = context["network_pressure_table"]
            ids = [row[0] for row in table["rows"]]
            arguments = {
                key: value
                for key, value in action.tool_calls[0]["args"].items()
                if key != "document_ids"
            }
            end = context["history_bounds"]["end_seconds"]
            for sensors in (ids[::14][:8],):
                action.tool_calls.append(
                    {
                        "name": "history.compare",
                        "id": uuid4().hex,
                        "args": {
                            **arguments,
                            "sensor_ids": sensors,
                            "start_seconds": end - 60,
                            "split_seconds": end - 30,
                            "end_seconds": end,
                        },
                    }
                )
        return action, review


@pytest.fixture(scope="module")
def investigated(settings):
    with Store(
        settings.database_dsn,
        tenant_id="history-test-" + uuid4().hex,
        tools_dsn=settings.tools_dsn,
        qualification=True,
    ) as store:
        telemetry = Telemetry(runtime_dir=settings.runtime_dir)
        try:
            with postgres_checkpointer(settings.checkpoint_dsn) as saver:
                service = AgentService(
                    store,
                    lambda role, mode: PromptBoundedScripted(
                        role=role, runtime_dir=settings.runtime_dir
                    ),
                    saver,
                    telemetry,
                )
                scenarios = {}
                for scenario in ("S1", "S2", "S4", "S5"):
                    source = generate_scenario(scenario, duration_seconds=180)
                    replay = store.create_replay(
                        ReplaySession(
                            id="history-" + uuid4().hex,
                            tenant_id=store.tenant_id,
                            scenario=scenario,
                            source_version=SOURCE_VERSION,
                            clock_seconds=185,
                            epoch=source.epoch,
                        )
                    )
                    rows = normalize_records(source.records, source.pack)
                    store.save_observations(replay.id, rows)
                    snapshot = store.save_window(
                        analyze_window(
                            source.pack,
                            normalize_records(source.baseline, source.pack),
                            rows,
                            replay.id,
                            180,
                            185,
                            source.epoch,
                            tenant_id=store.tenant_id,
                        )
                    )
                    root = service.submit_question(
                        replay,
                        snapshot,
                        "What evidence supports this, and what remains unknown?",
                        "history",
                    )
                    for _ in range(20):
                        if store.get_task(root.id).state in {"SUCCEEDED", "ABSTAINED", "FAILED"}:
                            break
                        assert service.run_once()
                    root = store.get_task(root.id)
                    assert root.state in {"SUCCEEDED", "ABSTAINED"}, (
                        root.error_code,
                        service.health(),
                    )
                    diagnosis = next(
                        task
                        for task in store.list_tasks(replay.id)
                        if task.role == "event_diagnosis"
                    )
                    scenarios[scenario] = (replay, snapshot, root, diagnosis)
                yield store, scenarios, telemetry
        finally:
            telemetry.close()


def test_fresh_history_execution_does_not_inherit_numerical_diagnoses(investigated):
    store, cases, _ = investigated
    expected = {
        "S1": "unresolved",
        "S2": "unresolved",
        "S4": "unresolved",
        "S5": "unresolved",
    }
    for scenario, (_, snapshot, root, diagnosis) in cases.items():
        assert root.result.investigation.assessment == expected[scenario]
        assert root.decision_policy == diagnosis.decision_policy == "llm-diagnosis-v1"
        assert root.result.hypothesis == "insufficient_evidence"
        assert root.state == "SUCCEEDED"
        assert root.result.investigation == diagnosis.result.investigation
        receipts = store.tool_receipts(diagnosis.id)
        assert {"history.search", "history.read", "history.compare"} <= {
            r["name"] for r in receipts
        }
        assert sum(t.model_calls for t in store.list_tasks(root.generation_id)) <= 10
        assert (
            sum(t.tool_calls for t in store.list_tasks(root.generation_id))
            <= 18 * BUDGET_MULTIPLIER
        )
        assert diagnosis.model_calls <= 4
        assert snapshot.event.hypothesis == (
            "suspected_leak"
            if scenario == "S1"
            else "sensor_or_telemetry_issue"
            if scenario == "S2"
            else "insufficient_evidence"
        )
        if scenario in {"S4", "S5"}:
            assert snapshot.location is None
    assert "OP-VALVE-001" in cases["S4"][2].answer


def test_extended_network_uses_its_own_corpus_and_versioned_pressure_history(settings):
    with Store(
        settings.database_dsn,
        tenant_id="extended-history-" + uuid4().hex,
        tools_dsn=settings.tools_dsn,
        qualification=True,
    ) as store:
        telemetry = Telemetry(runtime_dir=settings.runtime_dir)
        try:
            with postgres_checkpointer(settings.checkpoint_dsn) as saver:
                service = AgentService(
                    store,
                    lambda role, mode: PromptBoundedScripted(
                        role=role, runtime_dir=settings.runtime_dir
                    ),
                    saver,
                    telemetry,
                )
                source = generate_scenario("S7", duration_seconds=180)
                replay = store.create_replay(
                    ReplaySession(
                        id="extended-history-" + uuid4().hex,
                        tenant_id=store.tenant_id,
                        scenario="S7",
                        source_version=SOURCE_VERSION,
                        clock_seconds=145,
                        epoch=source.epoch,
                    )
                )
                rows = normalize_records(source.records, source.pack)
                store.save_observations(replay.id, rows)
                snapshot = store.save_window(
                    analyze_window(
                        source.pack,
                        normalize_records(source.baseline, source.pack),
                        rows,
                        replay.id,
                        140,
                        145,
                        source.epoch,
                        tenant_id=store.tenant_id,
                    )
                )
                root = service.submit_question(
                    replay, snapshot, "Where should we inspect, and why?", "extended-history"
                )
                for _ in range(20):
                    if store.get_task(root.id).state in {"SUCCEEDED", "ABSTAINED", "FAILED"}:
                        break
                    assert service.run_once()
                root = store.get_task(root.id)
                assert root.state == "SUCCEEDED", (root.error_code, service.health())
                assert len(root.interpretation_review.rounds) == 2
                tasks = store.list_tasks(replay.id)
                diagnosis = next(task for task in tasks if task.role == "event_diagnosis")
                assert diagnosis.model_calls <= 4
                receipts = store.tool_receipts(diagnosis.id)
                baseline_reads = [
                    receipt for receipt in receipts
                    if receipt["name"] == "evidence.get"
                    and any(
                        snapshot.evidence[identifier].kind == "channel_summary"
                        for identifier in receipt["arguments"]["ids"]
                    )
                ]
                assert {
                    identifier for receipt in baseline_reads
                    for identifier in receipt["arguments"]["ids"]
                } >= {
                    item.id for item in snapshot.evidence.values()
                    if item.kind == "channel_summary"
                }
                documents = [
                    document
                    for receipt in receipts
                    if receipt["name"] == "history.read"
                    for document in receipt["result"]["documents"]
                ]
                assert documents and all(
                    "EXTENDED" in document["id"] or "P7-GW" in document["id"]
                    for document in documents
                )
                comparison = next(r for r in receipts if r["name"] == "history.compare")
                assert comparison["result"]["sensors"]
                table = service._network_pressure_table(snapshot)
                assert table["total_instruments"] == len(table["rows"]) == 112
                assert len(comparison["result"]["joint_pattern"]["sensor_order"]) >= 2
                extended = read_history(
                    store,
                    diagnosis,
                    snapshot,
                    "history.compare",
                    {
                        **comparison["arguments"],
                        "sensor_ids": [s.id for s in source.pack.sensors[:8]],
                        "paired_only": True,
                    },
                )
                assert len(extended["sensors"]) == 8
                full = read_history(
                    store, diagnosis, snapshot, "history.compare",
                    {
                        **comparison["arguments"],
                        "sensor_ids": [s.id for s in source.pack.sensors[:8]],
                        "paired_only": False,
                    },
                )
                assert extended["sensors"] == full["sensors"]
                order = full["joint_pattern"]["sensor_order"]
                for pair in extended["joint_pattern"]["station_pairs"]:
                    i, j = (order.index(identifier) for identifier in pair["sensor_ids"])
                    for key in (
                        "pressure_correlation", "joint_usable_samples", "pipeline_distance_m",
                    ):
                        assert pair[key] == full["joint_pattern"][key][i][j]
                assert "station_pairs" not in full["joint_pattern"]
                assert len(json.dumps(extended).encode()) <= 12 * 1024
                compact = compact_comparison(extended)
                assert comparison_sensors(compact) == extended["sensors"]
                compact_records = compact_documents({"documents": documents})
                assert comparison_documents(compact_records) == documents
                assert (
                    len(
                        json.dumps(
                            {
                                **compact_records,
                                "comparisons": [compact, compact],
                            },
                            separators=(",", ":"),
                        ).encode()
                    )
                    < 12 * 1024
                )
                assert sum(task.model_calls for task in tasks) <= 10
                assert sum(task.tool_calls for task in tasks) <= 18 * BUDGET_MULTIPLIER
        finally:
            telemetry.close()


def test_frozen_extended_source_retains_time_and_asset_scoped_operating_records(
    settings, tmp_path, monkeypatch,
):
    from subsea_copilot.golden_evaluation import install_golden_input
    from subsea_copilot.monitoring import Monitor

    monkeypatch.setenv("SUBSEA_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("SUBSEA_TELEMETRY_ENABLED", "0")
    with Store(
        settings.database_dsn, tenant_id="frozen-history-" + uuid4().hex,
        tools_dsn=settings.tools_dsn, qualification=True,
    ) as store:
        telemetry = Telemetry(runtime_dir=tmp_path)
        try:
            service = AgentService(
                store, lambda role, mode: ScriptedChatModel(role=role), None, telemetry,
            )
            monitor = Monitor(store, service, telemetry)
            dataset = generate_scenario("S7", duration_seconds=180)
            replay = install_golden_input(monitor, dataset, "scripted", duration_seconds=180)
            snapshot = store.save_window(analyze_window(
                dataset.pack, normalize_records(dataset.baseline, dataset.pack),
                normalize_records(dataset.records, dataset.pack), replay.id, 150, 155,
                dataset.epoch, tenant_id=store.tenant_id,
            ))
            root = service.submit_question(
                replay, snapshot, "Rank the pressure concerns.", "frozen",
            )
            rows = store.history_documents(
                replay.id, root.history_version, snapshot.window_end,
                query="pressure calibration operating", assets=["P2", "P7"],
            )
            assert {"OP-P2-EXTENDED-001", "MAINT-P7-GW-002"} <= {row["id"] for row in rows}
            assert all(row["scenarios"] == [replay.scenario] for row in rows)
            before = store.history_documents(
                replay.id, root.history_version, dataset.epoch + timedelta(seconds=95),
                query="pressure calibration operating", assets=["P2", "P7"],
            )
            assert "OP-P2-EXTENDED-001" not in {row["id"] for row in before}
        finally:
            telemetry.close()


def test_operations_audit_checks_actual_handoffs_review_and_provenance(investigated):
    from subsea_copilot.operations_evaluation import audit_operations

    store, cases, _ = investigated
    for _, snapshot, root, _ in cases.values():
        audit = audit_operations(store, root, snapshot)
        assert all(audit["checks"].values()), audit["checks"]
        assert audit["fresh_model_calls"] == len(audit["model_receipts"])
        assert audit["critic_decisions"] == ["accept"]
        assert any(
            step["origin"] == "application_required_intake" for step in audit["tool_receipts"]
        )
        history = [step for step in audit["tool_receipts"] if step["name"].startswith("history.")]
        assert history
        intake = [step for step in history if step["origin"] == "application_required_intake"]
        assert len(intake) == 1 and intake[0]["name"] == "history.search"
        assert all(
            step["origin"] == "model_requested"
            for step in history if step not in intake
        )


def test_matched_fixed_report_does_not_read_agent_answer(investigated):
    from subsea_copilot.operations_evaluation import deterministic_report, report_rubric

    store, cases, _ = investigated
    for scenario, (_, snapshot, root, _) in cases.items():
        candidate = root.model_copy(update={"result": None, "answer": None})
        baseline = deterministic_report(store, candidate, snapshot, 2)
        assert baseline["model_calls"] == 0
        assert all(report_rubric(scenario, 2, baseline["report"]).values())
        assert baseline["report"]["physical_decision"] == snapshot.event.hypothesis


def test_future_documents_and_other_tenants_never_enter_retrieval(investigated, settings):
    store, cases, _ = investigated
    replay, snapshot, _, diagnosis = cases["S1"]
    visible = store.history_documents(
        replay.id,
        diagnosis.history_version,
        replay.epoch + timedelta(seconds=snapshot.clock_seconds),
        query="inspection OR leak OR pressure",
        assets=["northsea"],
    )
    assert "INC-INSPECTION-001" not in {doc["id"] for doc in visible}
    with pytest.raises(ValidationError, match="not visible"):
        read_history(
            store,
            diagnosis,
            snapshot,
            "history.read",
            {"document_ids": ["INC-INSPECTION-001"], "intent": "seek_counterevidence"},
        )
    with Store(
        settings.database_dsn,
        tenant_id="other-history-" + uuid4().hex,
        tools_dsn=settings.tools_dsn,
    ) as other:
        own = other.create_replay(
            ReplaySession(id="other-" + uuid4().hex, tenant_id=other.tenant_id, scenario="S1")
        )
        assert (
            other.history_documents(
                own.id,
                diagnosis.history_version,
                replay.epoch + timedelta(seconds=185),
                query="pressure",
                assets=["northsea"],
            )
            == []
        )
    with pytest.raises(
        (psycopg.errors.ReadOnlySqlTransaction, psycopg.errors.InsufficientPrivilege)
    ):
        with store._tx(read=True) as conn:
            conn.execute(
                "DELETE FROM subsea.history_documents WHERE corpus_version=%s",
                (diagnosis.history_version,),
            )


def test_stale_citations_fabricated_context_and_future_comparisons_are_rejected(investigated):
    store, cases, telemetry = investigated
    _, snapshot, root, diagnosis = cases["S4"]
    receipts = store.tool_receipts(diagnosis.id)
    stale = diagnosis.result.model_copy(deep=True)
    assert stale.investigation.rejected_document_ids
    stale.investigation.document_ids = stale.investigation.rejected_document_ids
    with pytest.raises(ValidationError, match="current approved"):
        validate_investigation(stale, diagnosis, snapshot, receipts)
    search_only = [
        {
            **receipt,
            "result": {
                **receipt["result"],
                "documents": [
                    document
                    for document in receipt["result"]["documents"]
                    if document["id"] not in diagnosis.result.investigation.rejected_document_ids
                ],
            },
        }
        if receipt["name"] == "history.read"
        else receipt
        for receipt in receipts
    ]
    with pytest.raises(ValidationError, match="read and non-authoritative"):
        validate_investigation(diagnosis.result, diagnosis, snapshot, search_only)
    forged = diagnosis.result.model_copy(deep=True)
    forged.investigation.comparison_call_ids = ["invented"]
    with pytest.raises(ValidationError, match="executed reads"):
        validate_investigation(forged, diagnosis, snapshot, receipts)
    with pytest.raises(ValidationError, match="bounded past range"):
        read_history(
            store,
            diagnosis,
            snapshot,
            "history.compare",
            {
                "intent": "seek_counterevidence",
                "sensor_ids": ["P1-ST1-A", "P2-ST1-A"],
                "start_seconds": 30,
                "split_seconds": 90,
                "end_seconds": 200,
            },
        )
    gateway = ToolGateway(store, diagnosis, snapshot, telemetry)
    with pytest.raises(ValidationError, match="scope"):
        gateway._authorize(
            "history.search",
            {
                "site_id": "another-site",
                "snapshot_id": snapshot.id,
                "pack_version": snapshot.pack_version,
                "baseline_version": snapshot.baseline_version,
                "parameter_version": snapshot.parameter_version,
                "intent": "seek_counterevidence",
                "query": "pressure",
                "asset_ids": ["northsea"],
            },
        )
    changed = root.model_copy(update={"history_version": "different-corpus"})
    with pytest.raises(Conflict):
        store.save_task(changed, root.version)


def test_future_arrivals_cannot_change_a_pinned_pressure_comparison(investigated):
    store, cases, _ = investigated
    replay, snapshot, _, diagnosis = cases["S4"]
    arguments = {
        "intent": "test_operating_change",
        "sensor_ids": ["P1-ST1-A", "P2-ST1-A"],
        "start_seconds": 30,
        "split_seconds": 90,
        "end_seconds": 180,
    }
    before = read_history(store, diagnosis, snapshot, "history.compare", arguments)
    original = next(
        row.original
        for row in store.observations(replay.id)
        if row.sensor_id == "P1-ST1-A" and row.observed_at == replay.epoch + timedelta(seconds=60)
    )
    future = original.model_copy(
        update={
            "value": 10.0,
            "unit": "bar",
            "source_record_id": "future-contradiction",
            "received_at": (replay.epoch + timedelta(seconds=260)).isoformat(),
        }
    )
    source = generate_scenario("S4", duration_seconds=180)
    store.save_observations(replay.id, normalize_records([future], source.pack))
    after = read_history(store, diagnosis, snapshot, "history.compare", arguments)
    assert after["input_hash"] == before["input_hash"]
    assert after["sensors"] == before["sensors"]


def test_frozen_fixed_workflow_is_separate_from_fresh_agent_contract_fixture(investigated):
    store, cases, _ = investigated
    for _, snapshot, root, diagnosis in cases.values():
        baseline = fixed_history_baseline(store, diagnosis, snapshot, quality_aware=True)
        assert root.result.investigation.assessment == "unresolved"
        assert baseline["model_calls"] == 0
        assert baseline["guard_error"] is None


def test_natural_keyword_queries_find_operating_records_without_all_words_matching(investigated):
    store, cases, _ = investigated
    _, snapshot, _, diagnosis = cases["S4"]
    result = read_history(
        store,
        diagnosis,
        snapshot,
        "history.search",
        {
            "intent": "test_operating_change",
            "asset_ids": ["P1", "P2", "P3"],
            "query": (
                "Approved incident-time valve compressor operating logs "
                "explaining common-mode pressure change"
            ),
        },
    )
    assert "OP-VALVE-001" in {doc["id"] for doc in result["documents"]}
    assert " OR " in result["executed_query"]


def test_segment_search_includes_maintenance_on_its_instruments(investigated):
    store, cases, _ = investigated
    _, snapshot, _, diagnosis = cases["S2"]
    result = read_history(
        store,
        diagnosis,
        snapshot,
        "history.search",
        {"intent": "test_instrumentation", "asset_ids": ["P1"], "query": "maintenance calibration"},
    )
    assert "MAINT-CAL-P1-002" in {doc["id"] for doc in result["documents"]}


def test_legacy_maintenance_guard_preserves_archived_quality_concern_policy(investigated):
    store, cases, _ = investigated
    _, snapshot, _, diagnosis = cases["S2"]
    receipts = store.tool_receipts(diagnosis.id)
    review = diagnosis.result.model_copy(deep=True)
    clean = [s["id"] for s in AgentService._history_sensors(snapshot) if not s["quality_concern"]][
        :2
    ]
    assert len(clean) == 2
    comparison = read_history(
        store,
        diagnosis,
        snapshot,
        "history.compare",
        {
            "intent": "test_instrumentation",
            "sensor_ids": clean,
            "start_seconds": 30,
            "split_seconds": 90,
            "end_seconds": 180,
        },
    )
    receipts.append(
        {"name": "history.compare", "call_id": "unrelated", "result": comparison, "error": None}
    )
    review.investigation.comparison_call_ids = ["unrelated"]
    review.investigation.assessment = "instrumentation_context"
    diagnosis = diagnosis.model_copy(update={"decision_policy": "legacy-v1"})
    with pytest.raises(ValidationError, match="match compared instruments") as rejection:
        validate_investigation(review, diagnosis, snapshot, receipts)
    assert rejection.value.details["comparison_call_ids"] == ["unrelated"]
    assert rejection.value.details["compared_assets"] == []
    assert rejection.value.details["maintenance_documents"]


def test_unresolved_review_cannot_ignore_current_search_hits(investigated):
    store, cases, _ = investigated
    _, snapshot, _, diagnosis = cases["S4"]
    review = diagnosis.result.model_copy(deep=True)
    review.investigation.assessment = "unresolved"
    review.investigation.document_ids = []
    review.investigation.rejected_document_ids = []
    review.investigation.comparison_call_ids = []
    receipts = [row for row in store.tool_receipts(diagnosis.id) if row["name"] != "history.read"]
    with pytest.raises(ValidationError, match="require a document read"):
        validate_investigation(review, diagnosis, snapshot, receipts)


def test_telemetry_context_is_not_a_physical_leak_clearance(investigated):
    _, cases, _ = investigated
    result = cases["S5"][2].result.model_copy(deep=True)
    result.outcome = "insufficient_evidence"
    result.hypothesis = None
    result.investigation.next_action = "restore_telemetry"
    for assessment in ("unresolved", "instrumentation_context"):
        result.investigation.assessment = assessment
        assert history_answer_supported("S5", result, "ABSTAINED")
        assert not history_answer_supported("S5", result, "SUCCEEDED")
    result.investigation.next_action = "inspect_supported_interval"
    assert not history_answer_supported("S5", result, "ABSTAINED")


def test_engineer_interpretation_is_separate_cited_and_response_only(investigated):
    store, cases, _ = investigated
    _, _, root, diagnosis = cases["S4"]
    assert root.response_protocol == "engineer-v2"
    assert root.interpretation_review.rounds[-1].assessment.decision == "accept"
    assert root.result.interpretation is not None
    assert root.answer.index("ENGINEER QUESTION") < root.answer.index("CHECKED EVIDENCE")
    assert "ENGINEERING ASSESSMENT" in root.answer
    assert "wording is not independently verified RCA" not in root.answer
    forged = root.result.model_copy(deep=True)
    forged.interpretation.answer.references = ["invented-document"]
    with pytest.raises(ValidationError, match="reviewed history"):
        validate_interpretation(forged, root)
    with pytest.raises(ValidationError, match="Only the response role"):
        validate_interpretation(root.result, diagnosis)
    missing = root.result.model_copy(update={"interpretation": None})
    with pytest.raises(ValidationError, match="engineer"):
        validate_interpretation(missing, root)
    legacy = root.model_copy(update={"response_protocol": None})
    validate_interpretation(missing, legacy)
    with pytest.raises(Conflict):
        store.save_task(legacy, root.version)


def test_engineer_followups_are_questions_not_unbounded_commands(investigated):
    _, cases, _ = investigated
    root = cases["S4"][2]
    invalid = root.result.model_copy(deep=True)
    invalid.interpretation.follow_up_questions = ["Close the valve now."]
    with pytest.raises(ValidationError, match="verification questions"):
        validate_interpretation(invalid, root)
    schema = EngineerInterpretation.model_json_schema()
    assert schema["properties"]["follow_up_questions"]["items"]["maxLength"] == 200
    fields = root.result.interpretation.model_dump()
    fields["follow_up_questions"] = ["x" * 200 + "?"]
    with pytest.raises(ValueError, match="200 characters"):
        EngineerInterpretation.model_validate(fields)


def test_knowledge_is_pinned_inherited_and_applied_to_case_evidence(investigated):
    store, cases, _ = investigated
    for _, snapshot, root, diagnosis in cases.values():
        assert root.knowledge_packet.cards
        assert diagnosis.knowledge_packet == root.knowledge_packet
        assert root.knowledge_packet.selected_at > snapshot.window_end
        assert root.result.interpretation.regional_assessments
        sources = source_texts(
            root.result, snapshot, store.tool_receipts(root.id), root.knowledge_packet
        )
        assert root.knowledge_packet.cards[0].id in sources
        forged = root.model_copy(
            update={
                "knowledge_packet": root.knowledge_packet.model_copy(
                    update={"selected_at": root.knowledge_packet.selected_at + timedelta(seconds=1)}
                )
            }
        )
        with pytest.raises(Conflict, match="task_identity_conflict"):
            store.save_task(forged, root.version)
        knowledge_only = root.result.model_copy(deep=True)
        knowledge_only.interpretation.answer.references = [root.knowledge_packet.cards[0].id]
        with pytest.raises(ValidationError, match="case evidence"):
            validate_interpretation(knowledge_only, root)
        unapplied = root.result.model_copy(deep=True)
        for paragraph in unapplied.interpretation.cited_paragraphs():
            paragraph.references = [
                ref for ref in paragraph.references if not ref.startswith("KN-")
            ]
        with pytest.raises(ValidationError, match="at least one pinned"):
            validate_interpretation(unapplied, root)
        knowledge_quote_only = root.interpretation_review.rounds[-1].assessment.model_copy(
            deep=True
        )
        knowledge_quote_only.checks[0].support = [
            support
            for support in knowledge_quote_only.checks[0].support
            if support.reference.startswith("KN-")
        ]
        with pytest.raises(ValidationError, match="both knowledge and case"):
            validate_assessment(knowledge_quote_only, root.result, sources)
        assert compatible(root, diagnosis, snapshot)
        changed_knowledge = diagnosis.model_copy(update={"knowledge_packet": None})
        assert not compatible(root, changed_knowledge, snapshot)
        forged_group = root.result.model_copy(deep=True)
        forged_group.interpretation.regional_assessments[0].sensor_ids[0] = "UNOBSERVED-SENSOR"
        with pytest.raises(ValidationError, match="their cited executed comparisons"):
            validate_interpretation(forged_group, root, store.tool_receipts(root.id))


def test_database_itself_fences_packet_mutation_and_wrong_child_inheritance(investigated):
    store, cases, _ = investigated
    replay, snapshot, original, _ = cases["S1"]
    identifier = "knowledge-pin-" + uuid4().hex
    root = store.create_task(
        AgentTask(
            id=identifier,
            root_id=identifier,
            generation_id=replay.id,
            tenant_id=store.tenant_id,
            site_id=store.site_id,
            snapshot_id=snapshot.id,
            role="operator_response",
            purpose=original.purpose,
            question="Pin test",
            mode="scripted",
            deadline=utc_now() + timedelta(seconds=299),
            knowledge_packet=original.knowledge_packet,
        )
    )
    claimed = store.claim_task("knowledge-pin-test", task_id=root.id)
    assert claimed is not None
    with pytest.raises(Conflict, match="task_identity_conflict"):
        with store._tx(token=claimed.lease_token) as conn:
            store._update_task(conn, claimed.model_copy(update={"knowledge_packet": None}))
    child = claimed.model_copy(
        update={
            "id": "knowledge-child-" + uuid4().hex,
            "parent_id": claimed.id,
            "role": "sensor_quality",
            "purpose": "assess_sensor_quality",
            "state": "QUEUED",
            "knowledge_packet": None,
            "version": 1,
        }
    )
    with pytest.raises(Conflict, match="task_identity_conflict"):
        store.create_child(child, 0, lease_token=claimed.lease_token)
    assert store.get_task(root.id).knowledge_packet == original.knowledge_packet
    store.save_task(claimed.model_copy(update={"state": "CANCELLED"}), claimed.version)


def test_scripted_paired_ablation_keeps_identical_measurements_and_separate_knowledge(settings):
    from subsea_copilot.knowledge_evaluation import qualify_knowledge

    report = qualify_knowledge("scripted")
    assert report["passed"] and report["matching_input_hashes"]
    off, on = report["arms"]
    assert off["casefile"]["knowledge_packet"] is None
    assert on["casefile"]["knowledge_used_ids"]
    assert off["casefile"]["inspection"] == on["casefile"]["inspection"]
    assert off["numerical_hypothesis"] == on["numerical_hypothesis"]


@pytest.mark.parametrize(
    "tamper", ["missing", "candidate", "source", "quote", "coverage", "decision"]
)
def test_current_reports_require_exact_complete_grounding_attestation(investigated, tamper):
    store, cases, _ = investigated
    _, snapshot, original, _ = cases["S4"]
    root = original.model_copy(deep=True)
    receipts = store.tool_receipts(root.id)
    validate_review(root.result, root, snapshot, receipts)
    if tamper == "missing":
        root.interpretation_review = None
    elif tamper == "candidate":
        root.result.interpretation.answer.text = (
            "An independent inspection photograph confirms a pipe-wall crack."
        )
    elif tamper == "source":
        root.interpretation_review.source_hash = "forged"
    else:
        final = root.interpretation_review.rounds[-1].assessment
        if tamper == "quote":
            final.checks[0].support[0].quote = "A nonexistent inspection confirms the crack."
        elif tamper == "coverage":
            final.checks[-1] = final.checks[0]
        else:
            final.checks[0].verdict = "uncertain"
    with pytest.raises(ValidationError):
        validate_review(root.result, root, snapshot, receipts)


def test_uncertain_critic_withholds_report_after_three_distinct_revisions(investigated):
    store, cases, telemetry = investigated
    _, snapshot, original, _ = cases["S4"]
    root = original.model_copy(deep=True)
    root.state = "RUNNING"
    root.interpretation_review = None
    assessment = original.interpretation_review.rounds[-1].assessment.model_copy(deep=True)
    assessment.decision = "revise"
    assessment.checks[0].verdict = "uncertain"
    assessment.checks[0].reason = "A valve command does not prove a physical movement."
    validate_assessment(
        assessment,
        root.result,
        source_texts(root.result, snapshot, store.tool_receipts(root.id), root.knowledge_packet),
    )
    phases = []

    def phase(
        task, _snapshot, name, candidate=None, criticism=None, previous_candidate=None
    ):
        phases.append(name)
        if name.startswith("reflection"):
            assert criticism.checks[0].reason == assessment.checks[0].reason
            return candidate.model_dump(), task
        return assessment.model_dump(), task

    service = AgentService(store, lambda role, mode: ScriptedChatModel(role=role), None, telemetry)
    with patch.object(service, "_graph", side_effect=phase):
        with pytest.raises(ValidationError, match="report withheld"):
            service._review_interpretation(root, snapshot, root.result)
    assert phases == [
        "critic-0", "reflection", "critic-1", "reflection-1",
        "critic-2", "reflection-2", "critic-3",
    ]
    assert root.interpretation_review is None


def test_grounding_checkpoint_reopens_without_new_model_calls(investigated):
    store, cases, telemetry = investigated
    _, snapshot, original, _ = cases["S4"]
    root = original.model_copy(deep=True)
    with postgres_checkpointer(Settings.from_env().checkpoint_dsn) as saver:
        service = AgentService(
            store, lambda role, mode: pytest.fail("No fresh model needed"), saver, telemetry
        )
        parsed, _ = service._graph(root, snapshot, "critic-0", candidate=root.result)
    assert parsed == root.interpretation_review.rounds[-1].assessment.model_dump()


def test_reflection_cannot_rewrite_checked_physical_or_history_findings(investigated):
    _, cases, _ = investigated
    result = cases["S4"][2].result
    revised = result.model_copy(deep=True)
    revised.interpretation.answer.text = "Operating context is plausible, not confirmed."
    validate_revision(result, revised)
    revised.investigation.assessment = "operating_change_plausible"
    with pytest.raises(ValidationError, match="interpretation only"):
        validate_revision(result, revised)


def test_response_receives_actual_reviewed_sources_not_just_identifiers(investigated):
    store, cases, _ = investigated
    _, _, root, diagnosis = cases["S4"]
    intake = next(
        receipt["result"]
        for receipt in store.tool_receipts(root.id)
        if receipt["name"] == "task.result" and receipt["arguments"]["task_id"] == diagnosis.id
    )
    context = intake["reviewed_context"]
    documents = context["documents"]
    assert {document["id"] for document in documents} == set(
        diagnosis.result.investigation.document_ids
    )
    actual_reads = [
        document
        for receipt in store.tool_receipts(diagnosis.id)
        if receipt["name"] == "history.read" and not receipt.get("error")
        for document in receipt["result"]["documents"]
        if document["id"] in diagnosis.result.investigation.document_ids
    ]
    assert documents == actual_reads
    assert any("valve" in str(document).lower() for document in documents)
    assert {comparison["call_id"] for comparison in context["comparisons"]} == set(
        diagnosis.result.investigation.comparison_call_ids
    )


def test_casefile_retains_the_accepted_decision_sources_and_physical_abstention(investigated):
    store, cases, telemetry = investigated
    for scenario, (_, snapshot, root, diagnosis) in cases.items():
        dependencies = ToolGateway(store, root, snapshot, telemetry).dependencies()
        receipts = [
            {"task_id": diagnosis.id, **receipt}
            for receipt in store.tool_receipts(diagnosis.id)
            if receipt["name"].startswith("history.")
        ]
        handoff = build_casefile(root, snapshot, dependencies, receipts)
        assert handoff.snapshot_id == root.snapshot_id
        assert handoff.input_hash == snapshot.input_hash
        assert handoff.interpretation == root.result.interpretation
        assert handoff.provider_cost_usd is None
        assert {
            source.document["id"] for source in handoff.sources if source.use == "cited"
        } == set(root.result.investigation.document_ids)
        assert handoff.fresh_model_calls == root.model_calls + sum(
            task.model_calls for task in dependencies if task.parent_id == root.id
        )
        if scenario == "S1":
            on_target = root.model_copy(
                update={"updated_at": root.created_at + timedelta(seconds=900)}
            )
            late = root.model_copy(
                update={"updated_at": root.created_at + timedelta(seconds=900.001)}
            )
            assert build_casefile(on_target, snapshot, dependencies, receipts).report_target_met
            assert not build_casefile(late, snapshot, dependencies, receipts).report_target_met
            archived = late.model_copy(update={
                "deadline": root.created_at + timedelta(seconds=300),
                "updated_at": root.created_at + timedelta(seconds=300.001),
            })
            archived_case = build_casefile(archived, snapshot, dependencies, receipts)
            assert archived_case.report_target_seconds == 300
            assert not archived_case.report_target_met
        assert handoff.inspection is None
        assert handoff.decision_policy == "llm-diagnosis-v1"
        assert handoff.state == "SUCCEEDED"
    root = cases["S4"][2]
    with pytest.raises(ValidationError, match="completed"):
        build_casefile(root.model_copy(update={"state": "FAILED"}), cases["S4"][1], [], [])


def test_casefile_cannot_export_unread_sources_or_inherit_an_uncited_location(investigated):
    store, cases, telemetry = investigated
    _, snapshot, root, diagnosis = cases["S1"]
    dependencies = ToolGateway(store, root, snapshot, telemetry).dependencies()
    with pytest.raises(ValidationError, match="source reads"):
        build_casefile(root, snapshot, dependencies, [])
    receipts = [
        {"task_id": diagnosis.id, **receipt}
        for receipt in store.tool_receipts(diagnosis.id)
        if receipt["name"].startswith("history.")
    ]
    uncited = root.model_copy(deep=True)
    uncited.result.claim_refs = uncited.result.claim_refs[1:]
    with pytest.raises(ValidationError, match="accepted review"):
        build_casefile(uncited, snapshot, dependencies, receipts)
    uncited.response_protocol = "engineer-v1"
    uncited.interpretation_review = None
    assert build_casefile(uncited, snapshot, dependencies, receipts).inspection is None
    forged = [{**receipt, "task_id": "unlinked-specialist"} for receipt in receipts]
    with pytest.raises(ValidationError, match="linked source"):
        build_casefile(root, snapshot, dependencies, forged)


@pytest.mark.parametrize("repair_allowed", [True, False])
def test_fabricated_assertion_is_revised_and_reviewed_with_persisted_budget(
    investigated, repair_allowed
):
    import json

    store, cases, telemetry = investigated
    replay, snapshot, _, _ = cases["S4"]

    class FabricatingAuthor(ScriptedChatModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            output = super()._generate(messages, stop, run_manager, **kwargs)
            context = json.loads(messages[0].content.split("\nBOUND_CONTEXT\n", 1)[1])
            if context.get("unchanged_previously_grounded_units"):
                assert set(context["candidate_paragraphs"]) == {"answer"}
                assert set(context["source_texts"]) == set(
                    context["candidate_paragraphs"]["answer"]["references"]
                )
            if context["phase"].startswith("reflection"):
                assert context["source_texts"]
                assert context["revision_targets"]["answer"]["text"]
                assert "candidate_paragraphs" not in context
                assert "pressure_summary_contract" in context
                assert not any(
                    isinstance(message.content, str)
                    and message.content.startswith('{"application_intake":')
                    for message in messages
                )
            if self.role == "operator_response" and (
                context["phase"] == "answer"
                or context["phase"] == "reflection"
                and not repair_allowed
            ):
                message = output.generations[0].message
                result = json.loads(message.content)
                fabricated = {
                    "text": "An independent inspection photograph confirms a pipe-wall crack.",
                    "references": ["OP-VALVE-001"],
                }
                if context["phase"] == "reflection":
                    next(
                        revision for revision in result["revisions"]
                        if revision["paragraph_id"] == "answer"
                    ).update(fabricated)
                else:
                    result["interpretation"]["answer"] = fabricated
                message.content = json.dumps(result)
            return output

    with postgres_checkpointer(Settings.from_env().checkpoint_dsn) as saver:
        service = AgentService(
            store, lambda role, mode: FabricatingAuthor(role=role), saver, telemetry
        )
        root = service.submit_question(
            replay,
            snapshot,
            "What evidence supports this operating change?",
            f"revision-regression-{repair_allowed}",
        )
        for _ in range(10):
            service.run_once()
            root = store.get_task(root.id)
            if root.state in {"SUCCEEDED", "ABSTAINED", "FAILED"}:
                break
    assert root.model_calls == (5 if repair_allowed else 9)
    if not repair_allowed:
        assert root.state == "FAILED"
        assert root.error_code == "grounding_rejected"
        assert root.result is None and root.answer is None
        assert root.interpretation_review is None
        return
    assert root.state == "SUCCEEDED", (root.error_code, service.health())
    assert [r.assessment.decision for r in root.interpretation_review.rounds] == [
        "revise",
        "accept",
    ]
    assert "photograph" not in root.answer
    assert [r["phase"] for r in store.list_model_calls(root.id)].count("reflection") == 1

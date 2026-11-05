"""Run only against explicitly configured, independently owned PostgreSQL roles."""

import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Event

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from subsea_copilot import store as store_module
from subsea_copilot.config import Settings
from subsea_copilot.contracts import (
    AgentResult,
    AgentTask,
    CanonicalObservation,
    EventAssessment,
    MonitoringEpisode,
    QualityReport,
    RawRecord,
    ReplaySession,
    WindowSnapshot,
    utc_now,
)
from subsea_copilot.store import (
    BudgetExceeded,
    Conflict,
    NotFound,
    QueueFull,
    ScopeError,
    Store,
    migrate,
)

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def settings() -> Settings:
    required = [
        "SUBSEA_DB_ADMIN_PASSWORD",
        "SUBSEA_DB_APP_PASSWORD",
        "SUBSEA_DB_TOOL_PASSWORD",
        "SUBSEA_DB_CHECKPOINT_PASSWORD",
        "SUBSEA_OPERATOR_PASSWORD",
    ]
    if any(not os.environ.get(name) for name in required):
        pytest.skip("Real PostgreSQL integration requires independently bootstrapped SUBSEA_DB_*")
    configured = Settings.from_env()
    migrate(
        configured.admin_dsn,
        configured.app_password,
        configured.tools_password,
        configured.checkpoint_password,
    )
    return configured


@pytest.fixture
def store(settings: Settings):
    # Keep evidence and budget history; each test gets an isolated synthetic tenant.
    with Store(
        settings.database_dsn,
        tenant_id=f"test-{uuid.uuid4().hex}",
        tools_dsn=settings.tools_dsn,
    ) as result:
        yield result


@pytest.fixture
def provider_settings(settings: Settings):
    # Global provider state is tested in an owned database, never reset in a
    # running application's database or while another cohort is using it.
    database = f"subsea_provider_test_{uuid.uuid4().hex}"
    with psycopg.connect(settings.admin_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        isolated = replace(
            settings,
            admin_dsn=make_conninfo(settings.admin_dsn, dbname=database),
            database_dsn=make_conninfo(settings.database_dsn, dbname=database),
            tools_dsn=make_conninfo(settings.tools_dsn, dbname=database),
            checkpoint_dsn=make_conninfo(settings.checkpoint_dsn, dbname=database),
        )
        try:
            migrate(
                isolated.admin_dsn,
                isolated.app_password,
                isolated.tools_password,
                isolated.checkpoint_password,
            )
            yield isolated
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))


def replay(store: Store, id: str = "generation") -> ReplaySession:
    return store.create_replay(
        ReplaySession(id=id, tenant_id=store.tenant_id, scenario="steady_normal")
    )


def window(store: Store, generation_id: str = "generation", **updates: object) -> WindowSnapshot:
    values = {
        "id": "window",
        "tenant_id": store.tenant_id,
        "site_id": store.site_id,
        "generation_id": generation_id,
        "window_start": datetime(2026, 1, 1, tzinfo=UTC),
        "window_end": datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=60),
        "end_seconds": 60,
        "input_hash": "test-hash",
        "pack_version": "pack-v1",
        "clock_seconds": 65,
        "watermark_seconds": 60,
        "canonical_count": 0,
        "quality": QualityReport(
            status="WARMING_UP",
            expected_samples=1,
            received_samples=0,
            usable_samples=0,
            coverage=0,
            failure_domains_available=0,
            findings=[],
        ),
        "event": EventAssessment(hypothesis="insufficient_evidence", eligible_hypotheses=[]),
    }
    values.update(updates)
    return WindowSnapshot.model_validate(values)


def root(store: Store, id: str = "root", **updates: object) -> AgentTask:
    values = {
        "id": id,
        "root_id": id,
        "tenant_id": store.tenant_id,
        "site_id": store.site_id,
        "generation_id": "generation",
        "snapshot_id": "window",
        "role": "operator_response",
        "purpose": "operator_question",
        "question": "Explain coverage",
        "mode": "scripted",
        "deadline": utc_now() + timedelta(seconds=299),
    }
    values.update(updates)
    return AgentTask.model_validate(values)


def test_real_roles_forced_tenant_site_and_checkpoint_boundary(
    settings: Settings, store: Store
) -> None:
    replay(store)
    store.save_window(window(store))
    with psycopg.connect(settings.database_dsn) as conn:
        row = conn.execute(
            "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
        ).fetchone()
        assert row == (False, False)
        assert conn.execute("SELECT count(*) FROM subsea.windows").fetchone() == (0,)
        conn.execute("SELECT set_config('subsea.tenant_id',%s,true)", (store.tenant_id,))
        conn.execute("SELECT set_config('subsea.site_id','wrong-site',true)")
        assert conn.execute("SELECT count(*) FROM subsea.windows").fetchone() == (0,)
        conn.execute("SELECT set_config('subsea.site_id',%s,true)", (store.site_id,))
        assert conn.execute("SELECT count(*) FROM subsea.windows").fetchone() == (1,)
        with conn.transaction():
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with conn.transaction():
                    conn.execute(
                        "INSERT INTO subsea.replays (tenant_id,site_id,id,payload,version)"
                        " VALUES ('other','northsea','forbidden','{}',1)"
                    )
    with Store(settings.database_dsn, tenant_id="other") as wrong:
        with pytest.raises(NotFound):
            wrong.get_window("window")
    with Store(settings.database_dsn, tenant_id=store.tenant_id, site_id="other") as wrong:
        with pytest.raises(NotFound):
            wrong.get_replay("generation")
        with pytest.raises(NotFound):
            wrong.events("generation")
    with pytest.raises(ScopeError):
        store.save_window(window(store, tenant_id="other"))
    with psycopg.connect(settings.tools_dsn) as conn:
        conn.execute("SELECT set_config('subsea.tenant_id',%s,true)", (store.tenant_id,))
        conn.execute("SELECT set_config('subsea.site_id',%s,true)", (store.site_id,))
        assert conn.execute("SELECT count(*) FROM subsea.windows").fetchone() == (1,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE subsea.replays SET version=version+1")
    with psycopg.connect(settings.checkpoint_dsn) as conn:
        assert conn.execute("SELECT current_schema()").fetchone() == ("subsea_checkpoint",)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM subsea.windows")


def test_observation_replay_conflicts_retain_originals(store: Store) -> None:
    replay(store)
    at = datetime(2026, 1, 1, tzinfo=UTC)
    raw = RawRecord(
        sensor_id="sensor",
        channel="acoustic",
        observed_at=at.isoformat(),
        received_at=at.isoformat(),
        value=1,
        unit="normalized",
        source_record_id="record",
    )
    observed = CanonicalObservation(
        id="observation",
        identity="same-source-identity",
        sensor_id="sensor",
        channel="acoustic",
        observed_at=at,
        received_at=at,
        value=1,
        unit="normalized",
        validity="usable",
        source_id="gateway",
        source_record_id="record",
        original=raw,
    )
    store.save_observations("generation", [observed, observed])
    assert len(store.observations("generation")) == 1
    other = observed.model_copy(
        update={
            "original": raw.model_copy(update={"value": 2.0}),
            "value": 2.0,
        }
    )
    store.save_observations("generation", [other])
    saved = store.observations("generation", start=at, end=at + timedelta(seconds=1))
    assert len(saved) == 2
    assert {item.original.value for item in saved} == {1, 2}
    assert all(item.validity == "conflicted" and item.value is None for item in saved)
    assert store.observations("generation", end=at) == []


def test_observation_preparation_does_not_hold_generation_fence(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    replay(store)
    at = datetime(2026, 1, 1, tzinfo=UTC)
    original = RawRecord(
        sensor_id="sensor",
        channel="acoustic",
        observed_at=at.isoformat(),
        received_at=at.isoformat(),
        value=1.0,
        unit="a.u.",
        source_record_id="record",
    )
    record = CanonicalObservation(
        id="record",
        identity="record",
        sensor_id="sensor",
        channel="acoustic",
        observed_at=at,
        received_at=at,
        value=1.0,
        unit="a.u.",
        validity="usable",
        source_id="synthetic-gateway",
        source_record_id="record",
        original=original,
    )
    preparing, release = Event(), Event()
    original_hash = store_module.content_hash

    def slow_hash(value):
        if not preparing.is_set():
            preparing.set()
            assert release.wait(10)
        return original_hash(value)

    monkeypatch.setattr(store_module, "content_hash", slow_hash)
    with ThreadPoolExecutor(max_workers=2) as executor:
        ingest = executor.submit(store.save_observations, "generation", [record])
        try:
            assert preparing.wait(5)
            event = executor.submit(
                store.publish_event, "generation", "health.changed", {"responsive": True}
            ).result(timeout=3)
            assert event.type == "health.changed"
        finally:
            release.set()
        ingest.result(timeout=10)
    assert store.observations("generation") == [record]


def test_observation_chunks_release_generation_fence_and_retry_idempotently(
    store: Store, settings: Settings
) -> None:
    replay(store)
    at = datetime(2026, 1, 1, tzinfo=UTC)
    template = CanonicalObservation(
        id="record",
        identity="record",
        sensor_id="sensor",
        channel="acoustic",
        observed_at=at,
        received_at=at,
        value=1.0,
        unit="a.u.",
        validity="usable",
        source_id="synthetic-gateway",
        source_record_id="record",
        original=RawRecord(
            sensor_id="sensor",
            channel="acoustic",
            observed_at=at.isoformat(),
            received_at=at.isoformat(),
            value=1.0,
            unit="a.u.",
            source_record_id="record",
        ),
    )
    records = [
        template.model_copy(
            update={
                "id": f"record-{n}",
                "identity": f"record-{n}",
                "source_record_id": f"record-{n}",
                "original": template.original.model_copy(
                    update={"source_record_id": f"record-{n}"}
                ),
            }
        )
        for n in range(1500)
    ]
    between_chunks, release = Event(), Event()

    class GatedStore(Store):
        chunk_calls = 0

        def _generation(self, conn, generation_id):
            self.chunk_calls += 1
            if self.chunk_calls == 2:
                between_chunks.set()
                assert release.wait(10)
            return super()._generation(conn, generation_id)

    with (
        GatedStore(settings.database_dsn, tenant_id=store.tenant_id) as ingest_store,
        ThreadPoolExecutor(max_workers=1) as executor,
    ):
        ingest = executor.submit(ingest_store.save_observations, "generation", records)
        try:
            assert between_chunks.wait(5)
            assert 0 < len(store.observations("generation")) < len(records)
            store.publish_event("generation", "health.changed", {"responsive": True})
        finally:
            release.set()
        ingest.result(timeout=10)
        ingest_store.save_observations("generation", records)
    assert len(store.observations("generation")) == len(records)


def test_immutable_window_events_controls_and_coherent_projection(
    settings: Settings, store: Store
) -> None:
    session = replay(store)
    snapshot = store.save_window(window(store))
    cursor = store.newest_event_id("generation")
    assert store.save_window(snapshot) == snapshot
    assert store.newest_event_id("generation") == cursor
    with pytest.raises(Conflict):
        store.save_window(snapshot.model_copy(update={"input_hash": "changed"}))
    revised = snapshot.model_copy(
        update={
            "id": "revision",
            "revision": 2,
            "predecessor_id": "window",
            "input_hash": "new",
        }
    )
    store.save_window(revised)
    assert store.list_windows("generation") == [revised]
    saved = store.save_controlled_replay(
        session.model_copy(update={"state": "PLAYING", "latest_window_id": "revision"}),
        "control",
        "play-hash",
        session.version,
    )
    assert store.save_controlled_replay(session, "control", "play-hash", 1) == saved
    with pytest.raises(Conflict):
        store.save_controlled_replay(saved, "control", "pause-hash", saved.version)
    with Store(
        settings.database_dsn, tenant_id=store.tenant_id, tools_dsn=settings.tools_dsn
    ) as reconnected:
        events = reconnected.events("generation", after=cursor)
        assert [event.type for event in events] == ["window.revised", "replay.state"]
        projection = reconnected.get_projection("generation")
        assert projection["cursor"] == events[-1].id
        assert projection["latest_window"]["id"] == "revision"
    with pytest.raises(NotFound):
        store.publish_event("missing-generation", "window.completed", {})
    assert store.newest_event_id("generation") == events[-1].id


def test_fenced_leases_children_and_call_receipts(store: Store, settings: Settings) -> None:
    replay(store)
    store.save_window(window(store))
    created = store.create_task(root(store, idempotency_key="root-key"))
    assert store.create_task(root(store, "retry", idempotency_key="root-key")).id == created.id
    with pytest.raises(Conflict):
        store.create_task(root(store, "retry", idempotency_key="root-key", question="changed"))
    claimed = store.claim_task("worker-1", ttl_seconds=1)
    assert claimed and claimed.lease_token
    stale_token = claimed.lease_token
    time.sleep(1.05)
    reclaimed = store.claim_task("worker-2")
    assert reclaimed and reclaimed.lease_token != stale_token
    with pytest.raises(Conflict):
        store.save_task(claimed.model_copy(update={"state": "FAILED"}), lease_token=stale_token)
    with pytest.raises(Conflict):
        store.reserve_model_call(created.id, stale_token, 3)
    token = reclaimed.lease_token
    assert token
    assert store.latest_task_trace(created.id) is None
    store.publish_event(
        "generation",
        "task.started",
        {
            "trace_metadata": {"trace_id": "trace", "span_id": "span", "secret_text": "excluded"},
            "attempt_id": store.begin_attempt(created.id, token),
        },
        task_id=created.id,
    )
    trace = store.latest_task_trace(created.id)
    assert trace and trace["trace_id"] == "trace" and trace["span_id"] == "span"
    assert "secret_text" not in trace
    reclaimed = store.reserve_model_call(created.id, token, 3)
    assert store.begin_attempt(created.id, token)
    store.record_model_call(created.id, token, "model-1", {"mode": "scripted"})
    reclaimed = store.reserve_tool_call(created.id, token, 5)
    store.record_tool_call(created.id, "tool-1", "coverage", {}, {"coverage": 0}, lease_token=token)
    store.record_tool_call(created.id, "tool-1", "coverage", {}, {"coverage": 0}, lease_token=token)
    assert len(store.tool_receipts(created.id)) == 1
    with pytest.raises(Conflict):
        store.record_tool_call(
            created.id, "tool-1", "coverage", {}, {"coverage": 1}, lease_token=token
        )
    child = root(
        store,
        "child",
        root_id=created.id,
        parent_id=created.id,
        role="sensor_quality",
        deadline=created.deadline,
    )
    saved_child = store.create_child(child, 0, lease_token=token)
    assert store.create_child(child, 0, lease_token=token) == saved_child
    with pytest.raises(Conflict):
        store.create_child(child.model_copy(update={"question": "different"}), 0, lease_token=token)
    waiting = store.get_task(reclaimed.id)
    assert waiting.state == "WAITING_ON_CHILD" and waiting.version == reclaimed.version + 1
    with pytest.raises(Conflict):
        store.save_task(
            reclaimed.model_copy(update={"state": "WAITING_ON_CHILD"}), lease_token=token
        )
    claimed_child = store.claim_task("worker-2")
    assert claimed_child and claimed_child.id == "child" and claimed_child.lease_token
    store.save_task(
        claimed_child.model_copy(update={"state": "ABSTAINED"}),
        lease_token=claimed_child.lease_token,
    )
    resumed = store.claim_task("worker-2")
    assert resumed and resumed.id == waiting.id and resumed.deadline == created.deadline
    assert resumed.model_calls == 1 and resumed.tool_calls == 1
    assert resumed.lease_token != token
    with pytest.raises(Conflict):
        store.record_tool_call(created.id, "stale-tool", "coverage", {}, {}, lease_token=token)
    assert settings.database_dsn


def test_atomic_event_cursor_and_pool_concurrency(store: Store) -> None:
    replay(store)
    before = store.newest_event_id("generation")
    with ThreadPoolExecutor(max_workers=4) as executor:
        ids = list(
            executor.map(
                lambda n: store.publish_event("generation", "health.changed", {"ordinal": n}).id,
                range(12),
            )
        )
    events = store.events("generation", after=before)
    assert len(events) == 12
    assert [event.id for event in events] == sorted(ids)


def test_model_call_records_read_through_scoped_tools_role(
    store: Store, settings: Settings
) -> None:
    replay(store)
    store.save_window(window(store))
    created = store.create_task(root(store))
    claimed = store.claim_task("worker")
    assert claimed and claimed.lease_token
    claimed = store.reserve_model_call(claimed.id, claimed.lease_token, 3)
    metadata = {
        "requested_model": "requested-fixture-model",
        "observed_model": "observed-fixture-model",
        "cli_version": "fixture-cli-version",
        "usage": {"known": True, "input_tokens": 20, "output_tokens": 10},
    }
    store.record_model_call(claimed.id, claimed.lease_token, "call-1", metadata)
    assert store.list_model_calls(created.id) == [metadata]
    with Store(
        settings.database_dsn, tenant_id="wrong-tenant", tools_dsn=settings.tools_dsn
    ) as wrong_tenant:
        with pytest.raises(NotFound):
            wrong_tenant.list_model_calls(created.id)
    with Store(
        settings.database_dsn,
        tenant_id=store.tenant_id,
        site_id="wrong-site",
        tools_dsn=settings.tools_dsn,
    ) as wrong_site:
        with pytest.raises(NotFound):
            wrong_site.list_model_calls(created.id)


def test_persisted_admission_and_role_budget(store: Store) -> None:
    replay(store)
    store.save_window(window(store))
    episode = MonitoringEpisode(
        id="episode",
        tenant_id=store.tenant_id,
        site_id=store.site_id,
        generation_id="generation",
        state="ACTIVE",
        hypothesis="insufficient_evidence",
        basis_window_id="window",
        current_window_id="window",
        first_seen_seconds=60,
        last_qualified_seconds=60,
    )
    store.save_episode(episode)
    created = store.create_task(
        root(
            store,
            automatic=True,
            episode_id="episode",
            idempotency_key="automatic",
        )
    )
    assert store.list_episodes("generation")[0].auto_roots == 1
    store.create_task(
        root(
            store,
            "retry",
            automatic=True,
            episode_id="episode",
            idempotency_key="automatic",
        )
    )
    assert store.save_episode(episode).auto_roots == 1
    claimed = store.claim_task("worker")
    assert claimed and claimed.lease_token
    for _ in range(3):
        claimed = store.reserve_model_call(created.id, claimed.lease_token, 3)
    with pytest.raises(BudgetExceeded):
        store.reserve_model_call(created.id, claimed.lease_token, 99)
    store.save_task(
        claimed.model_copy(update={"state": "ABSTAINED"}), lease_token=claimed.lease_token
    )
    with pytest.raises(BudgetExceeded):
        store.create_task(
            root(
                store,
                "cooldown",
                automatic=True,
                episode_id="episode",
                idempotency_key="cooldown",
            )
        )


def test_root_queue_and_manual_admission_are_database_enforced(store: Store) -> None:
    replay(store)
    store.save_window(window(store))
    for n in range(3):
        store.create_task(root(store, f"manual-{n}"), operator_id="same-operator")
    with pytest.raises(BudgetExceeded):
        store.create_task(root(store, "rate-blocked"), operator_id="same-operator")
    for n in range(13):
        store.create_task(root(store, f"queue-{n}"), operator_id=f"operator-{n}")
    with pytest.raises(QueueFull):
        store.create_task(root(store, "queue-blocked"), operator_id="another-operator")


def test_deadline_includes_waiting_and_monitor_lease_reconnect(
    store: Store, settings: Settings
) -> None:
    replay(store)
    store.save_window(window(store))
    assert store.acquire_monitor_lease("generation", "monitor-a", ttl_seconds=1)
    with Store(settings.database_dsn, tenant_id=store.tenant_id) as reconnected:
        assert not reconnected.acquire_monitor_lease("generation", "monitor-b")
        store.create_task(root(store, deadline=utc_now() + timedelta(seconds=0.5)))
        time.sleep(1.05)
        assert reconnected.acquire_monitor_lease("generation", "monitor-b")
        store.release_monitor_lease("generation", "monitor-a")
        assert not store.acquire_monitor_lease("generation", "monitor-c")
        assert reconnected.claim_task("worker") is None
        assert reconnected.get_task("root").error_code == "deadline_exceeded"
        assert store.events("generation")[-1].type == "task.finished"


def test_explicit_qualification_allowance_preserves_interactive_throttle(
    store: Store, settings: Settings
) -> None:
    replay(store)
    store.save_window(window(store))
    with Store(
        settings.database_dsn, tenant_id=store.tenant_id, qualification=True
    ) as qualification:
        for n in range(9):
            qualification.create_task(root(qualification, f"qualification-{n}"))
        with pytest.raises(BudgetExceeded):
            qualification.create_task(root(qualification, "qualification-blocked"))
        baseline = qualification.create_task(
            root(
                qualification,
                "baseline",
                purpose="evaluate_single_agent_baseline",
            )
        )
        assert baseline.purpose == "evaluate_single_agent_baseline"
        with pytest.raises(BudgetExceeded):
            qualification.create_task(
                root(
                    qualification,
                    "baseline-blocked",
                    purpose="evaluate_single_agent_baseline",
                )
            )
        claimed = qualification.claim_task("baseline-worker", task_id=baseline.id)
        assert claimed and claimed.id == baseline.id and claimed.lease_token
        with pytest.raises(ScopeError):
            qualification.create_child(
                root(
                    qualification,
                    "baseline-child",
                    root_id=baseline.id,
                    parent_id=baseline.id,
                    role="sensor_quality",
                    deadline=baseline.deadline,
                ),
                0,
                lease_token=claimed.lease_token,
            )
    with pytest.raises(BudgetExceeded):
        store.create_task(root(store, "interactive-blocked"))
    with pytest.raises(Conflict):
        store.create_task(
            root(
                store,
                "interactive-baseline",
                purpose="evaluate_single_agent_baseline",
            )
        )


def test_targeted_claim_never_consumes_other_queued_work(store: Store) -> None:
    replay(store)
    store.save_window(window(store))
    first = store.create_task(root(store, "first"))
    second = store.create_task(root(store, "second"))
    selected = store.claim_task("worker", task_id=second.id)
    assert selected and selected.id == second.id
    assert store.get_task(first.id).state == "QUEUED"
    assert store.claim_task("another-worker", task_id=second.id) is None
    assert store.get_task(first.id).state == "QUEUED"
    with pytest.raises(NotFound):
        store.claim_task("worker", task_id="missing")


def test_reuse_authority_is_fenced_exact_and_tied_to_consumed_quality(store: Store) -> None:
    replay(store)
    store.save_window(window(store))
    cached = store.create_task(root(store, "cached"))
    cached = store.claim_task("worker")
    assert cached and cached.lease_token
    quality = root(
        store,
        "cached-quality",
        root_id=cached.id,
        parent_id=cached.id,
        role="sensor_quality",
        purpose="assess_sensor_health",
        deadline=cached.deadline,
    )
    diagnosis = root(
        store,
        "cached-diagnosis",
        root_id=cached.id,
        parent_id=cached.id,
        role="event_diagnosis",
        purpose="assess_event_and_location",
        deadline=cached.deadline,
    )
    store.create_child(quality, 0, lease_token=cached.lease_token)
    store.create_child(diagnosis, 1, lease_token=cached.lease_token)
    quality = store.claim_task("worker")
    assert quality and quality.lease_token
    accepted = AgentResult(
        outcome="insufficient_evidence",
        claim_refs=[],
        limitations=["synthetic evidence only"],
    )
    quality = store.save_task(
        quality.model_copy(update={"state": "ABSTAINED", "result": accepted}),
        lease_token=quality.lease_token,
    )
    diagnosis = store.claim_task("worker")
    assert diagnosis and diagnosis.lease_token
    diagnosis = store.reserve_tool_call(diagnosis.id, diagnosis.lease_token, 8)
    store.record_tool_call(
        diagnosis.id,
        "read-quality",
        "task.result",
        {"task_id": quality.id},
        {"task": quality.model_dump(mode="json")},
        lease_token=diagnosis.lease_token,
    )
    diagnosis = store.save_task(
        diagnosis.model_copy(update={"state": "ABSTAINED", "result": accepted}),
        lease_token=diagnosis.lease_token,
    )
    cached = store.claim_task("worker", task_id=cached.id)
    assert cached and cached.lease_token
    store.save_task(
        cached.model_copy(update={"state": "ABSTAINED"}), lease_token=cached.lease_token
    )
    store.create_task(
        root(
            store,
            "reuse",
            purpose="answer_incident_question",
            plan=["reuse", "answer"],
        )
    )
    parent = store.claim_task("worker")
    assert parent and parent.lease_token
    with pytest.raises(Conflict):
        store.authorize_reuse(parent.id, [quality.id, diagnosis.id], "stale-token")
    authorized = store.authorize_reuse(parent.id, [diagnosis.id, quality.id], parent.lease_token)
    assert {task.id for task in authorized} == {quality.id, diagnosis.id}
    assert set(store.reuse_task_ids(parent.id)) == {quality.id, diagnosis.id}
    assert (
        len(store.authorize_reuse(parent.id, [quality.id, diagnosis.id], parent.lease_token)) == 2
    )
    with pytest.raises(Conflict):
        store.authorize_reuse(parent.id, [quality.id], parent.lease_token)


def test_supported_two_child_workflow_keeps_role_counters_separate(store: Store) -> None:
    replay(store)
    store.save_window(window(store))
    created = store.create_task(
        root(
            store,
            purpose="answer_incident_question",
            plan=["quality", "diagnosis", "answer"],
        )
    )
    supported = AgentResult(
        outcome="supported",
        claim_refs=[],
        limitations=["synthetic evidence only"],
        hypothesis="no_event",
    )
    current = store.claim_task("worker")
    assert current and current.lease_token
    for step, role, model_limit, tool_limit, purpose in (
        (0, "sensor_quality", 3, 5, "assess_sensor_health"),
        (1, "event_diagnosis", 4, 8, "assess_event_and_location"),
    ):
        current = store.reserve_model_call(current.id, current.lease_token, 3)
        current = store.reserve_tool_call(current.id, current.lease_token, 5)
        child = root(
            store,
            f"child-{step}",
            root_id=current.id,
            parent_id=current.id,
            role=role,
            purpose=purpose,
            deadline=created.deadline,
        )
        store.create_child(child, step, lease_token=current.lease_token)
        assert store.get_task(current.id).state == "WAITING_ON_CHILD"
        claimed_child = store.claim_task("worker")
        assert claimed_child and claimed_child.id == child.id and claimed_child.lease_token
        for _ in range(model_limit):
            claimed_child = store.reserve_model_call(
                claimed_child.id,
                claimed_child.lease_token,
                model_limit,
            )
        for _ in range(tool_limit):
            claimed_child = store.reserve_tool_call(
                claimed_child.id,
                claimed_child.lease_token,
                tool_limit,
            )
        store.save_task(
            claimed_child.model_copy(update={"state": "SUCCEEDED", "result": supported}),
            lease_token=claimed_child.lease_token,
        )
        current = store.claim_task("worker")
        assert current and current.id == created.id and current.lease_token
        assert current.model_calls == step + 1
        assert current.tool_calls == step + 1
    current = store.reserve_model_call(current.id, current.lease_token, 3)
    for _ in range(3):
        current = store.reserve_tool_call(current.id, current.lease_token, 5)
    answered = store.save_task(
        current.model_copy(
            update={
                "state": "SUCCEEDED",
                "result": supported,
                "answer": "No eligible event.",
            }
        ),
        lease_token=current.lease_token,
    )
    tasks = store.list_tasks("generation")
    assert answered.model_calls == 3 and answered.tool_calls == 5
    assert {task.role: task.model_calls for task in tasks} == {
        "operator_response": 3,
        "sensor_quality": 3,
        "event_diagnosis": 4,
    }
    assert sum(task.model_calls for task in tasks) == 10
    assert sum(task.tool_calls for task in tasks) == 18
    assert answered.state == "SUCCEEDED"


def test_atomic_child_handoff_survives_coordinator_crash(store: Store, settings: Settings) -> None:
    replay(store)
    store.save_window(window(store))
    created = store.create_task(root(store))
    parent = store.claim_task("coordinator")
    assert parent and parent.lease_token
    child = root(
        store,
        "child",
        root_id=parent.id,
        parent_id=parent.id,
        role="sensor_quality",
        deadline=created.deadline,
    )
    store.create_child(child, 0, lease_token=parent.lease_token)
    with pytest.raises(Conflict):
        store.create_child(child, 0, lease_token="stale-lease")
    # No separate parent save: another process can finish the child immediately.
    with Store(settings.database_dsn, tenant_id=store.tenant_id) as worker:
        assert worker.get_task(parent.id).state == "WAITING_ON_CHILD"
        claimed = worker.claim_task("worker")
        assert claimed and claimed.id == child.id and claimed.lease_token
        worker.save_task(
            claimed.model_copy(update={"state": "ABSTAINED"}), lease_token=claimed.lease_token
        )
        assert worker.get_task(parent.id).state == "QUEUED"
        resumed = worker.claim_task("new-coordinator")
        assert resumed and resumed.id == parent.id
        assert resumed.deadline == created.deadline
    with pytest.raises(Conflict):
        store.save_task(
            parent.model_copy(update={"state": "SUCCEEDED"}), lease_token=parent.lease_token
        )


def test_manual_rate_limit_survives_new_replay_generations(store: Store) -> None:
    for n in range(4):
        generation_id = f"generation-{n}"
        replay(store, generation_id)
        store.save_window(window(store, generation_id, id=f"window-{n}"))
        proposed = root(
            store,
            f"root-{n}",
            generation_id=generation_id,
            snapshot_id=f"window-{n}",
        )
        if n < 3:
            store.create_task(proposed, operator_id="same-operator")
        else:
            with pytest.raises(BudgetExceeded):
                store.create_task(proposed, operator_id="same-operator")


def test_provider_failure_is_global_durable_fenced_and_explicitly_cleared(
    provider_settings: Settings,
) -> None:
    configured = provider_settings
    with Store(
        configured.database_dsn, tenant_id="provider-test", tools_dsn=configured.tools_dsn
    ) as source:
        replay(source)
        source.save_window(window(source))
        source.create_task(root(source))
        claimed = source.claim_task("worker")
        assert claimed and claimed.lease_token
        assert source.get_provider_failure() is None
        claimed = source.reserve_model_call(claimed.id, claimed.lease_token, 3)
        source.record_model_call(
            claimed.id,
            claimed.lease_token,
            "quota-call",
            {"error_code": "proxy_quota"},
        )
        assert source.get_provider_failure() == "proxy_quota"
        replay(source, "new-generation")
        assert source.get_provider_failure() == "proxy_quota"
        with pytest.raises(Conflict):
            source.record_provider_failure(claimed.id, "stale", "proxy_auth")
        assert source.get_provider_failure() == "proxy_quota"
        source.record_provider_failure(claimed.id, claimed.lease_token, "proxy_auth")
    with Store(
        configured.database_dsn,
        tenant_id="different-tenant",
        site_id="different-site",
        tools_dsn=configured.tools_dsn,
    ) as reopened:
        assert reopened.get_provider_failure() == "proxy_auth"
        with pytest.raises(NotFound):
            reopened.get_task("root")
        reopened.clear_provider_failure()
        assert reopened.get_provider_failure() is None
    with psycopg.connect(configured.tools_dsn) as tools:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            tools.execute("SELECT subsea.clear_provider_failure()")


def test_migration_is_idempotent(settings: Settings) -> None:
    migrate(
        settings.admin_dsn,
        settings.app_password,
        settings.tools_password,
        settings.checkpoint_password,
    )
    with psycopg.connect(settings.database_dsn) as conn:
        rows = conn.execute(
            "SELECT relrowsecurity,relforcerowsecurity FROM pg_class c "
            "JOIN pg_namespace n ON c.relnamespace=n.oid "
            "WHERE n.nspname='subsea' AND c.relkind='r'"
        ).fetchall()
        assert rows and all(row == (True, True) for row in rows)

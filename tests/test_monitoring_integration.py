"""Exercise the monitor/provider boundary against the owned PostgreSQL database."""

import os
import uuid
from collections.abc import Iterator
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from subsea_copilot import monitoring as monitoring_module
from subsea_copilot.api import create_app
from subsea_copilot.config import Settings
from subsea_copilot.contracts import AgentRole, Mode, ReplaySession
from subsea_copilot.diagnostics import analyze_window
from subsea_copilot.ingest import normalize_records, parse_timestamp
from subsea_copilot.monitoring import UNAVAILABLE_DISPATCH, Monitor
from subsea_copilot.runtime.scripted import ScriptedChatModel
from subsea_copilot.runtime.workflow import AgentService
from subsea_copilot.store import Conflict, Store
from subsea_copilot.synthetic import SOURCE_VERSION, generate_scenario
from subsea_copilot.telemetry import Telemetry
from subsea_copilot.validation import ValidationError
from subsea_copilot.warning import monitoring_warning

pytestmark = pytest.mark.integration


def test_api_dispatches_fresh_root_with_its_own_postgres_execution_context(settings):
    import time

    with TestClient(create_app(settings)) as client:
        app = client.app
        store = app.state.store
        service = app.state.resources["service"]
        source = generate_scenario("S1", 2026, duration_seconds=180)
        replay = store.create_replay(ReplaySession(
            id="worker-smoke-" + uuid.uuid4().hex, tenant_id=store.tenant_id,
            site_id=settings.site_id, scenario="S1", source_version=SOURCE_VERSION,
            mode="scripted", epoch=source.epoch, clock_seconds=95, last_endpoint=95,
        ))
        rows = normalize_records(source.records, source.pack)
        store.save_observations(replay.id, rows)
        snapshot = store.save_window(analyze_window(
            source.pack, normalize_records(source.baseline, source.pack), rows,
            replay.id, 90, 95, source.epoch, tenant_id=store.tenant_id,
        ))
        task = service.submit_question(
            replay, snapshot, "Assess the pipeline and instrument evidence.", "worker-smoke",
        )
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            task = store.get_task(task.id)
            if task.state in {"SUCCEEDED", "FAILED", "ABSTAINED"}:
                break
            time.sleep(0.05)
        assert task.state == "SUCCEEDED", task.error_code
        health = client.get("/api/health").json()
        assert health["investigation_worker_limit"] is None
        assert health["agent"] == "running"


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Settings:
    if not os.environ.get("SUBSEA_DB_APP_PASSWORD"):
        pytest.skip("Load the independently bootstrapped PostgreSQL environment")
    monkeypatch.setenv("SUBSEA_TELEMETRY_ENABLED", "0")
    return replace(
        Settings.from_env(),
        tenant_id="monitor-test-" + uuid.uuid4().hex,
        runtime_dir=tmp_path,
    )


@pytest.fixture
def monitor(settings: Settings) -> Iterator[Monitor]:
    def factory(role: AgentRole, _mode: Mode) -> ScriptedChatModel:
        return ScriptedChatModel(role=role)

    with Store(
        settings.database_dsn,
        tenant_id=settings.tenant_id,
        site_id=settings.site_id,
        tools_dsn=settings.tools_dsn,
    ) as store:
        telemetry = Telemetry(settings.runtime_dir)
        try:
            service = AgentService(store, factory, InMemorySaver(), telemetry)
            yield Monitor(store, service, telemetry)
        finally:
            telemetry.close()


@pytest.mark.parametrize("failure", ["proxy_auth", "proxy_quota", "knowledge_unavailable"])
def test_outage_windows_progress_when_provider_is_unavailable(
    monitor: Monitor,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    replay = monitor.create("S6", 2026, "live", "outage")
    source = monitor._source(replay)
    source.received_seconds = []
    monkeypatch.setattr(monitor.agents, "health", lambda: {"available": False})
    for index in range(14):
        monitor.control(replay.id, "step", None, f"step-{index}")
    current = monitor.store.get_replay(replay.id)
    assert current.clock_seconds == 70
    assert current.latest_window_id
    snapshot = monitor.store.get_window(current.latest_window_id)
    assert snapshot.end_seconds == 65
    assert snapshot.quality.status == "COVERAGE_LOST"
    assert snapshot.event.hypothesis == "insufficient_evidence"
    assert not monitor.store.list_tasks(replay.id)
    episodes = monitor.store.list_episodes(replay.id)
    assert episodes
    assert all(episode.dispatch_status == "agent_unavailable" for episode in episodes)
    assert all(not episode.segment_ids for episode in episodes)

    # Availability can change between checking health and admitting a task.
    monkeypatch.setattr(monitor.agents, "health", lambda: {"available": True})

    def unavailable(*_args: object, **_kwargs: object) -> None:
        raise ValidationError(failure, "Provider became unavailable during admission")

    monkeypatch.setattr(monitor.agents, "submit_question", unavailable)
    monitor.control(replay.id, "step", None, "race-step")
    assert monitor.store.get_replay(replay.id).clock_seconds == 75
    assert monitor.error is None


def test_repeated_control_does_not_advance_clock_twice(monitor: Monitor) -> None:
    replay = monitor.create("S1", 2026, "scripted", "idempotent")
    first = monitor.control(replay.id, "step", None, "one-step")
    repeated = monitor.control(replay.id, "step", None, "one-step")
    assert first.clock_seconds == repeated.clock_seconds == 5
    second = monitor.control(replay.id, "step", None, "second-step")
    assert second.clock_seconds == 10
    assert second.latest_window_id
    assert monitor.store.get_window(second.latest_window_id).quality.status == "WARMING_UP"


def test_speed_linked_steps_preserve_every_window_and_idempotency(monitor: Monitor) -> None:
    for seconds in (1, 2, 5, 10, 20, 30):
        replay = monitor.create(
            "S1", 2026, "scripted", f"step-{seconds}", workflow="sensor_alerts",
        )
        current = monitor.control(
            replay.id, "step", None, "advance", step_seconds=seconds,
        )
        repeated = monitor.control(
            replay.id, "step", None, "advance", step_seconds=seconds,
        )
        assert current.clock_seconds == repeated.clock_seconds == seconds
        assert current.state == "PAUSED"
        windows = monitor.store.list_windows(replay.id)
        assert {window.end_seconds for window in windows} == set(range(5, seconds - 4, 5))
        assert not monitor.store.list_tasks(replay.id)


def test_speed_linked_step_stops_at_an_intermediate_investigation_hold(
    monitor: Monitor, monkeypatch: pytest.MonkeyPatch,
) -> None:
    replay = monitor.create("S1", 2026, "scripted", "step-hold", workflow="sensor_alerts")
    checked: list[int] = []

    def pause(session, snapshot):
        checked.append(snapshot.end_seconds)
        if snapshot.end_seconds != 15:
            return False
        current = monitor.store.get_replay(session.id)
        monitor.store.save_replay(
            current.model_copy(update={"investigation_window_id": snapshot.id}),
            expected_version=current.version,
        )
        return True

    monkeypatch.setattr(monitor, "_pause_for_investigation", pause)
    current = monitor.control(replay.id, "step", None, "advance", step_seconds=30)
    assert checked == [5, 10, 15]
    assert current.clock_seconds == 20
    assert current.investigation_window_id is not None
    assert current.last_endpoint == 15
    assert not monitor.store.list_tasks(replay.id)


@pytest.mark.parametrize("speed", [10, 30])
def test_monitor_retains_wall_time_across_accelerated_alarm_checks(
    monitor: Monitor, monkeypatch: pytest.MonkeyPatch, speed: int,
) -> None:
    wall = 0.0
    monkeypatch.setattr(
        monitoring_module, "time", SimpleNamespace(monotonic=lambda: wall),
    )
    replay = monitor.create("S1", 2026, "scripted", "wall-time", pause_on_anomaly=True)
    monitor.control(replay.id, "speed", speed, "speed")
    current = monitor.control(replay.id, "play", None, "play")
    source = monitor._source(current)
    for index in range(7):
        wall = 1 + index / 100
        monitor.tick()
    current = monitor.store.get_replay(replay.id)
    assert current.clock_seconds == pytest.approx(wall * speed)
    endpoints = {window.end_seconds for window in monitor.store.list_windows(replay.id)}
    assert endpoints == set(range(5, int(current.clock_seconds - 5) // 5 * 5 + 1, 5))
    assert all(
        value <= current.clock_seconds for value in source.received_seconds[:source.released]
    )
    assert not monitor.store.list_tasks(replay.id)


def test_pause_discards_catchup_credit_and_does_not_bill_paused_wall_time(
    monitor: Monitor, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wall = 0.0
    monkeypatch.setattr(
        monitoring_module, "time", SimpleNamespace(monotonic=lambda: wall),
    )
    replay = monitor.create("S1", 2026, "scripted", "pause-credit", pause_on_anomaly=True)
    monitor.control(replay.id, "speed", 30, "speed")
    monitor.control(replay.id, "play", None, "play")
    wall = 1
    monitor.tick()
    source = monitor._source(monitor.store.get_replay(replay.id))
    assert source.pending_seconds > 0
    paused = monitor.control(replay.id, "pause", None, "pause")
    assert source.pending_seconds == 0
    wall = 1001
    resumed = monitor.control(replay.id, "play", None, "resume")
    assert resumed.clock_seconds == paused.clock_seconds
    wall += 0.1
    monitor.tick()
    assert monitor.store.get_replay(replay.id).clock_seconds == pytest.approx(
        paused.clock_seconds + 3,
    )


def test_monitor_query_excludes_idle_history_but_keeps_clock_backlog(
    monitor: Monitor, monkeypatch: pytest.MonkeyPatch,
) -> None:
    idle = monitor.create("S1", 2026, "scripted", "idle")
    playing = monitor.create("S1", 2026, "scripted", "playing")
    monitor.store.save_replay(playing.model_copy(update={"state": "PLAYING"}))
    backlog = monitor.create("S1", 2026, "scripted", "backlog")
    monitor.store.save_replay(backlog.model_copy(update={"clock_seconds": 20}))
    completed = monitor.create("S1", 2026, "scripted", "completed")
    monitor.store.save_replay(completed.model_copy(update={
        "state": "COMPLETED", "clock_seconds": 365, "last_endpoint": 360,
    }))
    candidates = monitor.store.list_monitor_replays(
        SOURCE_VERSION, 5, 5, sorted(UNAVAILABLE_DISPATCH),
    )
    assert {row.id for row in candidates} == {playing.id, backlog.id}
    visited: list[str] = []
    monkeypatch.setattr(monitor, "_advance", lambda session, _source: visited.append(session.id))
    monitor.tick()
    assert set(visited) == {playing.id, backlog.id}
    assert monitor.store.get_replay(idle.id).clock_seconds == 0


@pytest.mark.parametrize("pause_on_anomaly", [False, True])
def test_missing_only_outage_requests_review_without_inventing_a_hardware_verdict(
    monitor: Monitor, monkeypatch: pytest.MonkeyPatch, pause_on_anomaly: bool
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("An unavailable provider must not receive an investigation")

    monkeypatch.setattr(monitor.agents, "health", lambda: {"available": False})
    monkeypatch.setattr(monitor.agents, "submit_question", forbidden)
    replay = monitor.create("S3", 2026, "live", "missing-only", pause_on_anomaly=pause_on_anomaly)
    for index in range(37):
        current = monitor.control(replay.id, "step", None, f"missing-step-{index}")
        if current.investigation_window_id:
            current = monitor.control(replay.id, "play", None, f"continue-missing-{index}")
            monitor.control(replay.id, "pause", None, f"pause-missing-{index}")
    snapshot = monitor.store.get_window(current.latest_window_id)
    assert 185 <= current.clock_seconds < 190
    assert snapshot.quality.status == "COVERAGE_LOST"
    assert any(finding.missing > 0 for finding in snapshot.quality.findings)
    assert not any(finding.anomaly_count for finding in snapshot.quality.findings)
    assert monitoring_warning(snapshot, sensor_alerts_only=True).kind == "coverage_lost"
    assert not monitor.store.list_tasks(replay.id)
    episodes = monitor.store.list_episodes(replay.id)
    assert episodes
    assert all(episode.hypothesis == "insufficient_evidence" for episode in episodes)
    assert all(not episode.segment_ids for episode in episodes)


def test_missing_invalid_flags_wait_for_context_not_a_numerical_fault_label(
    monitor: Monitor,
) -> None:
    replay = monitor.create("S6", 2026, "scripted", "quality-only", pause_on_anomaly=True)
    for index in range(14):
        current = monitor.control(replay.id, "step", None, f"normal-{index}")
    snapshot = monitor.store.get_window(current.latest_window_id)
    assert not any(finding.anomaly_count for finding in snapshot.quality.findings)
    findings = [
        finding.model_copy(update={"missing": 20, "hard_excluded": 1, "peer_disagreement": True})
        for finding in snapshot.quality.findings
    ]
    flagged = snapshot.model_copy(
        update={"quality": snapshot.quality.model_copy(update={"findings": findings})}
    )
    assert not monitor._pause_for_investigation(current, flagged)
    monitor._episode(current, flagged)
    assert monitor.store.get_replay(replay.id).investigation_window_id is None
    assert not monitor.store.list_tasks(replay.id)


def test_recovered_missing_only_hold_reports_unavailable_review_and_can_continue(
    monitor: Monitor, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(monitor.agents, "health", lambda: {"available": False})
    replay = monitor.create("S6", 2026, "live", "legacy-hold", pause_on_anomaly=True)
    monitor._source(replay).received_seconds = []
    for index in range(14):
        current = monitor.control(replay.id, "step", None, f"missing-{index}")
    current = monitor.store.save_replay(
        current.model_copy(update={"investigation_window_id": current.latest_window_id})
    )
    monitor._episode(current, monitor.store.get_window(current.latest_window_id))
    assert not monitor.store.list_tasks(replay.id)
    assert monitor.store.list_episodes(replay.id)[0].dispatch_status == "agent_unavailable"
    resumed = monitor.control(replay.id, "play", None, "continue-legacy")
    assert resumed.state == "PLAYING"
    assert resumed.investigation_window_id is None


def paused_s7(monitor: Monitor, *, mode: Mode = "scripted"):
    replay = monitor.create("S7", 2026, mode, "paused-s7", pause_on_anomaly=True)
    monitor.control(replay.id, "speed", 10, "ten-times")
    current = monitor.control(replay.id, "play", None, "start")
    source = monitor._source(current)
    for _ in range(60):
        source.anchor -= 60
        previous_endpoint = current.last_endpoint
        monitor._advance(current, source)
        current = monitor.store.get_replay(replay.id)
        assert current.clock_seconds <= (
            previous_endpoint
            + 2 * source.dataset.pack.hop_seconds
            + source.dataset.pack.lateness_seconds
        )
        if current.investigation_window_id:
            return current, source
    pytest.fail("The extended network never paused on a detector alarm")


def test_ten_times_admits_on_pressure_context_then_freezes_until_review(monitor: Monitor) -> None:
    current, source = paused_s7(monitor)
    assert current.state == "PAUSED"
    assert current.investigation_window_id == current.latest_window_id
    basis = monitor.store.get_window(current.investigation_window_id)
    assert basis.quality.status != "WARMING_UP"
    assert any(finding.anomaly_count > 0 for finding in basis.quality.findings)
    assert basis.end_seconds > 95
    assert basis.event.eligible_hypotheses == []
    assert basis.event.segment_ids == []
    assert basis.location is None
    assert current.investigation_context_policy == "early-pressure-context-v3"
    assert current.clock_seconds == 115
    assert current.detected_alert_keys
    assert all(key.endswith(":pressure") for key in current.detected_alert_keys)
    roots = [task for task in monitor.store.list_tasks(current.id) if not task.parent_id]
    assert len(roots) == 1
    assert roots[0].snapshot_id == basis.id
    frozen = (current.clock_seconds, source.released, basis.id, basis.input_hash)
    for action in ("play", "step"):
        with pytest.raises(Conflict, match="investigation_pending"):
            monitor.control(current.id, action, None, "blocked-" + action)
    monitor.control(current.id, "speed", 1, "speed-while-held")
    for _ in range(3):
        source.anchor -= 600
        monitor.tick()
    latest = monitor.store.get_replay(current.id)
    assert (
        latest.clock_seconds,
        source.released,
        latest.latest_window_id,
        basis.input_hash,
    ) == frozen
    assert len(monitor.store.list_tasks(current.id)) == 1
    for _ in range(10):
        monitor.agents.run_once()
        root = monitor.store.get_task(roots[0].id)
        if root.state in ("SUCCEEDED", "ABSTAINED"):
            break
    assert root.state in ("SUCCEEDED", "ABSTAINED"), root.error_code
    activity = monitor.store.events(current.id, limit=500)
    checks = [event for event in activity if event.type == "agent.check_completed"]
    assert checks
    assert all(event.payload["schema"] == "agent-public-v1" for event in checks)
    assert any(event.payload.get("agent_question") for event in checks)
    handoffs = [event for event in activity if event.type == "agent.handoff_requested"]
    assert {event.payload["to_role"] for event in handoffs} == {"sensor_quality", "event_diagnosis"}
    assert all(event.payload["from_task_id"] == root.id for event in handoffs)
    assert {event.payload["role"] for event in activity if event.type == "answer.checked"} == {
        "sensor_quality",
        "event_diagnosis",
        "operator_response",
    }
    assert any(event.type == "agent.draft" for event in activity)
    assert any(event.type == "agent.review_requested" for event in activity)
    assert monitor.store.get_replay(current.id).clock_seconds == frozen[0]
    assert monitor.store.get_replay(current.id).state == "PAUSED"
    fake_root = root.model_copy(update={"id": "new-root", "root_id": "new-root"})
    context = monitor.agents._context(fake_root, basis, "plan")
    assert context["compatible_tasks"] == []
    assert context["result_schema"]["properties"]["steps"]["enum"] == [
        ["quality", "diagnosis", "answer"]
    ]
    resumed = monitor.control(current.id, "play", None, "continue-after-review")
    assert resumed.state == "PLAYING"
    assert resumed.investigation_window_id is None


def test_recorded_immediate_pause_policy_is_not_rewritten(monitor: Monitor) -> None:
    replay = monitor.store.create_replay(ReplaySession(
        id="legacy-policy-" + uuid.uuid4().hex,
        tenant_id=monitor.store.tenant_id, site_id=monitor.store.site_id,
        scenario="S7", source_version=SOURCE_VERSION, seed=2026,
        mode="scripted", pause_on_anomaly=True,
    ))
    assert replay.investigation_context_seconds == 0
    for step in range(24):
        current = monitor.control(replay.id, "step", None, f"legacy-step-{step}")
        if current.investigation_window_id:
            break
    assert current.clock_seconds == 100
    assert monitor.store.get_window(current.investigation_window_id).end_seconds == 95


def test_recorded_context_delay_does_not_restore_numerical_persistence_gate(
    monitor: Monitor,
) -> None:
    replay = monitor.store.create_replay(ReplaySession(
        id="persistence-policy-" + uuid.uuid4().hex,
        tenant_id=monitor.store.tenant_id, site_id=monitor.store.site_id,
        scenario="S7", source_version=SOURCE_VERSION, seed=2026,
        mode="scripted", pause_on_anomaly=True, investigation_context_seconds=20,
    ))
    for step in range(26):
        current = monitor.control(replay.id, "step", None, f"old-context-{step}")
        if current.investigation_window_id:
            break
    assert current.clock_seconds == 120
    with pytest.raises(Conflict, match="generation_identity_conflict"):
        monitor.store.save_replay(
            current.model_copy(update={"investigation_context_policy": "inspection-context-v2"})
        )


def test_recorded_inspection_delay_does_not_require_a_numerical_location(monitor: Monitor) -> None:
    replay = monitor.store.create_replay(ReplaySession(
        id="inspection-policy-" + uuid.uuid4().hex,
        tenant_id=monitor.store.tenant_id, site_id=monitor.store.site_id,
        scenario="S7", source_version=SOURCE_VERSION, seed=2026,
        mode="scripted", pause_on_anomaly=True, investigation_context_seconds=30,
        investigation_context_policy="inspection-context-v2",
    ))
    for step in range(30):
        current = monitor.control(replay.id, "step", None, f"inspection-step-{step}")
        if current.investigation_window_id:
            break
    assert current.clock_seconds == 130
    assert monitor.store.get_window(current.investigation_window_id).location is None


def test_unavailable_agent_is_explicit_and_never_deadlocks_simulation(
    monitor: Monitor, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(monitor.agents, "health", lambda: {"available": False})
    current, _source = paused_s7(monitor, mode="live")
    episode = monitor.store.list_episodes(current.id)[0]
    assert episode.dispatch_status == "agent_unavailable"
    assert not monitor.store.list_tasks(current.id)
    monitor.tick()
    assert monitor.store.list_episodes(current.id)[0].material_revision == episode.material_revision
    continued = monitor.control(current.id, "play", None, "continue-without-report")
    assert continued.state == "PLAYING"
    assert continued.investigation_window_id is None
    episode = monitor.store.list_episodes(current.id)[0]
    assert episode.dispatch_status == "continued_without_report"
    assert episode.pending_window_id is None


def test_restart_recovers_a_hold_persisted_before_dispatch(
    monitor: Monitor, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = monitor._episode
    monkeypatch.setattr(monitor, "_episode", lambda *_args: None)
    current, _source = paused_s7(monitor)
    assert not monitor.store.list_tasks(current.id)
    assert current.latest_window_id == current.investigation_window_id
    monkeypatch.setattr(monitor, "_episode", original)
    monitor._sources.clear()
    monitor.tick()
    roots = monitor.store.list_tasks(current.id)
    assert len(roots) == 1
    assert roots[0].snapshot_id == current.investigation_window_id
    assert monitor.store.get_replay(current.id).clock_seconds == current.clock_seconds


def test_paused_workflow_drains_late_arrivals_after_its_final_window(
    monitor: Monitor, monkeypatch: pytest.MonkeyPatch
) -> None:
    replay = monitor.create("S1", 2026, "scripted", "late-source-tail", pause_on_anomaly=True)
    current = monitor.store.save_replay(
        replay.model_copy(
            update={"state": "PLAYING", "clock_seconds": 365, "last_endpoint": 360, "speed": 10}
        )
    )
    source = monitor._source(current)
    source.received_seconds[-1] = 425
    source.anchor -= 60
    monkeypatch.setattr(monitor, "_process", lambda session, _source: session)
    monitor._advance(current, source)
    final = monitor.store.get_replay(current.id)
    assert final.clock_seconds == 425
    assert final.state == "COMPLETED"


@pytest.mark.parametrize("scenario", ["S1", "S2"])
def test_sensor_alert_workflow_never_admits_agents(
    monitor: Monitor, monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    def forbidden_health() -> dict[str, object]:
        raise AssertionError("Alert-only monitoring must not check or invoke the LLM")

    monkeypatch.setattr(monitor.agents, "health", forbidden_health)
    replay = monitor.create(scenario, 2026, "live", "alerts-" + scenario, workflow="sensor_alerts")
    for index in range(37):
        current = monitor.control(replay.id, "step", None, f"alert-step-{index}")
    assert current.workflow == "sensor_alerts"
    snapshot = monitor.store.get_window(current.latest_window_id)
    assert any(f.anomaly_count or f.missing for f in snapshot.quality.findings)
    assert not monitor.store.list_tasks(replay.id)
    assert not monitor.store.list_episodes(replay.id)
    warning = monitoring_warning(snapshot, sensor_alerts_only=True)
    assert warning.kind == "sensor_alerts"
    assert "does not classify" in warning.message
    with pytest.raises(ValidationError, match="agent investigation is disabled"):
        monitor.agents.submit_question(current, snapshot, "Leak or malfunction?", "disabled")
    with pytest.raises(Conflict, match="generation_identity_conflict"):
        monitor.store.save_replay(
            current.model_copy(update={"workflow": "agent_assisted"}),
            expected_version=current.version,
        )


@pytest.mark.parametrize("terminal", ["FAILED", "ABSTAINED"])
def test_playback_live_override_preserves_recordings_and_retries_exact_window(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, terminal: str,
) -> None:
    monkeypatch.setattr(AgentService, "_check_provider", lambda *args: None)
    app = create_app(settings, start_workers=False)
    with TestClient(app) as client:
        login = client.post(
            "/api/login", json={"username": "operator", "password": settings.operator_password},
        )
        headers = {"X-CSRF-Token": login.json()["csrf_token"]}
        original = client.post("/api/replays", headers=headers, json={
            "scenario": "S7", "seed": 2026, "mode": "scripted",
            "idempotency_key": "playback-original",
        }).json()
        url = f"/api/replays/{original['id']}/investigate-here"
        payload = {"source_seconds": 100, "idempotency_key": "live-at-100"}
        assert client.post(url, json=payload).status_code == 403
        assert client.post(url, headers=headers, json={
            **payload, "source_seconds": 101,
        }).status_code == 422
        response = client.post(url, headers=headers, json=payload)
        assert response.status_code == 200, response.text
        prepared = response.json()
        replay, task = prepared["replay"], prepared["task"]
        assert replay["id"] != original["id"]
        assert replay["mode"] == "live"
        assert replay["state"] == "PAUSED"
        assert task["generation_id"] == replay["id"]
        assert task["snapshot_id"] == replay["investigation_window_id"]
        usage = client.get(f"/api/tasks/{task['id']}").json()["execution_usage"]
        assert usage["reported_calls"] == 0
        assert usage["cost_min_usd"] is None
        snapshot = client.get(f"/api/windows/{task['snapshot_id']}").json()
        assert snapshot["end_seconds"] == 100
        assert snapshot["generation_id"] == replay["id"]
        retried = client.post(url, headers=headers, json=payload)
        assert retried.status_code == 200
        assert retried.json()["task"]["id"] == task["id"]
        assert len(app.state.store.list_tasks(replay["id"])) == 1
        assert client.post(url, headers=headers, json={
            **payload, "source_seconds": 120,
        }).status_code == 409
        assert app.state.store.get_replay(original["id"]).model_dump(mode="json") == original
        assert not app.state.store.list_tasks(original["id"])
        manifest_url = f"/api/replays/{original['id']}/recordings"
        manifest = client.get(manifest_url).json()
        assert manifest["base_playback_speed"] == 5
        assert manifest["recordings"] == []
        claimed = app.state.store.claim_task("timeline-test", task_id=task["id"])
        assert claimed is not None
        app.state.store.save_task(claimed.model_copy(update={
            "state": terminal, "error_code": "grounding_rejected",
            "error_message": "Synthetic rejected report for recording-contract coverage.",
        }))
        rows = client.get(manifest_url).json()["recordings"]
        assert len(rows) == 1
        assert rows[0]["task_id"] == task["id"]
        assert rows[0]["source_seconds"] == 100
        assert rows[0]["state"] == terminal
        saved = client.get(f"{manifest_url}/{task['id']}")
        assert saved.status_code == 200
        assert saved.json()["snapshot"]["input_hash"] == snapshot["input_hash"]
        assert saved.json()["detail"]["casefile"] is None
        other = client.post("/api/replays", headers=headers, json={
            "scenario": "S7", "seed": 2027, "mode": "scripted",
            "idempotency_key": "unrelated-timeline",
        }).json()
        assert client.get(f"/api/replays/{other['id']}/recordings").json()["recordings"] == []


def test_timeline_map_uses_received_measurements_without_advancing_or_writing(
    settings: Settings,
) -> None:
    with TestClient(create_app(settings, start_workers=False)) as client:
        login = client.post("/api/login", json={
            "username": "operator", "password": settings.operator_password,
        })
        headers = {"X-CSRF-Token": login.json()["csrf_token"]}
        original = client.post("/api/replays", headers=headers, json={
            "scenario": "S7", "seed": 2026, "mode": "live",
            "idempotency_key": "readonly-timeline",
        }).json()
        endpoint = f"/api/replays/{original['id']}/timeline-window"
        assert client.get(endpoint, params={"source_seconds": 0}).json() == {
            "snapshot": None,
            "warning": monitoring_warning(
                None, workflow=original["workflow"],
            ).model_dump(mode="json"),
        }
        assert client.get(endpoint, params={"source_seconds": 101}).status_code == 422
        response = client.get(endpoint, params={"source_seconds": 120})
        assert response.status_code == 200
        snapshot = response.json()["snapshot"]
        replay = client.app.state.store.get_replay(original["id"])
        source = client.app.state.resources["monitor"]._source(replay)
        received = [
            row for row, arrival in zip(
                source.dataset.records, source.received_seconds, strict=True,
            ) if arrival <= snapshot["clock_seconds"]
        ]
        expected = analyze_window(
            source.dataset.pack, source.baseline,
            normalize_records(received, source.dataset.pack),
            generation_id=replay.id, end_seconds=120,
            clock_seconds=snapshot["clock_seconds"], epoch=replay.epoch,
            tenant_id=replay.tenant_id, screening_only=True,
        )
        assert snapshot["input_hash"] == expected.input_hash
        assert snapshot["quality"] == expected.quality.model_dump(mode="json")
        assert response.json()["warning"] == monitoring_warning(
            expected, workflow=replay.workflow,
        ).model_dump(mode="json")
        for selected in (120, 60, 120):
            payload = client.get(endpoint, params={"source_seconds": selected}).json()
            frame = payload["snapshot"]
            assert payload["warning"]["snapshot_id"] == frame["id"]
            sensor = source.dataset.pack.sensors[0]
            measurements = client.get(f"/api/windows/{frame['id']}/sensors/{sensor.id}")
            assert measurements.status_code == 200
            for row in measurements.json()["observations"]:
                assert frame["window_start"] <= row["observed_at"] < frame["window_end"]
                assert parse_timestamp(row["received_at"]) <= replay.epoch + timedelta(
                    seconds=frame["clock_seconds"],
                )
                assert row["sensor_id"] == sensor.id
                assert row["unit"] == "bar"
            assert client.get(f"/api/windows/{frame['id']}").json()["id"] == frame["id"]
        store = client.app.state.store
        assert store.get_replay(replay.id).model_dump(mode="json") == original
        assert store.list_tasks(replay.id) == []
        assert store.list_windows(replay.id) == []
        assert store.observations(replay.id) == []


def test_api_alert_workflow_blocks_questions_without_inference(settings: Settings) -> None:
    app = create_app(settings, start_workers=False)
    with TestClient(app) as client:
        login = client.post(
            "/api/login", json={"username": "operator", "password": settings.operator_password}
        )
        headers = {"X-CSRF-Token": login.json()["csrf_token"]}
        replay = client.post(
            "/api/replays",
            headers=headers,
            json={
                "scenario": "S1",
                "mode": "live",
                "workflow": "sensor_alerts",
                "idempotency_key": "api-alerts",
            },
        ).json()
        assert replay["workflow"] == "sensor_alerts"
        for index in range(24):
            stepped = client.post(
                f"/api/replays/{replay['id']}/control",
                headers=headers,
                json={"action": "step", "idempotency_key": f"step-{index}"},
            )
            assert stepped.status_code == 200
        view = client.get(f"/api/replays/{replay['id']}/projection").json()
        assert view["warning"]["kind"] == "sensor_alerts"
        assert view["tasks"] == []
        response = client.post(
            f"/api/replays/{replay['id']}/questions",
            headers=headers,
            json={
                "snapshot_id": view["latest_window"]["id"],
                "mode": "live",
                "question": "Leak or malfunction?",
                "idempotency_key": "disabled",
            },
        )
        assert response.status_code == 409
        assert response.json()["code"] == "workflow_disabled"


def test_both_api_workflows_share_detector_evidence_with_workflow_specific_copy(
    settings: Settings,
) -> None:
    with TestClient(create_app(settings, start_workers=False)) as client:
        login = client.post(
            "/api/login", json={"username": "operator", "password": settings.operator_password}
        )
        headers = {"X-CSRF-Token": login.json()["csrf_token"]}
        views = []
        for workflow in ("sensor_alerts", "agent_assisted"):
            response = client.post(
                "/api/replays",
                headers=headers,
                json={
                    "scenario": "S1",
                    "mode": "scripted",
                    "workflow": workflow,
                    "pause_on_anomaly": False,
                    "idempotency_key": "shared-" + workflow,
                },
            )
            assert response.status_code == 200
            replay_id = response.json()["id"]
            for index in range(23):
                stepped = client.post(
                    f"/api/replays/{replay_id}/control",
                    headers=headers,
                    json={"action": "step", "idempotency_key": f"shared-step-{index}"},
                )
                assert stepped.status_code == 200
            views.append(client.get(f"/api/replays/{replay_id}/projection").json())
        assert views[0]["latest_window"]["input_hash"] == views[1]["latest_window"]["input_hash"]
        for key in ("coverage", "usable_samples", "expected_samples"):
            assert (
                views[0]["latest_window"]["quality"][key]
                == views[1]["latest_window"]["quality"][key]
            )
        warnings = [{**view["warning"], "snapshot_id": None} for view in views]
        assert warnings[0]["kind"] == warnings[1]["kind"]
        assert warnings[1]["severity"] == "warning"
        assert warnings[0]["kind"] == "sensor_alerts"
        assert warnings[0]["severity"] == "attention"
        assert "engineer review required" in warnings[0]["title"]
        assert "does not classify" in warnings[0]["message"]
        assert "sensors flagged by monitoring" in warnings[1]["title"]
        assert "agent investigation below" in warnings[1]["message"]
        assert "do not wait for AI" in warnings[1]["message"]
        assert "does not classify" not in warnings[1]["message"]
        assert views[0]["tasks"] == []
        assert views[1]["tasks"]
        assert all(task["model_calls"] == 0 for view in views for task in view["tasks"])


def test_first_anomaly_admits_review_without_a_numerical_leak_or_location(
    monitor: Monitor,
) -> None:
    replay = monitor.create("S1", 2026, "scripted", "unresolved-then-leak")
    for index in range(20):
        monitor.control(replay.id, "step", None, f"triage-{index}")
    episode = monitor.store.list_episodes(replay.id)[0]
    assert episode.dispatch_status == "queued"
    assert episode.first_seen_seconds == 95
    for index in range(4):
        monitor.control(replay.id, "step", None, f"leak-{index}")
    roots = monitor.store.list_tasks(replay.id)
    assert len(roots) == 1
    basis = monitor.store.get_window(roots[0].snapshot_id)
    assert basis.end_seconds == 95
    assert basis.event.eligible_hypotheses == []
    assert basis.location is None
    latest = monitor.store.get_window(monitor.store.get_replay(replay.id).latest_window_id)
    assert latest.quality.status == "DEGRADED"
    pending = monitor.store.list_episodes(replay.id)[0].pending_window_id
    assert pending is not None
    assert monitor.store.get_window(pending).end_seconds > basis.end_seconds


@pytest.mark.parametrize("scenario", ["S2", "S5"])
def test_anomaly_admission_does_not_require_instrumentation_or_coverage_verdict(
    monitor: Monitor,
    scenario: str,
) -> None:
    replay = monitor.create(scenario, 2026, "scripted", "immediate-" + scenario)
    for index in range(60):
        current = monitor.control(replay.id, "step", None, f"source-{index}")
        if not current.latest_window_id:
            continue
        snapshot = monitor.store.get_window(current.latest_window_id)
        if snapshot.quality.status == "WARMING_UP":
            continue
        if not any(finding.anomaly_count > 0 for finding in snapshot.quality.findings):
            continue
        roots = monitor.store.list_tasks(replay.id)
        assert len(roots) == 1
        assert roots[0].snapshot_id == snapshot.id
        assert monitor.store.list_episodes(replay.id)[0].dispatch_status == "queued"
        return
    pytest.fail("The scenario did not reach its instrumentation/coverage warning")


def test_unresolved_measurements_do_not_impose_a_sixty_second_diagnosis_hold(
    monitor: Monitor,
) -> None:
    replay = monitor.create("S4", 2026, "scripted", "persistent-unresolved")
    for index in range(30):
        monitor.control(replay.id, "step", None, f"collect-{index}")
    episode = monitor.store.list_episodes(replay.id)[0]
    assert episode.dispatch_status == "queued"
    monitor.control(replay.id, "step", None, "source-155")
    monitor.control(replay.id, "step", None, "source-160")
    roots = monitor.store.list_tasks(replay.id)
    assert len(roots) == 1
    basis = monitor.store.get_window(roots[0].snapshot_id)
    assert basis.end_seconds == 95
    assert basis.event.hypothesis == "insufficient_evidence"
    assert basis.location is None


def test_numerical_no_event_label_cannot_cancel_an_admitted_measurement_review(
    monitor: Monitor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replay = monitor.create("S4", 2026, "scripted", "resolved-unresolved")
    for index in range(20):
        monitor.control(replay.id, "step", None, f"collect-{index}")
    original = monitor._snapshot

    def resolved(*args, **kwargs):
        snapshot = original(*args, **kwargs)
        return snapshot.model_copy(
            update={
                "event": snapshot.event.model_copy(update={"hypothesis": "no_event"}),
            }
        )

    monkeypatch.setattr(monitor, "_snapshot", resolved)
    monitor.control(replay.id, "step", None, "detector-resolved")
    episode = monitor.store.list_episodes(replay.id)[0]
    assert episode.dispatch_status == "queued"
    assert episode.pending_window_id is None
    assert len(monitor.store.list_tasks(replay.id)) == 1


def test_measurement_warning_does_not_claim_a_leak_without_an_agent(monitor: Monitor, monkeypatch):
    replay = monitor.create("S1", 2026, "live", "leak-without-provider")
    monkeypatch.setattr(monitor.agents, "health", lambda: {"available": False})
    for index in range(24):
        monitor.control(replay.id, "step", None, f"warning-step-{index}")
    current = monitor.store.get_replay(replay.id)
    snapshot = monitor.store.get_window(current.latest_window_id)
    assert monitoring_warning(snapshot, workflow="agent_assisted").kind == "sensor_alerts"
    assert not monitor.store.list_tasks(replay.id)
    assert monitor.store.list_episodes(replay.id)[0].dispatch_status == "agent_unavailable"


@pytest.mark.parametrize("old_version", ["legacy-v1", "pressure-v2"])
def test_archived_replay_is_never_reinterpreted_as_pressure(monitor: Monitor, old_version) -> None:
    replay = monitor.create("S1", 2026, "scripted", "archived")
    monitor.control(replay.id, "step", None, "one-step")
    current = monitor.control(replay.id, "step", None, "two-steps")
    assert current.source_version == "pressure-v3"
    assert current.latest_window_id
    snapshot = monitor.store.get_window(current.latest_window_id)
    archived = monitor.store.save_replay(
        current.model_copy(update={"source_version": old_version, "state": "PLAYING"}),
        expected_version=current.version,
    )
    with pytest.raises(Conflict, match="Archived replay"):
        monitor.control(archived.id, "step", None, "forbidden-step")
    monitor.tick()
    assert monitor.store.get_replay(archived.id).clock_seconds == archived.clock_seconds
    assert monitor.store.get_window(snapshot.id) == snapshot


def test_idle_history_does_not_rehydrate_all_sensor_streams(
    monitor: Monitor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replay = monitor.create("S1", 2026, "scripted", "idle-history")
    monitor.control(replay.id, "step", None, "one")
    monitor.control(replay.id, "step", None, "two")
    monitor._sources.clear()

    def forbidden(_replay: object) -> None:
        raise AssertionError("Idle history must not block startup by regenerating streams")

    monkeypatch.setattr(monitor, "_source", forbidden)
    monitor.tick()
    assert monitor.store.get_replay(replay.id).clock_seconds == 10


def test_completed_source_drains_bounded_window_backlog(monitor: Monitor) -> None:
    replay = monitor.create("S6", 2026, "scripted", "bounded-drain")
    monitor._source(replay).received_seconds = []
    monitor.store.save_replay(
        replay.model_copy(update={"state": "COMPLETED", "clock_seconds": 365}),
        expected_version=replay.version,
    )
    monitor.tick()
    assert monitor.store.get_replay(replay.id).last_endpoint == 10
    for _ in range(35):
        monitor.tick()
    drained = monitor.store.get_replay(replay.id)
    assert drained.state == "COMPLETED"
    assert drained.last_endpoint == 360
    assert drained.latest_window_id
    assert monitor.store.get_window(drained.latest_window_id).end_seconds == 360


def test_explicit_scripted_mode_is_not_disabled_by_live_provider_failure(
    monitor: Monitor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replay = monitor.create("S2", 2026, "scripted", "explicit-scripted")
    monkeypatch.setattr(monitor.agents, "health", lambda: {"available": False})
    for index in range(13):
        monitor.control(replay.id, "step", None, f"step-{index}")
    roots = monitor.store.list_tasks(replay.id)
    assert len(roots) == 1
    assert roots[0].mode == "scripted"
    assert roots[0].state == "QUEUED"
    basis = monitor.store.get_window(roots[0].snapshot_id)
    assert any(finding.anomaly_count > 0 for finding in basis.quality.findings)


def test_api_provider_error_is_explicit_and_controls_remain_available(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(settings, start_workers=False)
    with TestClient(app) as client:
        login = client.post(
            "/api/login",
            json={
                "username": "operator",
                "password": settings.operator_password,
            },
        )
        assert login.status_code == 200
        csrf = login.json()["csrf_token"]
        headers = {"X-CSRF-Token": csrf}
        service = app.state.resources["service"]
        monkeypatch.setattr(
            service,
            "health",
            lambda: {
                "available": False,
                "error_code": "proxy_quota",
            },
        )
        assert client.get("/api/health").json()["agent"] == "proxy_quota"
        response = client.post(
            "/api/replays",
            headers=headers,
            json={
                "scenario": "S1",
                "mode": "scripted",
                "idempotency_key": "api",
            },
        )
        assert response.status_code == 200
        replay_id = response.json()["id"]
        forged = client.post(
            f"/api/replays/{replay_id}/control",
            json={
                "action": "step",
                "idempotency_key": "forged",
            },
        )
        assert forged.status_code == 403
        stepped = client.post(
            f"/api/replays/{replay_id}/control",
            headers=headers,
            json={
                "action": "step",
                "idempotency_key": "valid",
            },
        )
        assert stepped.status_code == 200
        assert stepped.json()["clock_seconds"] == 5
        second = client.post(
            f"/api/replays/{replay_id}/control",
            headers=headers,
            json={
                "action": "step",
                "idempotency_key": "second",
            },
        ).json()
        question = {
            "question": "Is this a possible leak or an instrumentation issue?",
            "snapshot_id": second["latest_window_id"],
            "mode": "scripted",
            "idempotency_key": "question",
        }
        original_submit = service.submit_question

        def unavailable(*_args: object, **_kwargs: object) -> None:
            raise ValidationError("proxy_quota", "Provider unavailable; no automatic retry.")

        monkeypatch.setattr(service, "submit_question", unavailable)
        rejected = client.post(
            f"/api/replays/{replay_id}/questions",
            headers=headers,
            json=question,
        )
        assert rejected.status_code == 503
        assert rejected.json()["code"] == "proxy_quota"
        monkeypatch.setattr(service, "submit_question", original_submit)
        submitted = client.post(
            f"/api/replays/{replay_id}/questions",
            headers=headers,
            json=question,
        )
        assert submitted.status_code == 200
        task_id = submitted.json()["id"]
        assert client.get(f"/api/tasks/{task_id}/casefile").status_code == 409
        for _ in range(10):
            service.run_once()
            task = app.state.store.get_task(task_id)
            if task.state in ("SUCCEEDED", "ABSTAINED"):
                break
        assert task.state in ("SUCCEEDED", "ABSTAINED")
        checked: list[str] = []

        def verify(
            _self: Telemetry,
            trace_id: str,
            required_types: list[str] | None = None,
        ) -> bool:
            assert required_types == ["agent", "generation", "tool", "guardrail"]
            checked.append(trace_id)
            return True

        monkeypatch.setattr(Telemetry, "verify_trace", verify)
        trace = client.get(f"/api/tasks/{task_id}/trace").json()
        assert trace["stored_trace_visible"] is True
        assert checked == [trace["trace_id"]]
        assert trace["langfuse_url"].endswith(
            f"/project/subsea-copilot/traces/{trace['trace_id']}"
        )
        assert trace["content_capture"] == trace["observability"]["content_capture"]
        handoff = client.get(f"/api/tasks/{task_id}/casefile")
        assert handoff.status_code == 200
        assert "attachment" in handoff.headers["content-disposition"]
        assert handoff.json()["snapshot_id"] == question["snapshot_id"]
        assert handoff.json()["inspection"] is None
        assert handoff.json()["provider_cost_usd"] is None
        assert client.get(f"/api/tasks/{task_id}").json()["casefile"] == handoff.json()
        specialist = next(
            child for child in app.state.store.list_tasks(replay_id) if child.parent_id == task_id
        )
        specialist_trace = client.get(f"/api/tasks/{specialist.id}/trace").json()
        assert specialist_trace["trace_id"] == trace["trace_id"]
        assert specialist_trace["span_id"] != trace["span_id"]
        assert specialist_trace["trace_layout"] == trace["trace_layout"] == "investigation-v1"
        assert specialist_trace["session_id"] == trace["session_id"]
        assert client.get(f"/api/tasks/{specialist.id}/casefile").status_code == 409
        client.cookies.clear()
        assert client.get(f"/api/tasks/{task_id}/casefile").status_code == 401

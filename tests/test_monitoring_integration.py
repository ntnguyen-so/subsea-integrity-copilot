"""Exercise the monitor/provider boundary against the owned PostgreSQL database."""

import os
import uuid
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from subsea_copilot.api import create_app
from subsea_copilot.config import Settings
from subsea_copilot.contracts import AgentRole, Mode
from subsea_copilot.monitoring import Monitor
from subsea_copilot.runtime.scripted import ScriptedChatModel
from subsea_copilot.runtime.workflow import AgentService
from subsea_copilot.store import Conflict, Store
from subsea_copilot.telemetry import Telemetry
from subsea_copilot.validation import ValidationError
from subsea_copilot.warning import monitoring_warning

pytestmark = pytest.mark.integration


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


@pytest.mark.parametrize("failure", ["proxy_auth", "proxy_quota"])
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
    assert monitor.store.list_episodes(replay.id)[0].dispatch_status == "agent_unavailable"

    # Availability can change between checking health and admitting a task.
    monkeypatch.setattr(monitor.agents, "health", lambda: {"available": True})

    def unavailable(*_args: object, **_kwargs: object) -> None:
        raise ValidationError(failure, "Provider unavailable; no automatic retry.")

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


def test_maturing_leak_bypasses_unresolved_hold_without_an_obsolete_llm_job(
    monitor: Monitor,
) -> None:
    replay = monitor.create("S1", 2026, "scripted", "unresolved-then-leak")
    for index in range(20):
        monitor.control(replay.id, "step", None, f"triage-{index}")
    episode = monitor.store.list_episodes(replay.id)[0]
    assert episode.dispatch_status == "gathering_context"
    assert episode.first_seen_seconds == 95
    assert not monitor.store.list_tasks(replay.id)
    for index in range(4):
        monitor.control(replay.id, "step", None, f"leak-{index}")
    roots = monitor.store.list_tasks(replay.id)
    assert len(roots) == 1
    basis = monitor.store.get_window(roots[0].snapshot_id)
    assert basis.end_seconds == 110
    assert basis.event.hypothesis == "suspected_leak"
    assert basis.location and basis.location.status == "located"
    latest = monitor.store.get_window(monitor.store.get_replay(replay.id).latest_window_id)
    assert latest.quality.status == "DEGRADED"
    assert monitor.store.list_episodes(replay.id)[0].pending_window_id is None


@pytest.mark.parametrize("scenario", ["S2", "S3", "S5"])
def test_instrumentation_and_coverage_warnings_bypass_context_hold(
    monitor: Monitor,
    scenario: str,
) -> None:
    replay = monitor.create(scenario, 2026, "scripted", "immediate-" + scenario)
    for index in range(60):
        current = monitor.control(replay.id, "step", None, f"source-{index}")
        if not current.latest_window_id:
            continue
        snapshot = monitor.store.get_window(current.latest_window_id)
        if snapshot.quality.status != "COVERAGE_LOST" and (
            snapshot.event.hypothesis != "sensor_or_telemetry_issue"
        ):
            continue
        roots = monitor.store.list_tasks(replay.id)
        assert len(roots) == 1
        assert roots[0].snapshot_id == snapshot.id
        assert monitor.store.list_episodes(replay.id)[0].dispatch_status == "queued"
        return
    pytest.fail("The scenario did not reach its instrumentation/coverage warning")


def test_persistent_unresolved_pattern_is_admitted_on_its_latest_context(
    monitor: Monitor,
) -> None:
    replay = monitor.create("S4", 2026, "scripted", "persistent-unresolved")
    for index in range(30):
        monitor.control(replay.id, "step", None, f"collect-{index}")
    episode = monitor.store.list_episodes(replay.id)[0]
    assert episode.dispatch_status == "gathering_context"
    assert not monitor.store.list_tasks(replay.id)
    monitor.control(replay.id, "step", None, "source-155")
    monitor.control(replay.id, "step", None, "source-160")
    roots = monitor.store.list_tasks(replay.id)
    assert len(roots) == 1
    basis = monitor.store.get_window(roots[0].snapshot_id)
    assert basis.end_seconds == 155
    assert basis.event.hypothesis == "insufficient_evidence"
    assert basis.location is None


def test_resolved_transient_does_not_spend_an_llm_report(
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
    assert episode.dispatch_status == "resolved_before_dispatch"
    assert episode.pending_window_id is None
    assert not monitor.store.list_tasks(replay.id)


def test_possible_leak_warning_does_not_wait_for_a_working_llm(monitor: Monitor, monkeypatch):
    replay = monitor.create("S1", 2026, "live", "leak-without-provider")
    monkeypatch.setattr(monitor.agents, "health", lambda: {"available": False})
    for index in range(24):
        monitor.control(replay.id, "step", None, f"warning-step-{index}")
    current = monitor.store.get_replay(replay.id)
    snapshot = monitor.store.get_window(current.latest_window_id)
    assert monitoring_warning(snapshot).kind == "possible_leak"
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
    replay = monitor.create("S6", 2026, "scripted", "explicit-scripted")
    monitor._source(replay).received_seconds = []
    monkeypatch.setattr(monitor.agents, "health", lambda: {"available": False})
    for index in range(13):
        monitor.control(replay.id, "step", None, f"step-{index}")
    roots = monitor.store.list_tasks(replay.id)
    assert len(roots) == 1
    assert roots[0].mode == "scripted"
    assert roots[0].state == "QUEUED"


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
        assert client.get(f"/api/tasks/{specialist.id}/casefile").status_code == 409
        client.cookies.clear()
        assert client.get(f"/api/tasks/{task_id}/casefile").status_code == 401

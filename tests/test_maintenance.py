"""Maintenance browsing preserves source time, authority and replay scope without inference."""

import os
import uuid
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from subsea_copilot.api import create_app
from subsea_copilot.config import Settings
from subsea_copilot.contracts import ReplaySession
from subsea_copilot.history_data import EXTENDED_HISTORY_PATH, SYNTHETIC_EPOCH, history_index_rows
from subsea_copilot.maintenance import maintenance_catalog
from subsea_copilot.store import Store
from subsea_copilot.synthetic import EXTENDED_PACK_VERSION, SOURCE_VERSION, generate_pack


@pytest.fixture
def replay():
    return ReplaySession(
        id="maintenance-example", site_id="northsea", scenario="S7", seed=2026,
        source_version=SOURCE_VERSION, mode="scripted", epoch=SYNTHETIC_EPOCH,
    )


def test_maintenance_catalog_shows_only_effective_records_and_preserves_original_content(replay):
    before = maintenance_catalog(replay, EXTENDED_PACK_VERSION, 79)
    assert before["records"] == []
    assert before["scenario"] == "S7"
    assert before["next_effective_seconds"] == 80
    assert before["duration_seconds"] == replay.duration_seconds
    catalog = maintenance_catalog(replay, EXTENDED_PACK_VERSION, 80)
    by_id = {row["id"]: row for row in catalog["records"]}
    assert set(by_id) == {"MAINT-P7-GW-002"}
    assert catalog["next_effective_seconds"] is None
    approved = by_id["MAINT-P7-GW-002"]
    assert approved["admissible"] is True and approved["exclusion_reason"] is None
    assert approved["supersedes"] == "MAINT-P7-GW-001"
    originals = {row["id"]: row for row in history_index_rows(EXTENDED_HISTORY_PATH)}
    for row in by_id.values():
        assert row["body"] == originals[row["id"]]["body"]
        assert row["type"] == "maintenance"
        assert "scenarios" not in row
    assert catalog["generation_id"] == replay.id
    assert catalog["source_seconds"] == 80
    assert catalog["as_of"] == "2026-01-01T00:01:20+00:00"


@pytest.mark.parametrize(("changes", "visible"), [
    ({"status": "draft"}, False),
    ({"status": "superseded"}, False),
    ({"effective_to": "2026-01-01T00:01:59Z"}, False),
    ({"effective_to": "2026-01-01T00:02:00Z"}, True),
    ({"effective_from": "2026-01-01T00:02:01Z"}, False),
    ({"available_at": "2026-01-01T00:02:01Z"}, False),
])
def test_maintenance_catalog_enforces_approval_and_effective_period(
    replay, monkeypatch, changes, visible,
):
    original = next(
        row for row in history_index_rows(EXTENDED_HISTORY_PATH)
        if row["id"] == "MAINT-P7-GW-002"
    )
    monkeypatch.setattr(
        "subsea_copilot.maintenance.history_index_rows", lambda _: [{**original, **changes}],
    )
    records = maintenance_catalog(replay, EXTENDED_PACK_VERSION, 120)["records"]
    assert [row["id"] for row in records] == (["MAINT-P7-GW-002"] if visible else [])


def test_maintenance_catalog_is_layout_and_scenario_scoped(replay):
    other = replay.model_copy(update={"scenario": "S1"})
    unrelated = maintenance_catalog(other, EXTENDED_PACK_VERSION, 0)
    assert unrelated["records"] == []
    assert unrelated["next_effective_seconds"] is None
    small = maintenance_catalog(other, generate_pack("northsea").version, 120)
    extended = maintenance_catalog(replay, EXTENDED_PACK_VERSION, 120)
    assert small["corpus_version"] != extended["corpus_version"]
    assert small["source_file"] == r"fixtures\synthetic\operational-history.json"
    assert extended["source_file"] == r"fixtures\synthetic\extended-operational-history.json"
    assert extended["knowledge_source_file"] == r"fixtures\knowledge\pressure-investigation.json"
    assert all("P7" not in row["asset_ids"] for row in small["records"])


@pytest.mark.parametrize("changes", [
    {"status": "draft"},
    {"status": "superseded"},
    {"available_at": "2026-01-01T00:02:00Z", "effective_to": "2026-01-01T00:01:59Z"},
    {"available_at": "2026-01-01T00:06:01Z"},
])
def test_maintenance_navigation_does_not_offer_ineligible_records(replay, monkeypatch, changes):
    original = next(
        row for row in history_index_rows(EXTENDED_HISTORY_PATH)
        if row["id"] == "MAINT-P7-GW-002"
    )
    monkeypatch.setattr(
        "subsea_copilot.maintenance.history_index_rows", lambda _: [{**original, **changes}],
    )
    catalog = maintenance_catalog(replay, EXTENDED_PACK_VERSION, 0)
    assert catalog["records"] == []
    assert catalog["next_effective_seconds"] is None


def test_pressure_knowledge_uses_applicable_wall_clock_guidance_not_simulated_record_time(
    replay, monkeypatch,
):
    now = datetime(2026, 11, 10, tzinfo=UTC)
    monkeypatch.setattr("subsea_copilot.maintenance.utc_now", lambda: now)
    packet = maintenance_catalog(replay, EXTENDED_PACK_VERSION, 80)["knowledge"]
    assert packet["selected_at"] == "2026-11-10T00:00:00Z"
    assert {card["id"] for card in packet["cards"]} == {
        "KN-QUALITY-R1", "KN-INDEPENDENCE-R1", "KN-OPERATING-R1",
        "KN-LOCALIZATION-R1", "KN-INVESTIGATION-PROGRAM-R1",
    }
    assert packet["authority"] == "advisory_only"
    assert all(
        card["verification_steps"] and card["counterexamples"] and card["sources"]
        for card in packet["cards"]
    )



@pytest.mark.parametrize("seconds", [-1, 361])
def test_maintenance_catalog_rejects_out_of_range_source_time(replay, seconds):
    with pytest.raises(ValueError, match="within the selected replay"):
        maintenance_catalog(replay, EXTENDED_PACK_VERSION, seconds)


@pytest.mark.integration
def test_maintenance_api_authenticates_scopes_and_reads_without_creating_agent_work(
    replay, monkeypatch, tmp_path,
):
    if not os.environ.get("SUBSEA_DB_APP_PASSWORD"):
        pytest.skip("Load the independently bootstrapped PostgreSQL environment")
    monkeypatch.setenv("SUBSEA_TELEMETRY_ENABLED", "0")
    settings = replace(
        Settings.from_env(), tenant_id="maintenance-test-" + uuid.uuid4().hex, runtime_dir=tmp_path,
    )
    with TestClient(create_app(settings, start_workers=False)) as client:
        store = client.app.state.store
        scoped = replay.model_copy(update={"tenant_id": settings.tenant_id})
        store.create_replay(scoped)
        endpoint = f"/api/replays/{scoped.id}/maintenance"
        assert client.get(endpoint).status_code == 401
        assert client.post("/api/login", json={
            "username": "operator", "password": settings.operator_password,
        }).status_code == 200
        response = client.get(endpoint, params={"source_seconds": 120})
        assert response.status_code == 200
        assert {row["id"] for row in response.json()["records"]} == {
            "MAINT-P7-GW-002",
        }
        assert client.get(endpoint, params={"source_seconds": 361}).status_code == 422
        assert client.get(endpoint, params={"source_seconds": "invalid"}).status_code == 422
        with Store(
            settings.database_dsn, settings.tenant_id + "-other", settings.site_id,
            settings.tools_dsn,
        ) as other:
            foreign = replay.model_copy(update={"id": "foreign", "tenant_id": other.tenant_id})
            other.create_replay(foreign)
        assert client.get("/api/replays/foreign/maintenance").status_code == 404
        assert store.list_tasks(scoped.id) == []

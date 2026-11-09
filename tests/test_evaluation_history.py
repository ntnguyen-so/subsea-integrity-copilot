from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from subsea_copilot.config import Settings
from subsea_copilot.evaluation_history import load_archive, public_history, rebuild_history


def archive(root: Path, folder: str, **changes: object) -> Path:
    path = root / "runtime" / folder / "report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "version": "spatial-evaluation-v1",
        "run_id": "old-run",
        "created_at": "2026-01-01T00:00:00Z",
        "status": "completed",
        "suite": "current",
        "cases": [{"answer": "Original frozen answer"}],
        "metrics": {"original_recorded_score": 0.25},
        "agent_process": {"withdrawn_score": 1},
    }
    report.update(changes)
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


def test_catalog_separates_suites_and_revisions_and_loads_original_scores(tmp_path):
    original = archive(tmp_path, "original")
    archive(tmp_path, "remapped", remapped_at="2026-01-02T00:00:00Z")
    archive(tmp_path, "recovery", suite="recovery", run_id="recovery-run")
    archive(tmp_path, "private-agent-audit", version="agent-process-evaluation-v1")
    index = tmp_path / "runtime" / "evaluation-history.json"
    source = original.read_bytes()
    catalog = rebuild_history(tmp_path, index)
    assert len(catalog["entries"]) == 3
    entry = next(row for row in catalog["entries"] if row["label"] == "original")
    report = load_archive(entry["archive_id"], root=tmp_path, index=index)
    assert report["metrics"] == {"original_recorded_score": 0.25}
    assert report["cases"] == [{"answer": "Original frozen answer"}]
    assert "agent_process" not in report
    assert report["historical_archive_id"] == entry["archive_id"]
    assert original.read_bytes() == source
    assert all("relative_path" not in row for row in public_history(index)["entries"])


def test_changed_missing_and_unknown_archives_fail_explicitly(tmp_path):
    path = archive(tmp_path, "old")
    index = tmp_path / "runtime" / "evaluation-history.json"
    entry = rebuild_history(tmp_path, index)["entries"][0]
    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(ValueError, match="changed since indexing"):
        load_archive(entry["archive_id"], root=tmp_path, index=index)
    with pytest.raises(LookupError, match="Unknown"):
        load_archive("..\\secrets", root=tmp_path, index=index)
    path.unlink()
    with pytest.raises(FileNotFoundError):
        load_archive(entry["archive_id"], root=tmp_path, index=index)


def test_catalog_reports_unreadable_metadata_without_fabricating_a_result(tmp_path):
    bad = archive(tmp_path, "bad")
    bad.write_text("{corrupt", encoding="utf-8")
    index = tmp_path / "runtime" / "evaluation-history.json"
    catalog = rebuild_history(tmp_path, index)
    assert catalog["entries"] == []
    assert len(catalog["warnings"]) == 1


def test_catalog_cannot_redirect_a_token_outside_approved_output_folders(tmp_path):
    archive(tmp_path, "old")
    index = tmp_path / "runtime" / "evaluation-history.json"
    catalog = rebuild_history(tmp_path, index)
    catalog["entries"][0]["relative_path"] = "..\\outside.json"
    index.write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(ValueError):
        load_archive(catalog["entries"][0]["archive_id"], root=tmp_path, index=index)


def test_api_authenticates_archive_reads_and_never_substitutes_latest(tmp_path, monkeypatch):
    from subsea_copilot import api

    path = archive(tmp_path, "old")
    index = tmp_path / "runtime" / "evaluation-history.json"
    entry = rebuild_history(tmp_path, index)["entries"][0]
    monkeypatch.setattr(api, "Store", MagicMock())
    monkeypatch.setattr(api, "Telemetry", MagicMock())
    monkeypatch.setattr(
        "subsea_copilot.evaluation_history.load_archive",
        lambda token: load_archive(token, root=tmp_path, index=index),
    )
    monkeypatch.setattr(
        "subsea_copilot.reference_evaluation.read_evaluation",
        lambda: {"run_id": "latest-run", "cases": [], "metrics": None},
    )
    settings = Settings(
        database_dsn="unused",
        tools_dsn="unused",
        checkpoint_dsn="unused",
        admin_dsn="unused",
        app_password="unused",
        tools_password="unused",
        checkpoint_password="unused",
        operator_password="local-test-only-password",
        runtime_dir=tmp_path,
    )
    client = TestClient(api.create_app(settings, start_workers=False))
    try:
        url = f"/api/evaluation?archive_id={entry['archive_id']}"
        assert client.get(url).status_code == 401
        assert (
            client.post(
                "/api/login",
                json={"username": "operator", "password": "local-test-only-password"},
            ).status_code
            == 200
        )
        response = client.get(url)
        assert response.status_code == 200
        assert response.json()["run_id"] == "old-run"
        assert response.json()["metrics"] == {"original_recorded_score": 0.25}
        assert "agent_process" not in response.json()
        assert client.get("/api/evaluation").json()["run_id"] == "latest-run"
        assert client.get("/api/evaluation?archive_id=unknown").status_code == 404
        path.write_text("{corrupt", encoding="utf-8")
        response = client.get(url)
        assert response.status_code == 503
        assert "metrics" not in response.json()
    finally:
        client.close()

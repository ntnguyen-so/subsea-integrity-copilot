from pathlib import Path
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from subsea_copilot.config import Settings
from subsea_copilot.recorded_console import create_recorded_console


def test_recorded_console_is_tenant_isolated_and_denies_inference_and_replay_writes(monkeypatch):
    app = FastAPI()
    effects = []

    @app.post("/api/replays/example/questions")
    def question():
        effects.append("new-work")
        return {"queued": True}

    @app.post("/api/replays/example/control")
    def control():
        effects.append("control")
        return {"changed": True}

    @app.post("/api/login")
    def login():
        return {"authenticated": True}

    @app.get("/api/replays")
    def replays():
        return {"replays": [{"id": "recorded-original"}]}

    factory = MagicMock(return_value=app)
    monkeypatch.setattr("subsea_copilot.api.create_app", factory)
    settings = Settings(
        database_dsn="unused", tools_dsn="unused", checkpoint_dsn="unused", admin_dsn="unused",
        app_password="unused", tools_password="unused", checkpoint_password="unused",
        operator_password="unused", runtime_dir=Path("runtime"),
    )
    with TestClient(create_recorded_console(settings, "golden-eval-example")) as client:
        assert client.post("/api/login").status_code == 200
        assert client.get("/api/replays").json()["replays"][0]["id"] == "recorded-original"
        assert client.post("/api/replays/example/questions", json={}).status_code == 405
        assert client.post("/api/replays/example/control", json={}).status_code == 405
        assert client.post("/api/replays", json={}).status_code == 405
        assert client.get("/api/recorded-mode").json()["new_inference"] is False
    assert effects == []
    assert factory.call_args.args[0].tenant_id == "golden-eval-example"
    assert factory.call_args.kwargs["start_workers"] is False
    assert settings.tenant_id == "demo"

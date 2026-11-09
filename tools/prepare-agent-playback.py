"""Export preserved terminal synthetic investigations; never call a model."""

import argparse
import json
from pathlib import Path

from fastapi.testclient import TestClient

from subsea_copilot.casefile import InvestigationCase
from subsea_copilot.config import Settings
from subsea_copilot.contracts import SitePack
from subsea_copilot.playback import Recording, RecordingLibrary, load_library, save_library
from subsea_copilot.recorded_console import create_recorded_console
from subsea_copilot.store import Store


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, required=True)
    args = parser.parse_args()
    settings = Settings.from_env()
    destination = settings.runtime_dir / "agent-playback.json"
    recordings = {row.task.id: row for row in load_library(destination).recordings}
    manifests = sorted(args.runs.glob(r"S7-2026-*\manifest.json"))
    if not manifests:
        parser.error("No preserved S7 checkpoint manifests found")
    for path in manifests:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest["state"] not in {"SUCCEEDED", "ABSTAINED", "FAILED"}:
            raise ValueError(f"Cannot publish a nonterminal recording: {path.name}")
        with TestClient(create_recorded_console(settings, manifest["tenant_id"])) as client:
            login = client.post("/api/login", json={
                "username": "operator", "password": settings.operator_password,
            })
            login.raise_for_status()
            detail_response = client.get(
                f"/api/replays/{manifest['generation_id']}/recordings/{manifest['root_id']}"
            )
            detail_response.raise_for_status()
            detail = detail_response.json()["detail"]
            projection = client.get(f"/api/replays/{manifest['generation_id']}/projection")
            projection.raise_for_status()
            with Store(
                settings.database_dsn, manifest["tenant_id"], settings.site_id,
                settings.tools_dsn, qualification=True,
            ) as store:
                snapshot = store.get_window(manifest["snapshot_id"])
                task = store.get_task(manifest["root_id"])
                children = [
                    child for child in store.list_tasks(manifest["generation_id"])
                    if child.parent_id == task.id
                ]
            row = Recording(
                scenario=manifest["scenario"], seed=manifest["seed"],
                dataset_sha256=manifest["dataset_sha256"],
                pack=SitePack.model_validate(projection.json()["pack"]), snapshot=snapshot,
                task=task, children=children,
                casefile=InvestigationCase.model_validate(detail["casefile"])
                if detail["casefile"] else None,
                execution_usage=detail.get("execution_usage"),
            )
            recordings[row.task.id] = row
    save_library(destination, RecordingLibrary(recordings=list(recordings.values())))
    print(
        f"Preserved {len(recordings)} terminal investigations for playback. No inference executed."
    )


if __name__ == "__main__":
    main()

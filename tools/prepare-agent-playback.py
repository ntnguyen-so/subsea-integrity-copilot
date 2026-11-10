"""Export preserved terminal synthetic investigations; never call a model."""

# Inputs are scenario checkpoint manifests and the original tenants' database records.
# Uses the authenticated recorded-console API in process to build public casefiles,
# then merges recordings by task ID into runtime_dir/agent-playback.json. Reruns
# replace matching IDs, retain others and make no hosted calls; DB access is required.
# Dataset hashes, pack and immutable snapshots travel with each preserved execution.
import argparse
import json
from pathlib import Path

from fastapi.testclient import TestClient

from subsea_copilot.casefile import InvestigationCase
from subsea_copilot.config import Settings
from subsea_copilot.contracts import SitePack
from subsea_copilot.playback import (
    RecordedTrace,
    Recording,
    RecordingLibrary,
    dataset_hash,
    load_library,
    save_library,
)
from subsea_copilot.recorded_console import create_recorded_console
from subsea_copilot.store import Store


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path)
    parser.add_argument("--refresh-traces", action="store_true")
    args = parser.parse_args()
    if args.runs is None and not args.refresh_traces:
        parser.error("Provide --runs or --refresh-traces")
    settings = Settings.from_env()
    destination = settings.runtime_dir / "agent-playback.json"
    # Merge, do not erase other published checkpoints when exporting a subset.
    recordings = {row.task.id: row for row in load_library(destination).recordings}
    manifests = sorted(args.runs.glob(r"*\manifest.json")) if args.runs else []
    if args.runs is not None and not manifests:
        parser.error("No preserved scenario checkpoint manifests found")
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
            if (
                manifest.get("completed") and manifest["state"] == "ABSTAINED"
                and detail["casefile"] is None
            ):
                # Rebuild a qualified abstention's handoff from its original validated
                # task rather than retaining an older library's missing projection.
                original_detail = client.get(f"/api/tasks/{manifest['root_id']}")
                original_detail.raise_for_status()
                detail = original_detail.json()
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
                trace_metadata = store.latest_task_trace(task.id)
                replay = store.get_replay(task.generation_id)
            source = client.app.state.resources["monitor"]._source(replay).dataset
            if (
                manifest["scenario"] != replay.scenario
                or manifest["seed"] != replay.seed
                or manifest["dataset_sha256"] != dataset_hash(source)
                or manifest["source_seconds"] != snapshot.end_seconds
            ):
                raise ValueError(f"Manifest does not match original scenario evidence: {path}")
            row = Recording(
                scenario=manifest["scenario"], seed=manifest["seed"],
                dataset_sha256=manifest["dataset_sha256"],
                pack=SitePack.model_validate(projection.json()["pack"]), snapshot=snapshot,
                task=task, children=children,
                casefile=InvestigationCase.model_validate(detail["casefile"])
                if detail["casefile"] else None,
                execution_usage=detail.get("execution_usage"),
                trace_metadata=RecordedTrace.model_validate({
                    **trace_metadata, "task_id": task.id, "snapshot_id": snapshot.id,
                }) if trace_metadata else None,
            )
            if row.trace_metadata is None:
                print(f"No original trace metadata recorded for {task.id}.")
            recordings[row.task.id] = row
    if args.refresh_traces:
        for task_id, row in recordings.items():
            with Store(
                settings.database_dsn, row.task.tenant_id, row.task.site_id,
                settings.tools_dsn, qualification=True,
            ) as store:
                task = store.get_task(task_id)
                snapshot = store.get_window(task.snapshot_id)
                if (
                    task.snapshot_id != row.task.snapshot_id
                    or task.generation_id != row.task.generation_id
                    or task.state != row.task.state or task.updated_at != row.task.updated_at
                    or snapshot.input_hash != row.snapshot.input_hash
                ):
                    raise ValueError(f"Original recording identity changed: {task_id}")
                trace_metadata = store.latest_task_trace(task_id)
            if trace_metadata is None:
                raise ValueError(f"No original trace metadata recorded for {task_id}")
            recordings[task_id] = row.model_copy(update={
                "trace_metadata": RecordedTrace.model_validate({
                    **trace_metadata, "task_id": task_id, "snapshot_id": row.snapshot.id,
                }),
            })
    save_library(destination, RecordingLibrary(recordings=list(recordings.values())))
    print(
        f"Preserved {len(recordings)} terminal investigations for playback. No inference executed."
    )


if __name__ == "__main__":
    main()

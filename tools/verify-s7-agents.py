"""Run fresh hosted S7 investigations at reproducible demo playback checkpoints."""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from subsea_copilot.budgets import ROOT_WATCHDOG_SECONDS
from subsea_copilot.config import Settings
from subsea_copilot.contracts import content_hash
from subsea_copilot.monitoring import AUTO_QUESTION, Monitor
from subsea_copilot.operations_evaluation import audit_operations
from subsea_copilot.qualification import TERMINALS, qualification_model_factory
from subsea_copilot.reference_evaluation import evaluation_implementation_hash
from subsea_copilot.runtime.checkpointer import postgres_checkpointer
from subsea_copilot.runtime.workflow import AgentService
from subsea_copilot.store import Store
from subsea_copilot.telemetry import Telemetry


def run_checkpoint(endpoint: int, output: Path) -> dict[str, object]:
    settings = Settings.from_env()
    tenant = "s7-reliability-" + uuid4().hex[:12]
    destination = output / f"S7-2026-{endpoint}"
    destination.mkdir(exist_ok=False)
    telemetry = Telemetry(runtime_dir=settings.runtime_dir)
    try:
        with (
            Store(
                settings.database_dsn, tenant, settings.site_id, settings.tools_dsn,
                qualification=True,
            ) as store,
            postgres_checkpointer(settings.checkpoint_dsn) as saver,
        ):
            service = AgentService(store, qualification_model_factory(settings), saver, telemetry)
            monitor = Monitor(store, service, telemetry)
            replay = monitor.create("S7", 2026, "live", "seeded-reliability")
            replay = monitor.control(replay.id, "speed", 5, "recording-base-speed")
            source = monitor._source(replay)
            dataset_hash = content_hash({
                "baseline": [row.model_dump(mode="json") for row in source.dataset.baseline],
                "records": [row.model_dump(mode="json") for row in source.dataset.records],
            })
            for end in range(
                source.dataset.pack.hop_seconds, endpoint + 1, source.dataset.pack.hop_seconds,
            ):
                replay = store.save_replay(
                    replay.model_copy(update={
                        "clock_seconds": end + source.dataset.pack.lateness_seconds,
                    }),
                    expected_version=replay.version,
                )
                monitor._release(replay, source)
                snapshot = store.save_window(monitor._snapshot(replay, source, end))
                replay = store.save_replay(
                    replay.model_copy(update={
                        "latest_window_id": snapshot.id, "last_endpoint": end,
                    }),
                    expected_version=replay.version,
                )
            assert replay.latest_window_id is not None
            snapshot = store.get_window(replay.latest_window_id)
            replay = store.save_replay(
                replay.model_copy(update={"investigation_window_id": snapshot.id}),
                expected_version=replay.version,
            )
            started = time.monotonic()
            monitor._episode(replay, snapshot)
            roots = [
                task for task in store.list_tasks(replay.id)
                if task.parent_id is None and task.snapshot_id == snapshot.id
            ]
            if len(roots) != 1 or roots[0].question != AUTO_QUESTION:
                raise RuntimeError("Production automatic admission did not create one S7 root")
            root = roots[0]
            print(f"S7 seed 2026 @{endpoint}s: {root.id}", flush=True)
            while root.state not in TERMINALS:
                if time.monotonic() - started > ROOT_WATCHDOG_SECONDS:
                    raise RuntimeError(f"S7 @{endpoint}s did not terminate within the watchdog")
                if not service.run_once():
                    time.sleep(0.05)
                root = store.get_task(root.id)
            audit = audit_operations(store, root, snapshot)
            agent_states = {task["role"]: task["state"] for task in audit["tasks"]}
            completed = (
                audit["report"]["completed"] and all(audit["checks"].values())
                and root.state == "SUCCEEDED"
                and all(state == "SUCCEEDED" for state in agent_states.values())
            )
            manifest: dict[str, object] = {
                "scope": "Fresh-agent seeded S7 development regression, not field qualification",
                "scenario": replay.scenario,
                "seed": replay.seed,
                "base_playback_speed": 5,
                "source_seconds": endpoint,
                "dataset_sha256": dataset_hash,
                "tenant_id": tenant,
                "generation_id": replay.id,
                "root_id": root.id,
                "snapshot_id": snapshot.id,
                "input_hash": snapshot.input_hash,
                "state": root.state,
                "error_code": root.error_code,
                "completed": completed,
                "report_completed": audit["report"]["completed"],
                "agent_states": agent_states,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "fresh_model_calls": audit["fresh_model_calls"],
                "fresh_tool_calls": audit["fresh_tool_calls"],
                "reused_task_ids": audit["reused_task_ids"],
                "validation_errors": audit["validation_errors"],
                "critic_decisions": audit["critic_decisions"],
                "answer": audit["report"]["answer"],
                "traces": [
                    {"task_id": task["id"], "trace": store.latest_task_trace(task["id"])}
                    for task in audit["tasks"]
                ],
            }
            (destination / "audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
            (destination / "manifest.json").write_text(
                json.dumps(manifest, indent=2), encoding="utf-8",
            )
            print(json.dumps({
                key: manifest[key]
                for key in ("source_seconds", "root_id", "state", "error_code", "completed")
            }), flush=True)
            return manifest
    finally:
        telemetry.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--checkpoints", nargs="+", type=int, default=[100, 110, 120, 150, 180, 360],
    )
    parser.add_argument(
        "--workers", type=int,
        help="Parallel independent roots; defaults to all requested checkpoints.",
    )
    args = parser.parse_args()
    if any(point < 60 or point > 360 or point % 5 for point in args.checkpoints):
        parser.error("Checkpoints must be five-second endpoints between 60 and 360 seconds.")
    if len(set(args.checkpoints)) != len(args.checkpoints):
        parser.error("Checkpoint endpoints must be unique within one run.")
    if args.workers is not None and args.workers < 1:
        parser.error("Workers must be positive.")
    args.output.mkdir(parents=True, exist_ok=False)
    fingerprint = evaluation_implementation_hash()
    with ThreadPoolExecutor(max_workers=args.workers or len(args.checkpoints)) as executor:
        cases = list(executor.map(lambda end: run_checkpoint(end, args.output), args.checkpoints))
    report = {
        "seed": 2026,
        "implementation_sha256": fingerprint,
        "implementation_unchanged": fingerprint == evaluation_implementation_hash(),
        "cases": cases,
        "failed_checkpoints": [row["source_seconds"] for row in cases if not row["completed"]],
    }
    (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if report["failed_checkpoints"]:
        raise RuntimeError(f"S7 failed checkpoints: {report['failed_checkpoints']}")


if __name__ == "__main__":
    main()

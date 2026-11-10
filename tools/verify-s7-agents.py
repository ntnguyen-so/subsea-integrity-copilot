"""Run fresh hosted investigations at reproducible scenario playback checkpoints."""

# Requires authenticated hosted Copilot plus database/checkpointer services. Each
# checkpoint has an independent qualification tenant/root; source windows are released
# numerically before real-time agent execution. Writes manifests, receipts/audits and
# a report under a new output directory; exist_ok=False prevents destructive reruns.
# Dataset/implementation fingerprints bind the recorded results to their provenance.
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
from subsea_copilot.report_mapping import prepare_report_mapping
from subsea_copilot.runtime.checkpointer import postgres_checkpointer
from subsea_copilot.runtime.workflow import AgentService
from subsea_copilot.store import Store
from subsea_copilot.synthetic import SCENARIOS
from subsea_copilot.telemetry import Telemetry


# Build one bounded checkpoint through production automatic admission, then audit
# actual tool/model work. An accepted contract is not a field diagnosis certificate.
def run_checkpoint(
    endpoint: int, output: Path, scenario: str = "S7", *, record: bool = False,
) -> dict[str, object]:
    settings = Settings.from_env()
    tenant = scenario.lower() + "-reliability-" + uuid4().hex[:12]
    destination = output / f"{scenario}-2026-{endpoint}"
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
            model_factory = qualification_model_factory(settings)
            service = AgentService(store, model_factory, saver, telemetry)
            monitor = Monitor(store, service, telemetry)
            replay = monitor.create(scenario, 2026, "live", "seeded-reliability")
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
            if record:
                service.submit_question(
                    replay, snapshot, AUTO_QUESTION, "explicit-recorded-checkpoint",
                )
            else:
                monitor._episode(replay, snapshot)
            roots = [
                task for task in store.list_tasks(replay.id)
                if task.parent_id is None and task.snapshot_id == snapshot.id
            ]
            if len(roots) != 1 or roots[0].question != AUTO_QUESTION:
                raise RuntimeError("Checkpoint admission did not create one investigation root")
            root = roots[0]
            print(f"{scenario} seed 2026 @{endpoint}s: {root.id}", flush=True)
            while root.state not in TERMINALS:
                if time.monotonic() - started > ROOT_WATCHDOG_SECONDS:
                    raise RuntimeError(
                        f"{scenario} @{endpoint}s did not terminate within the watchdog",
                    )
                if not service.run_once():
                    time.sleep(0.05)
                root = store.get_task(root.id)
            audit = audit_operations(store, root, snapshot)
            agent_states = {task["role"]: task["state"] for task in audit["tasks"]}
            completed = (
                audit["report"]["completed"] and all(audit["checks"].values())
                and root.state in ({"SUCCEEDED", "ABSTAINED"} if record else {"SUCCEEDED"})
                and all(
                    state in ({"SUCCEEDED", "ABSTAINED"} if record else {"SUCCEEDED"})
                    for state in agent_states.values()
                )
            )
            mapping_status = None
            trace_verified = None
            if record and completed:
                if root.state == "SUCCEEDED":
                    mapping = prepare_report_mapping(
                        settings.runtime_dir, root, source.dataset.pack,
                        model_factory("operator_response", "live"), telemetry,
                    )
                    mapping_status = mapping["status"]
                else:
                    mapping_status = "not_run_abstained"
                telemetry.flush()
                trace_metadata = store.latest_task_trace(root.id) or {}
                trace_id = trace_metadata.get("trace_id")
                trace_verified = False
                if isinstance(trace_id, str):
                    for attempt in range(5):
                        trace_verified = telemetry.verify_trace(
                            trace_id, required_types=["agent", "generation", "tool", "guardrail"],
                        )
                        if trace_verified:
                            break
                        if attempt < 4:
                            time.sleep(1)
                completed = mapping_status in {"completed", "not_run_abstained"} and trace_verified
            manifest: dict[str, object] = {
                "scope": "Fresh-agent seeded development recording, not field qualification",
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
                "report_supported": root.state == "SUCCEEDED",
                "error_code": root.error_code,
                "completed": completed,
                "report_completed": audit["report"]["completed"],
                "agent_states": agent_states,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "elapsed_scope": "reviewed report, mapping and trace verification"
                if record else "reviewed report",
                "fresh_model_calls": audit["fresh_model_calls"],
                "fresh_tool_calls": audit["fresh_tool_calls"],
                "reused_task_ids": audit["reused_task_ids"],
                "validation_errors": audit["validation_errors"],
                "critic_decisions": audit["critic_decisions"],
                "admission": "explicit-fixed-checkpoint" if record else "automatic",
                "mapping_status": mapping_status,
                "stored_trace_verified": trace_verified,
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
                for key in (
                    "scenario", "source_seconds", "root_id", "state", "error_code", "completed",
                )
            }), flush=True)
            return manifest
    finally:
        telemetry.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scenarios", nargs="+", choices=SCENARIOS, default=["S7"])
    parser.add_argument(
        "--record", action="store_true",
        help="Investigate explicit checkpoints, including quiet sources; prepare maps and traces.",
    )
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
    if len(set(args.scenarios)) != len(args.scenarios):
        parser.error("Scenarios must be unique within one run.")
    if args.workers is not None and args.workers < 1:
        parser.error("Workers must be positive.")
    args.output.mkdir(parents=True, exist_ok=False)
    fingerprint = evaluation_implementation_hash()
    # Parallelism is across isolated roots, not faster simulated model time.
    checkpoints = [(scenario, point) for point in args.checkpoints for scenario in args.scenarios]
    with ThreadPoolExecutor(max_workers=args.workers or len(checkpoints)) as executor:
        cases = list(executor.map(
            lambda item: run_checkpoint(item[1], args.output, item[0], record=args.record),
            checkpoints,
        ))
    report = {
        "seed": 2026,
        "scenarios": args.scenarios,
        "base_playback_speed": 5,
        "implementation_sha256": fingerprint,
        "implementation_unchanged": fingerprint == evaluation_implementation_hash(),
        "cases": cases,
        "failed_checkpoints": [row["source_seconds"] for row in cases if not row["completed"]],
        "failed_cases": [
            {"scenario": row["scenario"], "source_seconds": row["source_seconds"]}
            for row in cases if not row["completed"]
        ],
    }
    (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if report["failed_checkpoints"]:
        raise RuntimeError(f"Failed scenario checkpoints: {report['failed_cases']}")


if __name__ == "__main__":
    from subsea_copilot.llm.copilot_sdk import close_hosts

    try:
        main()
    finally:
        close_hosts()

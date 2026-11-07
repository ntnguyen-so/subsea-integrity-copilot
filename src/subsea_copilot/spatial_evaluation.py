"""Recorded numerical windows and real, truth-blind agents on extended networks."""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from uuid import uuid4

from .budgets import ROOT_WATCHDOG_SECONDS, WORKER_POLL_LIMIT
from .config import Settings
from .contracts import WindowSnapshot, utc_now
from .diagnostics import analyze_window
from .evaluation_mapping import run_mapping
from .evaluation_metrics import score_report
from .golden_data import dataset_hash
from .golden_evaluation import grounded_case_evidence, install_golden_input, judge_candidate_report
from .golden_judge import calibration_packets, run_judge
from .grounding import source_texts
from .ingest import normalize_records
from .monitoring import AUTO_QUESTION, Monitor
from .operations_evaluation import audit_operations
from .qualification import TERMINALS, qualification_model_factory
from .reference_evaluation import (
    PUBLIC_REPORT,
    evaluation_implementation_hash,
    mapping_controls,
    read_evaluation,
    reference_cases,
    reference_dataset,
    truth_labels,
    write_report,
)
from .replay_sources import freeze_replay_source
from .runtime.checkpointer import postgres_checkpointer
from .runtime.workflow import AgentService
from .spatial_data import (
    CHECKPOINTS,
    DURATION_SECONDS,
    spatial_cases,
    spatial_dataset,
    spatial_truth,
)
from .store import Store
from .telemetry import Telemetry

logger = logging.getLogger(__name__)


def spatial_metrics(report: dict[str, Any]) -> dict[str, Any]:
    metrics = score_report(report)
    # The injected footprint is continuous, not a detector-threshold truth label.
    metrics["groups"] = {
        name: value for name, value in metrics["groups"].items() if not name.startswith("detector_")
    }
    metrics["unit"] = "network/checkpoint; related windows are not independent trials"
    return metrics


def frame_record(
    snapshot: WindowSnapshot,
    truth: dict[str, Any],
    review_case_id: str | None,
) -> dict[str, Any]:
    summaries = {
        item.sensor_id: item.value
        for item in snapshot.evidence.values()
        if item.kind == "channel_summary" and item.channel == "pressure"
    }
    return {
        "source_seconds": snapshot.end_seconds,
        "window_start_seconds": max(0, snapshot.end_seconds - 60),
        "snapshot_id": snapshot.id,
        "input_hash": snapshot.input_hash,
        "truth": truth,
        "review_case_id": review_case_id,
        "detector": {
            "pressure_anomaly_sensors": sorted(
                item.sensor_id for item in snapshot.quality.findings if item.anomaly_count
            ),
            "missing_value_sensors": sorted(
                item.sensor_id
                for item in snapshot.quality.findings
                if item.missing or item.hard_excluded
            ),
            "coverage": snapshot.quality.coverage,
        },
        "pressure_summaries": summaries,
    }


def public_task(store: Store, task: dict[str, Any]) -> dict[str, Any]:
    saved = store.get_task(task["id"])
    return {
        **task,
        "created_at": saved.created_at.isoformat(),
        "updated_at": saved.updated_at.isoformat(),
        "summary": saved.result.summary if saved.result else None,
    }


def run_spatial_evaluation(
    output: Path,
    *,
    seed: int,
    split: str,
    agent_model: str = "gpt-6.1-sol",
    evaluator_model: str = "gpt-6.1-terra",
) -> dict[str, Any]:
    if (
        os.environ.get("SUBSEA_TRACE_CONTENT") != "1"
        or os.environ.get("SUBSEA_SYNTHETIC_ONLY") != "1"
    ):
        raise ValueError("Spatial evaluation requires explicit synthetic trace capture")
    if (output / "report.json").exists():
        raise ValueError("Use a fresh output directory; recorded attempts are immutable")
    prior = read_evaluation()
    if prior["status"] == "running":
        raise ValueError("An evaluation is already active")
    settings = Settings.from_env()
    recipes = spatial_cases()
    datasets = [
        spatial_dataset(case, seed + index * 1009, settings.site_id)
        for index, case in enumerate(recipes)
    ]
    report: dict[str, Any] = {
        "version": "spatial-evaluation-v1",
        "status": "running",
        "run_id": uuid4().hex,
        "created_at": utc_now().isoformat(),
        "seed": seed,
        "split": split,
        "agent_model": agent_model,
        "evaluator_model": evaluator_model,
        "implementation_sha256": evaluation_implementation_hash(),
        "planned_cases": len(recipes) * (len(CHECKPOINTS) + 1),
        "planned_networks": len(recipes),
        "duration_seconds": DURATION_SECONDS,
        "checkpoints_seconds": list(CHECKPOINTS),
        "frame_hop_seconds": 15,
        "mapping_calibration": [],
        "judge_calibration": [],
        "previous_runs": [
            *prior.get("previous_runs", []),
            {
                key: prior.get(key)
                for key in (
                    "version",
                    "run_id",
                    "created_at",
                    "split",
                    "seed",
                    "status",
                    "metrics",
                    "implementation_sha256",
                )
            },
        ]
        if prior["status"] != "not_run"
        else [],
        "limitations": [
            "Three independent 112-instrument, seven-segment, 11.2 km recordings of 360 seconds.",
            "Recorded 60-second numerical windows are sampled every 15 source seconds.",
            "Agents run at predeclared 150/360-second checkpoints only when pressure anomalies "
            "exist. This evaluates classification/localization, not automatic admission latency.",
            "Source ingestion is frozen during each real investigation; inference wall time "
            "and source time are separate. Playback compresses time, not agent computation.",
            "Both checkpoints and failed/withheld outputs count. Adjacent windows share data "
            "and are not independent population trials.",
            "The broad-footprint source remains in localization recall even when its interval "
            "is withheld. The 400 m maximum interval is unchanged.",
            "Continuous weak physical influence has no binary anomaly ground-truth threshold; "
            "numerical flags are displayed, not assigned fabricated precision/recall labels.",
            "Labels and recipes never enter runtime tools or truth-blind output extraction.",
            "Model-based extraction may make semantic errors; exact quotes remain inspectable.",
            "Generated pressure fields are not field-calibrated hydraulic models.",
            "Seed holdout changes noise, not the pattern families. Field reliability is unproven.",
        ],
        "networks": [
            {
                "id": case["id"],
                "name": case["name"],
                "status": "queued",
                "pack": dataset.pack.model_dump(mode="json"),
                "dataset_sha256": dataset_hash(dataset),
                "frozen_source": freeze_replay_source(dataset),
                "source_labels": case,
                "frames": [],
            }
            for case, dataset in zip(recipes, datasets, strict=True)
        ],
        "cases": [
            {
                "case_id": f"{case['id']}@{end}",
                "network_id": case["id"],
                "source_seconds": end,
                "name": f"{case['name']} at {end} s",
                "status": "queued",
                "dataset_sha256": dataset_hash(dataset),
                "truth": spatial_truth(case, dataset, end),
            }
            for case, dataset in zip(recipes, datasets, strict=True)
            for end in (60, *CHECKPOINTS)
        ],
    }
    lock = threading.RLock()

    def save() -> None:
        report["metrics"] = spatial_metrics(report)
        write_report(output / "report.json", report)
        write_report(PUBLIC_REPORT, report)

    save()
    telemetry = Telemetry(runtime_dir=settings.runtime_dir)
    evaluator = qualification_model_factory(settings, evaluator_model)("operator_response", "live")
    catalog = [
        {"id": item.id, "station_id": item.station_id, "segment_id": item.segment_id}
        for item in datasets[0].pack.sensors
    ]
    for control in mapping_controls():
        extraction = run_mapping(
            evaluator,
            {
                "answer": {"text": control["text"]},
                "competing_causes": [{"text": control["competing_text"]}]
                if control.get("competing_text")
                else [],
            },
            catalog,
            telemetry,
            tenant_id="spatial-calibration",
            generation_id=report["run_id"],
        )
        mapping = extraction["mapping"] or {}
        leaks = {
            (
                item["segment_id"],
                item["assertion"],
                (item["interval"] or {}).get("start_m"),
                (item["interval"] or {}).get("end_m"),
            )
            for item in mapping.get("leaks", [])
        }
        issues = {
            (item["sensor_id"], item["kind"], item["assertion"])
            for item in mapping.get("sensor_issues", [])
        }
        report["mapping_calibration"].append(
            {
                "name": control["name"],
                **extraction,
                "passed": extraction["status"] == "completed"
                and leaks == control["leaks"]
                and issues == control["issues"]
                and mapping.get("instrumentation_concern") == control["instrumentation"],
            }
        )
        save()

    control_case = reference_cases()[0]
    control_data = reference_dataset(control_case, seed, settings.site_id)
    control_snapshot = analyze_window(
        control_data.pack,
        normalize_records(control_data.baseline, control_data.pack),
        normalize_records(control_data.records, control_data.pack),
        generation_id="spatial-judge-calibration",
        end_seconds=60,
        clock_seconds=65,
        epoch=control_data.epoch,
    )
    control_truth = truth_labels(control_case, control_data)
    evidence = grounded_case_evidence(control_snapshot, {"report": {}})
    for control in calibration_packets(
        evidence,
        {
            "source_truth": control_truth["leak_source"],
            "hypothesis": "suspected_leak",
            "inspection": control_truth["expected_inspection"],
            "missing_or_invalid": False,
        },
    ):
        receipt = run_judge(
            evaluator,
            control["packet"],
            telemetry,
            identity=control["identity"],
            tenant_id="spatial-calibration",
            generation_id=report["run_id"],
        )
        report["judge_calibration"].append({**receipt, "expected_pass": control["expected_pass"]})
        save()

    def run_network(index: int) -> None:
        network, recipe, dataset = report["networks"][index], recipes[index], datasets[index]
        rows = {
            row["source_seconds"]: row
            for row in report["cases"]
            if row["network_id"] == recipe["id"]
        }
        tenant = "spatial-eval-" + uuid4().hex[:12]
        with lock:
            network.update(status="running", tenant_id=tenant)
            save()
        try:
            with (
                Store(
                    settings.database_dsn,
                    tenant,
                    settings.site_id,
                    settings.tools_dsn,
                    qualification=True,
                ) as store,
                postgres_checkpointer(settings.checkpoint_dsn) as saver,
            ):
                service = AgentService(
                    store,
                    qualification_model_factory(settings, agent_model),
                    saver,
                    telemetry,
                )
                monitor = Monitor(store, service, telemetry)
                replay = install_golden_input(
                    monitor,
                    dataset,
                    "live",
                    duration_seconds=DURATION_SECONDS,
                )
                network["generation_id"] = replay.id
                source = monitor._source(replay)
                for end in range(60, DURATION_SECONDS + 1, 15):
                    replay = store.save_replay(
                        replay.model_copy(
                            update={"clock_seconds": end + dataset.pack.lateness_seconds}
                        ),
                        expected_version=replay.version,
                    )
                    monitor._release(replay, source)
                    snapshot = monitor._snapshot(replay, source, end)
                    store.save_window(snapshot)
                    replay = store.save_replay(
                        replay.model_copy(
                            update={"latest_window_id": snapshot.id, "last_endpoint": end}
                        ),
                        expected_version=replay.version,
                    )
                    row = rows.get(end)
                    frame = frame_record(
                        snapshot,
                        spatial_truth(recipe, dataset, end),
                        row["case_id"] if row else None,
                    )
                    with lock:
                        network["frames"].append(frame)
                        if row:
                            row.update(
                                snapshot_id=snapshot.id,
                                input_hash=snapshot.input_hash,
                                detector=frame["detector"],
                                root_count=0,
                                generation_id=replay.id,
                                tenant_id=tenant,
                            )
                        save()
                    if not row:
                        continue
                    if not frame["detector"]["pressure_anomaly_sensors"]:
                        with lock:
                            row.update(
                                status="completed"
                                if not row["truth"]["pressure_trigger"]
                                else "failed",
                                error_code=None
                                if not row["truth"]["pressure_trigger"]
                                else "missed_pressure_trigger",
                            )
                            save()
                        continue
                    started = time.monotonic()
                    agent_started_at = utc_now().isoformat()
                    root = service.submit_question(
                        replay,
                        snapshot,
                        AUTO_QUESTION,
                        f"spatial-checkpoint-{end}",
                    )
                    with lock:
                        row.update(
                            status="running_agents",
                            root_id=root.id,
                            root_count=1,
                            agent_started_at=agent_started_at,
                        )
                        save()
                    for _ in range(WORKER_POLL_LIMIT):
                        if root.state in TERMINALS:
                            break
                        if time.monotonic() - started > ROOT_WATCHDOG_SECONDS:
                            raise RuntimeError("spatial_root_watchdog")
                        if not service.run_once():
                            time.sleep(0.05)
                        root = store.get_task(root.id)
                        tasks = [
                            task for task in store.list_tasks(replay.id)
                            if task.root_id == root.id
                        ]
                        with lock:
                            row["agent_tasks"] = [
                                public_task(store, {
                                    "id": task.id, "role": task.role, "state": task.state,
                                    "root_id": task.root_id, "snapshot_id": task.snapshot_id,
                                })
                                for task in tasks
                            ]
                            row["activity"] = [
                                event.model_dump(mode="json")
                                for event in store.events(replay.id, limit=1000)
                                if event.task_id in {task.id for task in tasks}
                            ]
                            save()
                    if root.state not in TERMINALS:
                        raise RuntimeError("spatial_root_not_terminal")
                    elapsed = round(time.monotonic() - started, 3)
                    audit = audit_operations(store, root, snapshot)
                    if root.result:
                        audit["grounded_source_texts"] = source_texts(
                            root.result,
                            snapshot,
                            store.tool_receipts(root.id),
                            root.knowledge_packet,
                        )
                    write_report(output / f"{row['case_id'].replace('@', '-')}-audit.json", audit)
                    activity = [
                        event.model_dump(mode="json")
                        for event in store.events(replay.id, limit=1000)
                        if event.task_id in {task["id"] for task in audit["tasks"]}
                    ]
                    with lock:
                        row.update(
                            state=root.state,
                            error_code=root.error_code,
                            accepted_report=bool(audit["report"]["completed"]),
                            answer=audit["report"].get("answer"),
                            authorized_inspection=audit["report"].get("inspection"),
                            interpretation=audit["report"].get("interpretation"),
                            agent_calls=audit["fresh_model_calls"],
                            agent_elapsed_seconds=elapsed,
                            model_receipts=audit["model_receipts"],
                            activity=activity,
                            agent_tasks=[public_task(store, task) for task in audit["tasks"]],
                            traces=[
                                {"role": task["role"], "trace": store.latest_task_trace(task["id"])}
                                for task in audit["tasks"]
                            ],
                            status="mapping_output",
                        )
                        save()
                    if row["accepted_report"] and row["interpretation"]:
                        extraction = run_mapping(
                            evaluator,
                            row["interpretation"],
                            catalog,
                            telemetry,
                            tenant_id=tenant,
                            generation_id=replay.id,
                        )
                        with lock:
                            row.update(extraction=extraction, status="judging_explanation")
                            save()
                        truth = row["truth"]
                        receipt = run_judge(
                            evaluator,
                            {
                                "case_evidence": grounded_case_evidence(snapshot, audit),
                                "hidden_expected_outcomes": {
                                    "source_truth": truth["leak_source"],
                                    "hypothesis": "suspected_leak"
                                    if truth["leak_source"]
                                    else "sensor_or_telemetry_issue",
                                    "inspection_policy": (
                                        "Only measured, qualified intervals are acceptable. "
                                        "Do not demand an exact source point; any interval "
                                        "must contain the source on the correct branch and "
                                        "must not exceed 400 m. Justified withholding is "
                                        "not a localization success in deterministic scoring."
                                    ),
                                    "missing_or_invalid": bool(truth["missing_value_sensors"]),
                                    "source_sensor_issue_labels": truth["sensor_issues"],
                                },
                                "candidate_report": judge_candidate_report(audit["report"]),
                            },
                            telemetry,
                            identity=f"spatial-{recipe['id']}-{end}",
                            tenant_id=tenant,
                            generation_id=replay.id,
                        )
                        with lock:
                            row["judge"] = receipt
                            save()
                    with lock:
                        row["status"] = (
                            "completed"
                            if (
                                row.get("accepted_report")
                                and (row.get("extraction") or {}).get("status") == "completed"
                            )
                            else "failed"
                        )
                        save()
                with lock:
                    network["status"] = "completed"
                    save()
        except Exception as exc:
            logger.error("Spatial network %s failed: %s", recipe["id"], type(exc).__name__)
            with lock:
                network.update(status="failed", error_code=getattr(exc, "code", type(exc).__name__))
                for row in rows.values():
                    if row["status"] not in {"completed", "failed"}:
                        row.update(status="failed", error_code=network["error_code"])
                save()

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(run_network, range(len(recipes))))
    with lock:
        report.update(
            status="completed",
            completed_at=utc_now().isoformat(),
            implementation_unchanged=report["implementation_sha256"]
            == evaluation_implementation_hash(),
        )
        save()
    return report

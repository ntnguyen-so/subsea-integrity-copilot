"""Record extended-network diagnostics and truth-blind investigations over source time.

Authored spatial/temporal recipes yield frozen 112-instrument inputs. Production
normalization and 60-second windows advance every five seconds; measured pressure or
instrument signals admit reviews without consulting hidden labels. Source ingestion
pauses through inference, mapping and result admission, so source-time delays and model
wall time remain separate. Networks run concurrently, but each network is sequential.

Frames retain diagnostics/truth for inspection; review rows retain actual tasks,
receipts, extraction and judge opinion. Deterministic scores include failed/withheld
reviews and overlapping-window denominators, not independent field observations.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .budgets import ROOT_WATCHDOG_SECONDS, WORKER_POLL_LIMIT
from .config import Settings
from .contracts import SitePack, WindowSnapshot, utc_now
from .diagnostics import analyze_window
from .evaluation_mapping import run_mapping
from .evaluation_metrics import score_report
from .golden_data import dataset_hash
from .golden_evaluation import grounded_case_evidence, install_golden_input, judge_candidate_report
from .golden_judge import calibration_packets, run_judge
from .grounding import source_texts
from .ingest import normalize_records
from .monitoring import AUTO_QUESTION, Monitor, instrument_signals, pressure_context_ready
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
    temporal_cases,
)
from .store import Store
from .telemetry import Telemetry
from .temporal_evaluation import (
    SUITE_NAMES,
    agent_process_metrics,
    lifecycle_metrics,
    publish_evaluation,
)

logger = logging.getLogger(__name__)

INSTRUMENT_REVIEW_COOLDOWN_SECONDS = 60
INSTRUMENT_REVIEW_QUESTION = (
    AUTO_QUESTION + " Reassess instrument-quality changes using paired readings and recent "
    "behaviour, including drift, spikes, stuck readings, invalid values and missing samples. "
    "Identify each supported suspect instrument and issue type, and retain unresolved "
    "concerns explicitly. A usable pressure anomaly alone does not establish an instrument fault."
)


@dataclass
class InstrumentReviews:
    """Track measured quality signals with a 60-source-second refresh cooldown."""
    checked: set[tuple[str, str]] = field(default_factory=set)
    last_review_seconds: int | None = None

    def due(self, snapshot: WindowSnapshot, pack: SitePack) -> str | None:
        if snapshot.quality.status == "WARMING_UP":
            return None
        signals = instrument_signals(snapshot, pack)
        novel = signals - self.checked
        cooled = (
            self.last_review_seconds is None
            or snapshot.end_seconds - self.last_review_seconds >= INSTRUMENT_REVIEW_COOLDOWN_SECONDS
        )
        if cooled and novel:
            return "automatic_instrument_context"
        if signals & self.checked and cooled and self.last_review_seconds is not None:
            return "periodic_instrument_review"
        return None

    def reviewed(self, snapshot: WindowSnapshot, pack: SitePack) -> None:
        self.checked = instrument_signals(snapshot, pack)
        self.last_review_seconds = snapshot.end_seconds


def spatial_metrics(report: dict[str, Any]) -> dict[str, Any]:
    """Reuse answer scores but omit fabricated binary detector truth for continuous footprints."""
    metrics = score_report(report)
    # The injected footprint is continuous, not a detector-threshold truth label.
    metrics["groups"] = {
        name: value for name, value in metrics["groups"].items() if not name.startswith("detector_")
    }
    metrics["unit"] = "network/review; related windows are not independent trials"
    metrics["timing"] = spatial_timing(report)
    if report.get("suite") in {"recovery", "non_leak"}:
        metrics["temporal"] = lifecycle_metrics(report)
    return metrics


def spatial_timing(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Separate branch alert, admission, checked diagnosis and accepted answer timestamps.

    Correct-branch credit requires the review's source time, snapshot and input hash to
    match a frame. A succeeded checked diagnosis is preliminary, not a final report.
    This summary follows the first source; lifecycle_metrics handles multiple episodes.
    """
    timings = []
    for network in report.get("networks", []):
        frames = network.get("frames", [])
        source = next(
            (frame["truth"]["leak_source"] for frame in frames if frame["truth"]["leak_source"]),
            None,
        )
        if not source:
            continue
        onset = source.get("start_seconds")
        alert = next(
            (frame["source_seconds"] for frame in frames
             if (onset is None or frame["source_seconds"] >= onset)
             and any(sensor.startswith(source["segment_id"] + "-")
                    for sensor in frame["detector"]["pressure_anomaly_sensors"])),
            None,
        )
        rows = sorted(
            (row for row in report["cases"] if row.get("network_id") == network["id"]),
            key=lambda row: row["source_seconds"],
        )
        admitted = next(
            (row for row in rows if row.get("root_count") and onset is not None
             and row["source_seconds"] >= onset), None,
        )
        recognized = next(
            (row for row in rows if row.get("accepted_report")
             and (onset is None or row["source_seconds"] >= onset)
             and (row.get("extraction") or {}).get("status") == "completed"
             and any(frame.get("review_case_id") == row["case_id"]
                     and frame["source_seconds"] == row["source_seconds"]
                     and frame.get("snapshot_id") == row.get("snapshot_id")
                     and frame.get("input_hash") == row.get("input_hash")
                     for frame in frames)
             and any(item["segment_id"] == source["segment_id"]
                     for item in (((row.get("extraction") or {}).get("mapping") or {})
                                  .get("leaks", [])))), None,
        )
        checked_warning = next(
            ((row, finding) for row in rows for task in row.get("agent_tasks", [])
             if (finding := task.get("checked_finding"))
             and task["role"] == "event_diagnosis" and task["state"] == "SUCCEEDED"
             and task["root_id"] == row.get("root_id")
             and task["snapshot_id"] == finding["snapshot_id"] == row.get("snapshot_id")
             and finding["input_hash"] == row.get("input_hash")
             and finding["hypothesis"] == "suspected_leak"
             and finding.get("final_report") is False
             and any(frame.get("review_case_id") == row["case_id"]
                     and frame["source_seconds"] == row["source_seconds"]
                     and frame.get("snapshot_id") == row.get("snapshot_id")
                     and frame.get("input_hash") == row.get("input_hash")
                     for frame in frames)
             and source["segment_id"] in finding["segment_ids"]),
            None,
        )
        warning_wall_seconds = None
        if checked_warning and checked_warning[0].get("agent_started_at"):
            warning_wall_seconds = (
                datetime.fromisoformat(checked_warning[1]["available_at"])
                - datetime.fromisoformat(checked_warning[0]["agent_started_at"])
            ).total_seconds()
        timings.append({
            "network_id": network["id"],
            "source_onset_seconds": onset,
            "first_branch_alert_seconds": alert,
            "first_agent_admission_seconds": admitted["source_seconds"] if admitted else None,
            "first_correct_branch_review_seconds": (
                recognized["source_seconds"] if recognized else None
            ),
            "admission_delay_source_seconds": (
                admitted["source_seconds"] - onset if admitted and onset is not None else None
            ),
            "correct_branch_delay_source_seconds": (
                recognized["source_seconds"] - onset
                if recognized and onset is not None else None
            ),
            "correct_branch_model_wall_seconds": (
                recognized.get("agent_elapsed_seconds") if recognized else None
            ),
            "first_checked_warning_source_seconds": (
                checked_warning[0]["source_seconds"] if checked_warning else None
            ),
            "first_checked_warning_model_wall_seconds": warning_wall_seconds,
            "source_frozen_during_inference": True,
        })
    return timings


def frame_record(
    snapshot: WindowSnapshot,
    truth: dict[str, Any],
    review_case_id: str | None,
) -> dict[str, Any]:
    """Persist current measured evidence and hidden grading truth, not a future agent answer."""
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
    """Expose task timing and only a succeeded, snapshot-checked legacy leak warning."""
    saved = store.get_task(task["id"])
    checked_finding = None
    if (
        saved.role == "event_diagnosis" and saved.state == "SUCCEEDED"
        and saved.decision_policy == "legacy-v1"
        and saved.result and saved.result.outcome == "supported"
        and saved.result.hypothesis == "suspected_leak"
    ):
        snapshot = store.get_window(saved.snapshot_id)
        if snapshot and snapshot.event.hypothesis == saved.result.hypothesis:
            checked_finding = {
                "hypothesis": saved.result.hypothesis,
                "segment_ids": snapshot.event.segment_ids,
                "snapshot_id": snapshot.id,
                "input_hash": snapshot.input_hash,
                "available_at": saved.updated_at.isoformat(),
                "final_report": False,
            }
    return {
        **task,
        "created_at": saved.created_at.isoformat(),
        "updated_at": saved.updated_at.isoformat(),
        "summary": saved.result.summary if saved.result else None,
        "checked_finding": checked_finding,
    }


def run_spatial_evaluation(
    output: Path,
    *,
    seed: int,
    split: str,
    agent_model: str = "gpt-6.1-sol",
    evaluator_model: str = "gpt-6.1-terra",
    suite: str = "current",
    publish: bool = True,
) -> dict[str, Any]:
    """Run isolated recordings with fixed checkpoints plus measurement-admitted follow-ups.

    Current-suite checkpoints are 60/150/360; lifecycle suites use 60/180/240/360 and
    force quiet reassessments after 60. Dynamic reviews increase planned_cases, retaining
    early and failed attempts. Split is recorded metadata, not a recipe-family filter.
    Mapping/judge controls precede networks. Each completed answer must have accepted
    runtime output and completed extraction; judge opinion stays separate. Network
    exceptions mark outstanding review rows failed and the overall run incomplete.
    """
    if (
        os.environ.get("SUBSEA_TRACE_CONTENT") != "1"
        or os.environ.get("SUBSEA_SYNTHETIC_ONLY") != "1"
    ):
        raise ValueError("Spatial evaluation requires explicit synthetic trace capture")
    if (output / "report.json").exists():
        raise ValueError("Use a fresh output directory; recorded attempts are immutable")
    prior = read_evaluation()
    if publish and (prior["status"] == "running" or any(
        item["status"] == "running" for item in prior.get("additional_evaluations", [])
    )):
        raise ValueError("An evaluation is already active")
    if suite not in SUITE_NAMES:
        raise ValueError(f"Unknown spatial evaluation suite: {suite}")
    previous = prior if suite == "current" else next(
        (item for item in prior.get("additional_evaluations", []) if item.get("suite") == suite),
        {"status": "not_run"},
    )
    settings = Settings.from_env()
    recipes = spatial_cases() if suite == "current" else temporal_cases(suite)
    checkpoints = CHECKPOINTS if suite == "current" else tuple(
        end for end in (180, 240, DURATION_SECONDS) if 60 < end <= DURATION_SECONDS
    )
    checkpoints = tuple(dict.fromkeys(checkpoints))
    datasets = [
        spatial_dataset(case, seed + index * 1009, settings.site_id)
        for index, case in enumerate(recipes)
    ]
    report: dict[str, Any] = {
        "version": "spatial-evaluation-v1",
        "suite": suite,
        "suite_name": SUITE_NAMES[suite],
        "status": "running",
        "run_id": uuid4().hex,
        "created_at": utc_now().isoformat(),
        "seed": seed,
        "split": split,
        "agent_model": agent_model,
        "evaluator_model": evaluator_model,
        "implementation_sha256": evaluation_implementation_hash(),
        "planned_cases": len(recipes) * (len(checkpoints) + 1),
        "planned_networks": len(recipes),
        "network_workers": len(recipes),
        "publication": "dashboard" if publish else "isolated-output-only",
        "duration_seconds": DURATION_SECONDS,
        "checkpoints_seconds": list(checkpoints),
        "frame_hop_seconds": datasets[0].pack.hop_seconds,
        "admission_policy": "immediate-measurement-review-v3",
        "admission_context_seconds": 0,
        "instrument_review_cooldown_seconds": INSTRUMENT_REVIEW_COOLDOWN_SECONDS,
        "simulation_policy": "pause-until-result-admission-v1",
        "mapping_calibration": [],
        "judge_calibration": [],
        "previous_runs": [
            *previous.get("previous_runs", []),
            {
                key: previous.get(key)
                for key in (
                    "version",
                    "run_id",
                    "created_at",
                    "split",
                    "seed",
                    "status",
                    "metrics",
                    "implementation_sha256",
                    "implementation_unchanged",
                )
            },
        ]
        if previous["status"] != "not_run"
        else [],
        "limitations": [
            f"{len(recipes)} separate synthetic 112-instrument recordings of "
            f"{DURATION_SECONDS} source seconds; not independent field trials.",
            "Recorded 60-second numerical windows use the site's 5-second monitoring hop.",
            "The first pressure alert immediately admits a truth-blind review of the acquired "
            "measurements. No numerical event, persistence or location verdict is required. "
            + (
                "The 150/360-second checkpoints remain for comparison."
                if suite == "current" else
                "Fixed quiet reassessments are recorded at 180/240/end source seconds."
            ),
            "New instrument-quality signals need no extra acquisition delay; persistent "
            "concerns are refreshed with a 60-source-second review cooldown. These signals "
            "are measurement evidence, not confirmed fault labels.",
            "Lifecycle/control suites add fixed reassessments at 180/240/end source seconds, "
            "even when pressure is quiet, and rearm pressure admission after alerts clear. "
            "These declared evaluation review slots do not use hidden event labels.",
            "Source ingestion is frozen through agent investigation, output mapping and result "
            "admission before the next data window. Original inference wall time "
            "and source time are separate. Playback compresses time, not agent computation.",
            "Early reviews, checkpoints and failed/withheld outputs count. Windows share data "
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
                "truth": {
                    **spatial_truth(case, dataset, end),
                    **({"review_required": True} if suite != "current" and end > 60 else {}),
                },
                "force_review": suite != "current" and end > 60,
                "admission_kind": "periodic_reassessment" if suite != "current" else "checkpoint",
            }
            for case, dataset in zip(recipes, datasets, strict=True)
            for end in (60, *checkpoints)
        ],
    }
    lock = threading.RLock()

    def save() -> None:
        report["metrics"] = spatial_metrics(report)
        report["agent_process"] = agent_process_metrics(report)
        write_report(output / "report.json", report)
        if publish:
            publish_evaluation(report, PUBLIC_REPORT)

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
                first_alert: int | None = None
                early_reviewed = False
                instrument_reviews = InstrumentReviews()
                for end in range(60, DURATION_SECONDS + 1, dataset.pack.hop_seconds):
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
                    pressure_alert = (
                        snapshot.quality.status != "WARMING_UP"
                        and any(item.anomaly_count for item in snapshot.quality.findings)
                    )
                    if suite != "current" and not pressure_alert:
                        early_reviewed = False
                        first_alert = None
                    if not early_reviewed:
                        if not pressure_alert:
                            first_alert = None
                        elif first_alert is None:
                            first_alert = end
                        if first_alert is not None and pressure_context_ready(
                            snapshot, dataset.pack, first_alert,
                            context_seconds=0,
                        ):
                            early_reviewed = True
                            if row is None:
                                row = {
                                    "case_id": f"{recipe['id']}@{end}",
                                    "network_id": recipe["id"],
                                    "source_seconds": end,
                                    "name": f"{recipe['name']} first pressure review at {end} s",
                                    "status": "queued",
                                    "dataset_sha256": dataset_hash(dataset),
                                    "truth": spatial_truth(recipe, dataset, end),
                                    "admission_kind": "automatic_pressure_context",
                                }
                                rows[end] = row
                                with lock:
                                    report["cases"].append(row)
                                    report["planned_cases"] += 1
                    instrument_kind = instrument_reviews.due(snapshot, dataset.pack)
                    if row is None and instrument_kind:
                        row = {
                            "case_id": f"{recipe['id']}@{end}",
                            "network_id": recipe["id"],
                            "source_seconds": end,
                            "name": f"{recipe['name']} instrument follow-up at {end} s",
                            "status": "queued",
                            "dataset_sha256": dataset_hash(dataset),
                            "truth": spatial_truth(recipe, dataset, end),
                            "admission_kind": instrument_kind,
                            "instrument_review_sensors": sorted({
                                identifier for identifier, _kind
                                in instrument_signals(snapshot, dataset.pack)
                            }),
                        }
                        rows[end] = row
                        with lock:
                            report["cases"].append(row)
                            report["planned_cases"] += 1
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
                    if (
                        not row.get("force_review")
                        and
                        not frame["detector"]["pressure_anomaly_sensors"]
                        and not instrument_signals(snapshot, dataset.pack)
                    ):
                        with lock:
                            row.update(
                                status="completed"
                                if not row["truth"]["review_required"]
                                else "failed",
                                error_code=None
                                if not row["truth"]["review_required"]
                                else "missed_pressure_trigger" if row["truth"]["pressure_trigger"]
                                else "missed_instrument_trigger",
                            )
                            save()
                        continue
                    started = time.monotonic()
                    agent_started_at = utc_now().isoformat()
                    instrument_reviews.reviewed(snapshot, dataset.pack)
                    root = service.submit_question(
                        replay,
                        snapshot,
                        INSTRUMENT_REVIEW_QUESTION,
                        f"spatial-checkpoint-{end}",
                    )
                    service.root_id = root.id
                    with lock:
                        row.update(
                            status="running_agents",
                            root_id=root.id,
                            root_count=1,
                            agent_started_at=agent_started_at,
                        )
                        network["held_source_seconds"] = end
                        save()
                    for _ in range(WORKER_POLL_LIMIT):
                        if root.state in TERMINALS:
                            break
                        progressed = service.run_once()
                        if not progressed:
                            time.sleep(0.05)
                        root = store.get_task(root.id)
                        if root.state in TERMINALS:
                            break
                        if time.monotonic() - started > ROOT_WATCHDOG_SECONDS:
                            raise RuntimeError("spatial_root_watchdog")
                        if not progressed:
                            continue
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
                            agent_audit={
                                "checks": audit["checks"],
                                "validation_errors": audit["validation_errors"],
                                "critic_decisions": audit["critic_decisions"],
                                "fresh_tool_calls": audit["fresh_tool_calls"],
                                "tool_errors": audit["tool_errors"],
                            },
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
                                    else "sensor_or_telemetry_issue"
                                    if truth["sensor_issues"]
                                    else "no_injected_leak_or_instrument_fault",
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
                        row["result_admitted_at"] = utc_now().isoformat()
                        row["investigation_elapsed_seconds"] = round(time.monotonic() - started, 3)
                        row["status"] = (
                            "completed"
                            if (
                                row.get("accepted_report")
                                and (row.get("extraction") or {}).get("status") == "completed"
                            )
                            else "failed"
                        )
                        network["held_source_seconds"] = None
                        save()
                with lock:
                    network["status"] = "completed"
                    save()
        except Exception as exc:
            logger.exception("Spatial network %s failed: %s", recipe["id"], type(exc).__name__)
            with lock:
                failed_at = utc_now()
                code = getattr(exc, "code", None)
                if code is None:
                    code = str(exc) if str(exc) in {
                        "spatial_root_watchdog", "spatial_root_not_terminal",
                    } else type(exc).__name__
                network.update(status="failed", error_code=code)
                for row in rows.values():
                    if row["status"] not in {"completed", "failed"}:
                        row.update(status="failed", error_code=network["error_code"])
                        if row.get("agent_started_at"):
                            row.update(
                                result_admitted_at=failed_at.isoformat(),
                                investigation_elapsed_seconds=round((
                                    failed_at - datetime.fromisoformat(row["agent_started_at"])
                                ).total_seconds(), 3),
                            )
                network["held_source_seconds"] = None
                save()

    with ThreadPoolExecutor(max_workers=len(recipes)) as executor:
        list(executor.map(run_network, range(len(recipes))))
    with lock:
        report.update(
            status="incomplete" if any(
                network["status"] == "failed" for network in report["networks"]
            ) else "completed",
            completed_at=utc_now().isoformat(),
            implementation_unchanged=report["implementation_sha256"]
            == evaluation_implementation_hash(),
        )
        save()
    return report


def run_spatial_evaluations(
    output: Path, *, cohorts: dict[str, tuple[int, str]],
    agent_model: str = "gpt-6.1-sol", evaluator_model: str = "gpt-6.1-terra",
    publish: bool = True,
) -> dict[str, Any]:
    """Start every suite immediately; publish finished suites through one writer."""
    if not cohorts or set(cohorts) - SUITE_NAMES.keys():
        raise ValueError("Select known spatial evaluation suites")
    if output.exists():
        raise ValueError("Use a fresh output directory; recorded attempts are immutable")
    output.mkdir(parents=True)
    summary: dict[str, Any] = {
        "version": "parallel-spatial-evaluation-v1",
        "status": "running", "suite_workers": len(cohorts), "suites": {},
        "implementation_sha256": evaluation_implementation_hash(),
    }
    write_report(output / "summary.json", summary)
    with ThreadPoolExecutor(max_workers=len(cohorts)) as executor:
        futures = {
            executor.submit(
                run_spatial_evaluation, output / suite,
                seed=seed, split=split, suite=suite, agent_model=agent_model,
                evaluator_model=evaluator_model, publish=False,
            ): suite
            for suite, (seed, split) in cohorts.items()
        }
        for future in as_completed(futures):
            suite = futures[future]
            try:
                report = future.result()
            except Exception as exc:
                logger.exception("Spatial suite %s failed", suite)
                summary["suites"][suite] = {
                    "status": "failed",
                    "error_code": getattr(exc, "code", type(exc).__name__),
                }
                write_report(output / "summary.json", summary)
                continue
            if publish:
                publish_evaluation(report, PUBLIC_REPORT)
            summary["suites"][suite] = {
                key: report[key] for key in (
                    "run_id", "status", "planned_cases", "metrics",
                    "implementation_unchanged",
                )
            }
            write_report(output / "summary.json", summary)
    summary.update(
        status="completed" if all(
            item["status"] == "completed" for item in summary["suites"].values()
        ) else "incomplete",
        implementation_unchanged=summary["implementation_sha256"]
        == evaluation_implementation_hash(),
        completed_at=utc_now().isoformat(),
    )
    write_report(output / "summary.json", summary)
    return summary

"""End-to-end source-labelled cohort using production monitor and agent execution.

Eight recipes extend the golden examples with other branches, a stable control and
drift. Labels come from injected source/fault schedules, not detector predictions.
Frozen content-addressed runtime inputs omit those labels. Accepted public answers
are mapped truth-blind; deterministic set metrics then compare them with source truth,
while an external model separately judges explanation quality against hidden evidence.

The caller supplies seed/split metadata; split does not filter recipe families here.
Seed holdout varies noise, not unseen pattern families. Immutable run directories,
implementation/prompt/data hashes, per-case audits and incremental public projections
preserve failures and provenance without establishing field reliability.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .budgets import ROOT_WATCHDOG_SECONDS, WORKER_POLL_LIMIT
from .config import Settings
from .contracts import content_hash, utc_now
from .evaluation_mapping import run_mapping
from .evaluation_metrics import score_report
from .golden_data import dataset_hash, generate_golden, load_cases
from .golden_evaluation import grounded_case_evidence, install_golden_input, judge_candidate_report
from .golden_judge import calibration_packets, run_judge
from .grounding import source_texts
from .monitoring import Monitor
from .operations_evaluation import audit_operations
from .prompts import prompt_catalog_provenance, prompt_manifest_sha256
from .qualification import TERMINALS, qualification_model_factory
from .replay_sources import freeze_replay_source
from .runtime.checkpointer import postgres_checkpointer
from .runtime.workflow import AgentService
from .store import Store
from .synthetic import ReplayDataset
from .telemetry import Telemetry

ROOT = Path(__file__).resolve().parents[2]
PUBLIC_REPORT = ROOT / "runtime" / "evaluation-report.json"
logger = logging.getLogger(__name__)


def evaluation_implementation_hash() -> str:
    """Hash package Python and prompt text, including docs, to detect mid-run changes."""
    package = ROOT / "src" / "subsea_copilot"
    source: dict[str, Any] = {
        path.relative_to(package).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(package.rglob("*.py"))
    }
    source["prompts"] = {
        path.name: path.read_text(encoding="utf-8")
        for path in (ROOT / "src" / "subsea_copilot" / "prompts").glob("*.md")
    }
    return content_hash(source)


def reference_cases() -> list[dict[str, Any]]:
    """Build eight authored patterns and remove golden expected-output shortcut fields."""
    cases: list[dict[str, Any]] = copy.deepcopy(load_cases()["cases"])
    for identifier, segment, mixed in (("E5", "P2", False), ("E6", "P3", True)):
        case = copy.deepcopy(cases[2 if mixed else 0])
        case.update(
            id=identifier,
            name=f"{segment} pressure event"
            + (" with independent measurement issues" if mixed else ""),
        )
        case["source"].update(segment_id=segment)
        if mixed:
            case.update(
                spikes=[{"sensor_id": "P1-ST1-A", "phase_seconds": 5}],
                invalid_sensor_ids=["P2-ST4-A"],
                gap_sensor_ids=["P1-ST4-B"],
            )
        cases.append(case)
    normal = copy.deepcopy(cases[3])
    normal.update(id="E7", name="Stable pressure and complete readings", outage=False)
    cases.append(normal)
    drift = copy.deepcopy(normal)
    drift.update(
        id="E8",
        name="One drifting instrument with a stable paired reference",
        drift_sensor_id="P3-ST2-A",
        gap_sensor_ids=["P2-ST4-B"],
    )
    cases.append(drift)
    for case in cases:
        case.pop("expected", None)
    return cases


def reference_dataset(case: dict[str, Any], seed: int, site_id: str) -> ReplayDataset:
    dataset = generate_golden(case, seed, site_id=site_id)
    if case.get("drift_sensor_id"):
        dataset = replace(
            dataset,
            records=[
                row.model_copy(
                    update={
                        "value": float(row.value)
                        - 0.02
                        * (datetime.fromisoformat(row.observed_at) - dataset.epoch).total_seconds(),
                    }
                )
                if row.sensor_id == case["drift_sensor_id"] and isinstance(row.value, (int, float))
                else row
                for row in dataset.records
            ],
        )
    return dataset


def truth_labels(case: dict[str, Any], dataset: ReplayDataset) -> dict[str, Any]:
    """Declare source/issue/anomaly identities from recipes, never runtime predictions.

    The small-network source footprint targets stations 2/3 with expected 200..600 m
    inspection bounds. Missing/invalid samples are unknown, not instrumentation proof;
    source and nuisance issues may coexist rather than forcing one exclusive class.
    """
    issues = [{"sensor_id": item["sensor_id"], "kind": "spike"} for item in case["spikes"]]
    issues += [{"sensor_id": sensor, "kind": "invalid"} for sensor in case["invalid_sensor_ids"]]
    issues += [{"sensor_id": sensor, "kind": "missing"} for sensor in case["gap_sensor_ids"]]
    if case.get("drift_sensor_id"):
        issues.append({"sensor_id": case["drift_sensor_id"], "kind": "drift"})
    if case["outage"]:
        issues = [{"sensor_id": sensor.id, "kind": "missing"} for sensor in dataset.pack.sensors]
    source = copy.deepcopy(case["source"])
    affected = [
        sensor.id
        for sensor in dataset.pack.sensors
        if source
        and sensor.segment_id == source["segment_id"]
        and sensor.station_id.endswith(("ST2", "ST3"))
    ]
    anomalies = sorted(
        set(affected) | {item["sensor_id"] for item in issues if item["kind"] in {"spike", "drift"}}
    )
    return {
        "leak_source": source,
        "sensor_issues": issues,
        "pressure_anomaly_sensors": anomalies,
        "missing_value_sensors": sorted(
            item["sensor_id"] for item in issues if item["kind"] in {"missing", "invalid"}
        ),
        "pressure_trigger": bool(anomalies),
        "expected_inspection": {
            "segment_id": source["segment_id"],
            "start_m": 200,
            "end_m": 600,
        }
        if source
        else None,
        "instrumentation_concern": any(item["kind"] != "missing" for item in issues),
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    """Replace JSON atomically with bounded Windows-lock retries and archive indexing.

    Public writes strip agent-process audits and attach independent reference/history
    projections. Completed archive reports retain their original recorded scores.
    """
    if path == PUBLIC_REPORT:
        from .temporal_evaluation import without_agent_audit_results

        report = without_agent_audit_results(report)
        agent_report = PUBLIC_REPORT.parent / "agent-reference-report.json"
        if agent_report.exists():
            report["agent_reference_evaluation"] = json.loads(
                agent_report.read_text(encoding="utf-8")
            )
        history = PUBLIC_REPORT.parent / "evaluation-history.json"
        if history.exists():
            from .evaluation_history import public_history

            report["evaluation_history"] = public_history(history)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".pending")
    temporary.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    for attempt in range(5):
        try:
            temporary.replace(path)
            if path != PUBLIC_REPORT and report.get("status") in {
                "completed", "incomplete", "failed",
            }:
                from .evaluation_history import ROOT as history_root
                from .evaluation_history import VERSIONS, rebuild_history

                if (
                    report.get("version") in VERSIONS
                    and path.resolve().is_relative_to(history_root)
                ):
                    try:
                        rebuild_history()
                    except (OSError, ValueError, TypeError) as exc:
                        logger.error(
                            "Detection report saved, but history catalog update failed: %s",
                            type(exc).__name__,
                        )
            return
        except PermissionError as exc:
            if getattr(exc, "winerror", None) not in {5, 32, 33} or attempt == 4:
                raise
            logger.warning("Report replacement blocked by a Windows file handle; retrying")
            time.sleep(0.05 * 2 ** attempt)


def read_evaluation() -> dict[str, Any]:
    """Load current or checked-in evidence, never fabricate a successful not-run result."""
    path = (
        PUBLIC_REPORT
        if PUBLIC_REPORT.exists()
        else ROOT / "docs" / "evidence" / "evaluation-report.json"
    )
    if not path.exists():
        return {
            "version": "reference-evaluation-v1",
            "status": "not_run",
            "cases": [],
            "metrics": None,
        }
    report: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if report.get("version") not in {"reference-evaluation-v1", "spatial-evaluation-v1"}:
        raise ValueError("Unrecognized evaluation report")
    from .temporal_evaluation import without_agent_audit_results

    report = without_agent_audit_results(report)
    agent_report = PUBLIC_REPORT.parent / "agent-reference-report.json"
    if agent_report.exists():
        report["agent_reference_evaluation"] = json.loads(agent_report.read_text(encoding="utf-8"))
    history = PUBLIC_REPORT.parent / "evaluation-history.json"
    if history.exists():
        from .evaluation_history import public_history

        report["evaluation_history"] = public_history(history)
    return report


def mapping_controls() -> list[dict[str, Any]]:
    """Author extraction calibration for negation, coexistence, false certainty and issue types."""
    return [
        {
            "name": "valid-pressure-anomaly-is-not-instrument-failure",
            "text": (
                "Prioritize pipeline P1 for a possible leak: inspect P1 from 200 to 600 m. "
                "P1-ST2-A, P1-ST2-B, P1-ST3-A and P1-ST3-B show a sustained joint "
                "pressure deficit. These are pressure anomalies, not identified faulty "
                "instruments. Independent reference checks are needed because a common "
                "measurement bias remains a competing explanation, not because a "
                "measurement-path problem has been identified. P2 and P3 pressure changes "
                "remain on secondary pressure and process review, not identified as "
                "separate leak sources."
            ),
            "leaks": {("P1", "suspected", 200, 600)},
            "issues": set(),
            "instrumentation": False,
            "competing_text": (
                "Measurement bias or an instrumentation problem remains a competing "
                "explanation, but the health checks for P1-ST2-A, P1-ST2-B, P1-ST3-A "
                "and P1-ST3-B show persistent anomalies rather than brief spikes or "
                "gradual drift."
            ),
        },
        {
            "name": "coexistence-and-missing",
            "text": (
                "The observed pressure pattern suggests a possible leak on pipeline P1. "
                "Prioritize inspection on P1 from 200 to 600 m. P2-ST2-A has brief spikes "
                "and needs a measurement-path check, not a confirmed hardware diagnosis. "
                "P3-ST4-B has missing readings; its pressure is unknown."
            ),
            "leaks": {("P1", "suspected", 200, 600)},
            "issues": {("P2-ST2-A", "spike", "suspected"), ("P3-ST4-B", "missing", "suspected")},
            "instrumentation": True,
        },
        {
            "name": "negations-and-healthy-comparison",
            "text": (
                "No leak-like pattern has been identified. P1-ST1-A and P1-ST1-B agree "
                "and neither is flagged as faulty. P2-ST4-B has missing readings; treat "
                "its pressure as unknown, not normal and not proof of hardware failure."
            ),
            "leaks": set(),
            "issues": {("P2-ST4-B", "missing", "suspected")},
            "instrumentation": False,
        },
        {
            "name": "preserve-incorrect-confirmation",
            "text": (
                "A leak is confirmed on pipeline P3. Inspect P3 from 42 to 42 m. "
                "P1-ST1-A is confirmed faulty. This report makes no claim about other sensors."
            ),
            "leaks": {("P3", "confirmed", 42, 42)},
            "issues": {("P1-ST1-A", "unspecified", "confirmed")},
            "instrumentation": True,
        },
        {
            "name": "screening-spike-flags-are-not-instrument-findings",
            "text": (
                "P1-ST2-A and P1-ST2-B have numerical spike flags, but their reviewed "
                "profiles show a joint pressure change, not identified instrument spikes. "
                "Neither instrument is prioritized as a suspect measurement path. "
                "No concrete instrument problem has been identified."
            ),
            "leaks": set(), "issues": set(), "instrumentation": False,
        },
        {
            "name": "plain-language-offset-and-stuck-reading",
            "text": (
                "P2-ST1-A is a suspect measurement path: its readings abruptly shifted "
                "0.7 bar lower and remained at that new level, while P2-ST1-B stayed "
                "near normal. P3-ST4-B is also suspect: its 60 received readings stayed "
                "exactly unchanged while the paired instrument continued to vary. "
                "These are measurement patterns, not confirmed hardware faults."
            ),
            "leaks": set(),
            "issues": {("P2-ST1-A", "offset", "suspected"), ("P3-ST4-B", "flatline", "suspected")},
            "instrumentation": True,
        },
    ]


def run_reference_evaluation(
    output: Path,
    *,
    seed: int,
    split: str,
    agent_model: str = "gpt-6.1-sol",
    evaluator_model: str = "gpt-6.1-terra",
) -> dict[str, Any]:
    """Freeze recipes/labels before two concurrent first-attempt production investigations.

    Mapping controls exercise truth-blind extraction before cohort cases. Judge controls
    and verdicts are separate opinion receipts; calibration failure blocks target_met
    rather than rewriting the candidate. Missing reports/mappings and exceptions remain
    failed terminal rows. Run completion does not mean all cases or metrics passed.
    """
    if (
        os.environ.get("SUBSEA_TRACE_CONTENT") != "1"
        or os.environ.get("SUBSEA_SYNTHETIC_ONLY") != "1"
    ):
        raise ValueError("Reference evaluation requires explicit synthetic trace capture")
    if (output / "report.json").exists():
        raise ValueError("Use a new output directory; prior evaluation attempts are immutable")
    settings = Settings.from_env()
    prior = read_evaluation()
    if prior["status"] == "running":
        raise ValueError("An evaluation is already active; do not overwrite its progress")
    previous_runs = list(prior.get("previous_runs", []))
    if prior["status"] != "not_run":
        previous_runs.append(
            {
                key: prior.get(key)
                for key in (
                    "run_id",
                    "created_at",
                    "split",
                    "seed",
                    "status",
                    "metrics",
                    "implementation_sha256",
                )
            }
        )
    recipes = reference_cases()
    datasets = [reference_dataset(case, seed, settings.site_id) for case in recipes]
    report: dict[str, Any] = {
        "version": "reference-evaluation-v1",
        "status": "running",
        "run_id": uuid4().hex,
        "created_at": utc_now().isoformat(),
        "seed": seed,
        "split": split,
        "planned_cases": len(recipes),
        "agent_model": agent_model,
        "evaluator_model": evaluator_model,
        "implementation_sha256": evaluation_implementation_hash(),
        "previous_runs": previous_runs,
        "mapping_calibration": [],
        "judge_calibration": [],
        "recipe_sha256": content_hash(json.loads(json.dumps(recipes))),
        "prompt_sha256": prompt_manifest_sha256(),
        **prompt_catalog_provenance(),
        "limitations": [
            "Synthetic pressure footprints, not field-calibrated hydraulic leak models.",
            "Held-out seeds change measurement noise, not the known pattern families.",
            "First attempts only; failures, absent mappings and withheld locations count.",
            "Accuracy uses deterministic label comparison; model-based extraction can still err.",
            "Exact quotes and catalog membership do not prove semantic extraction is correct.",
            "Few cases cannot establish field reliability; denominators and intervals are shown.",
            "Different observed models reduce self-judging but do not establish independence.",
            "Model calls and elapsed time are measured; monetary cost is unavailable.",
        ],
        "cases": [
            {
                "case_id": case["id"],
                "name": case["name"],
                "status": "queued",
                "dataset_sha256": dataset_hash(dataset),
                "frozen_source": freeze_replay_source(dataset),
                "truth": truth_labels(case, dataset),
            }
            for case, dataset in zip(recipes, datasets, strict=True)
        ],
    }
    lock = threading.Lock()

    def save() -> None:
        report["metrics"] = score_report(report)
        write_report(output / "report.json", report)
        write_report(PUBLIC_REPORT, report)

    with lock:
        save()
    telemetry = Telemetry(runtime_dir=settings.runtime_dir)
    evaluator = qualification_model_factory(settings, evaluator_model)("operator_response", "live")
    catalog = [
        {"id": sensor.id, "station_id": sensor.station_id, "segment_id": sensor.segment_id}
        for sensor in datasets[0].pack.sensors
    ]
    for control in mapping_controls():
        interpretation = {
            "answer": {"text": control["text"]},
            "competing_causes": [{"text": control["competing_text"]}]
            if control.get("competing_text")
            else [],
        }
        receipt = run_mapping(
            evaluator,
            interpretation,
            catalog,
            telemetry,
            tenant_id="evaluation-calibration",
            generation_id=report["run_id"],
        )
        mapping = receipt["mapping"] or {}
        observed_leaks = {
            (
                item["segment_id"],
                item["assertion"],
                (item["interval"] or {}).get("start_m"),
                (item["interval"] or {}).get("end_m"),
            )
            for item in mapping.get("leaks", [])
        }
        observed_issues = {
            (item["sensor_id"], item["kind"], item["assertion"])
            for item in mapping.get("sensor_issues", [])
        }
        report["mapping_calibration"].append(
            {
                "name": control["name"],
                **receipt,
                "passed": (
                    receipt["status"] == "completed"
                    and observed_leaks == control["leaks"]
                    and observed_issues == control["issues"]
                    and mapping.get("instrumentation_concern") == control["instrumentation"]
                ),
            }
        )
        with lock:
            save()

    def run_case(index: int) -> None:
        row, dataset = report["cases"][index], datasets[index]
        tenant = "reference-eval-" + uuid4().hex[:12]
        with lock:
            row.update(status="running_agents", tenant_id=tenant)
            save()
        started = time.monotonic()
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
                replay = install_golden_input(monitor, dataset, "live")
                current = replay
                for step in range(13):
                    current = monitor.control(replay.id, "step", None, f"reference-step-{step}")
                    if current.investigation_window_id:
                        break
                if not current.latest_window_id:
                    raise RuntimeError("evaluation_no_complete_window")
                snapshot = store.get_window(current.latest_window_id)
                roots = [task for task in store.list_tasks(replay.id) if not task.parent_id]
                with lock:
                    row.update(
                        generation_id=replay.id,
                        snapshot_id=snapshot.id,
                        input_hash=snapshot.input_hash,
                        root_count=len(roots),
                        detector={
                            "pressure_anomaly_sensors": sorted(
                                finding.sensor_id
                                for finding in snapshot.quality.findings
                                if finding.anomaly_count
                            ),
                            "missing_value_sensors": sorted(
                                finding.sensor_id
                                for finding in snapshot.quality.findings
                                if finding.missing or finding.hard_excluded
                            ),
                        },
                    )
                    save()
                if len(roots) > 1:
                    raise RuntimeError("evaluation_multiple_initial_roots")
                if roots:
                    root = roots[0]
                    for _ in range(WORKER_POLL_LIMIT):
                        if root.state in TERMINALS:
                            break
                        if time.monotonic() - started > ROOT_WATCHDOG_SECONDS:
                            raise RuntimeError("evaluation_root_watchdog")
                        if not service.run_once():
                            time.sleep(0.05)
                        root = store.get_task(root.id)
                    if root.state not in TERMINALS:
                        raise RuntimeError("evaluation_root_not_terminal")
                    audit = audit_operations(store, root, snapshot)
                    if root.result:
                        audit["grounded_source_texts"] = source_texts(
                            root.result,
                            snapshot,
                            store.tool_receipts(root.id),
                            root.knowledge_packet,
                        )
                    write_report(output / f"case-{index}-audit.json", audit)
                    with lock:
                        row.update(
                            root_id=root.id,
                            state=root.state,
                            error_code=root.error_code,
                            accepted_report=bool(audit["report"]["completed"]),
                            answer=audit["report"].get("answer"),
                            interpretation=audit["report"].get("interpretation"),
                            agent_calls=audit["fresh_model_calls"],
                            agent_elapsed_seconds=round(time.monotonic() - started, 3),
                            model_receipts=audit["model_receipts"],
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
                        evidence = grounded_case_evidence(snapshot, audit)
                        truth = row["truth"]
                        expected = {
                            "source_truth": truth["leak_source"],
                            "hypothesis": "suspected_leak"
                            if truth["leak_source"]
                            else "sensor_or_telemetry_issue",
                            "inspection": truth["expected_inspection"],
                            "missing_or_invalid": bool(truth["missing_value_sensors"]),
                            "source_sensor_issue_labels": truth["sensor_issues"],
                        }
                        if index == 0:
                            for control in calibration_packets(evidence, expected):
                                verdict = run_judge(
                                    evaluator,
                                    control["packet"],
                                    telemetry,
                                    identity=control["identity"],
                                    tenant_id=tenant,
                                    generation_id=replay.id,
                                )
                                with lock:
                                    report["judge_calibration"].append(
                                        {
                                            **verdict,
                                            "expected_pass": control["expected_pass"],
                                        }
                                    )
                                    save()
                        verdict = run_judge(
                            evaluator,
                            {
                                "case_evidence": evidence,
                                "hidden_expected_outcomes": expected,
                                "candidate_report": judge_candidate_report(audit["report"]),
                            },
                            telemetry,
                            identity=f"reference-{index}",
                            tenant_id=tenant,
                            generation_id=replay.id,
                        )
                        with lock:
                            row["judge"] = verdict
                            save()
                with lock:
                    row.update(
                        status="completed"
                        if (
                            not roots
                            and not row["truth"]["pressure_trigger"]
                            or row.get("accepted_report")
                            and (row.get("extraction") or {}).get("status") == "completed"
                        )
                        else "failed",
                        elapsed_seconds=round(time.monotonic() - started, 3),
                    )
                    save()
        except Exception as exc:
            with lock:
                row.update(
                    status="failed",
                    error_code=getattr(exc, "code", "evaluation_execution_failed"),
                    error_type=type(exc).__name__,
                    elapsed_seconds=round(time.monotonic() - started, 3),
                )
                save()

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(run_case, range(len(recipes))))
    with lock:
        report["status"] = "completed"
        report["completed_at"] = utc_now().isoformat()
        report["implementation_unchanged"] = (
            report["implementation_sha256"] == evaluation_implementation_hash()
        )
        save()
    return report

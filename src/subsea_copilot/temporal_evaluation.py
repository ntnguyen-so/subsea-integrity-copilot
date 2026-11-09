"""Source-causal lifecycle scores and recorded agent-protocol checks, not field validation."""

from __future__ import annotations

import json
import logging
import math
from copy import deepcopy
from pathlib import Path
from statistics import median
from typing import Any

from .spatial_data import leak_episodes

logger = logging.getLogger(__name__)

SUITE_NAMES = {
    "current": "Leak and sensor-issue detection",
    "recovery": "Leak recovery and new leaks",
    "non_leak": "No-leak scenarios and false alarms",
}

def without_agent_audit_results(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: without_agent_audit_results(item) for key, item in value.items()
            if key not in {
                "agent_process", "agent_process_audit", "agent_audit", "agent_audit_error",
            }
        }
    if isinstance(value, list):
        return [without_agent_audit_results(item) for item in value]
    return value


def publish_evaluation(report: dict[str, Any], path: Path) -> None:
    from .reference_evaluation import write_report

    suite = report.get("suite", "current")
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
        "version": "spatial-evaluation-v1", "status": "not_run",
        "cases": [], "networks": [], "metrics": None,
    }
    additions = existing.get("additional_evaluations", [])
    if suite == "current":
        projection = {**report, "additional_evaluations": additions}
        if "agent_reference_evaluation" in existing:
            projection["agent_reference_evaluation"] = existing["agent_reference_evaluation"]
    else:
        projection = {
            **existing,
            "additional_evaluations": [
                *[item for item in additions if item.get("suite") != suite], report,
            ],
        }
    write_report(path, without_agent_audit_results(projection))


def run_agent_evaluation(output: Path, *, suite: str = "current") -> dict[str, Any]:
    from uuid import uuid4

    from .config import Settings
    from .contracts import utc_now
    from .operations_evaluation import audit_operations
    from .reference_evaluation import (
        evaluation_implementation_hash,
        read_evaluation,
        write_report,
    )
    from .store import ScopeError, Store, StoreError

    if (output / "report.json").exists():
        raise ValueError("Use a fresh output directory; recorded audits are immutable")
    published = read_evaluation()
    source = published if suite == "current" else next(
        (item for item in published.get("additional_evaluations", [])
         if item.get("suite") == suite), None,
    )
    if source is None or source["status"] == "not_run":
        raise ValueError("No recorded source evaluation is available")
    settings = Settings.from_env()
    result: dict[str, Any] = {
        "version": "agent-process-evaluation-v1", "status": "completed",
        "run_id": uuid4().hex, "source_run_id": source["run_id"], "source_suite": suite,
        "created_at": utc_now().isoformat(),
        "validator_implementation_sha256": evaluation_implementation_hash(),
        "cases": deepcopy(source["cases"]),
    }
    for row in result["cases"]:
        if not row.get("root_count"):
            continue
        row.pop("agent_audit", None)
        try:
            with Store(
                settings.database_dsn, row["tenant_id"], settings.site_id,
                settings.tools_dsn, qualification=True,
            ) as store:
                root = store.get_task(row["root_id"])
                snapshot = store.get_window(row["snapshot_id"])
                if snapshot is None or snapshot.input_hash != row["input_hash"]:
                    raise ScopeError("Archived snapshot provenance does not match")
                audit = audit_operations(store, root, snapshot)
                row["agent_audit"] = {
                    "checks": audit["checks"], "validation_errors": audit["validation_errors"],
                    "critic_decisions": audit["critic_decisions"],
                }
                write_report(output / f"{row['case_id'].replace('@', '-')}-audit.json", audit)
        except (StoreError, ValueError, TypeError, KeyError) as exc:
            logger.error("Recorded agent audit %s failed: %s", row["case_id"], type(exc).__name__)
            row["agent_audit_error"] = getattr(exc, "code", type(exc).__name__)
    result["agent_process"] = agent_process_metrics(result)
    result["agent_process"]["basis"] += (
        " Current-validator read-only re-audit of archived receipts; original acceptance "
        "was not replayed and no new inference or diagnostic findings were generated."
    )
    write_report(output / "report.json", result)
    return result


def admitted_timeline(
    report: dict[str, Any], network: dict[str, Any],
) -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
    rows = {row["case_id"]: row for row in report["cases"]}
    latest = None
    timeline = []
    for frame in sorted(network["frames"], key=lambda item: item["source_seconds"]):
        row = rows.get(frame.get("review_case_id"))
        matching = row is not None and all(
            row.get(key) == value for key, value in {
                "network_id": network["id"], "source_seconds": frame["source_seconds"],
                "snapshot_id": frame["snapshot_id"], "input_hash": frame["input_hash"],
            }.items()
        )
        if (
            matching and row is not None and row.get("status") == "completed"
            and row.get("accepted_report")
            and (row.get("extraction") or {}).get("status") == "completed"
            and (row.get("extraction") or {}).get("mapping") is not None
        ):
            latest = row
            current = row
        else:
            current = (
                latest if latest and latest["source_seconds"] < frame["source_seconds"] else None
            )
        timeline.append((frame, current))
    return timeline


def lifecycle_metrics(report: dict[str, Any]) -> dict[str, Any]:
    episodes = []
    controls = []
    for network in report.get("networks", []):
        timeline = admitted_timeline(report, network)
        sources = leak_episodes(network["source_labels"])
        for index, source in enumerate(sources):
            onset, stop = source["start_seconds"], source.get("end_seconds")
            detected = next(
                (row for frame, row in timeline
                 if frame["source_seconds"] > onset and (stop is None
                                                        or frame["source_seconds"] <= stop)
                 and row is not None and row["source_seconds"] > onset
                 and any(item["segment_id"] == source["segment_id"]
                         for item in row["extraction"]["mapping"]["leaks"])),
                None,
            )
            next_onset = sources[index + 1]["start_seconds"] if index + 1 < len(sources) else None
            clean_start = stop + network["pack"]["window_seconds"] if stop is not None else None
            clean = [
                (frame, row) for frame, row in timeline if clean_start is not None
                and frame["source_seconds"] >= clean_start
                and (next_onset is None or frame["source_seconds"] <= next_onset)
            ]
            cleared = next(
                (row for _, row in clean if row is not None and clean_start is not None
                 and row["source_seconds"] >= clean_start
                 and not row["extraction"]["mapping"]["leaks"]),
                None,
            )
            active = [(frame, row) for frame, row in timeline if frame["source_seconds"] > onset
                      and (stop is None or frame["source_seconds"] <= stop)]
            uncovered = sum(
                row is None or not any(item["segment_id"] == source["segment_id"]
                                       for item in row["extraction"]["mapping"]["leaks"])
                for _, row in active
            )
            episodes.append({
                "network_id": network["id"], "episode": index + 1,
                "segment_id": source["segment_id"], "onset_seconds": onset, "stop_seconds": stop,
                "first_fresh_correct_review_seconds": (
                    detected["source_seconds"] if detected else None
                ),
                "detection_delay_source_seconds": detected["source_seconds"] - onset
                if detected else None,
                "active_windows": len(active), "uncovered_active_windows": uncovered,
                "clean_recovery_start_seconds": clean_start,
                "first_clear_review_seconds": cleared["source_seconds"] if cleared else None,
                "clearance_delay_source_seconds": cleared["source_seconds"] - stop
                if cleared and stop is not None else None,
                "clean_recovery_windows": len(clean),
                "false_leak_recovery_windows": sum(
                    row is not None and bool(row["extraction"]["mapping"]["leaks"])
                    for _, row in clean
                ),
                "unassessed_recovery_windows": sum(row is None for _, row in clean),
            })
        if not sources:
            assessed = [(frame, row) for frame, row in timeline if row is not None]
            controls.append({
                "network_id": network["id"], "name": network["name"],
                "windows": len(timeline), "assessed_windows": len(assessed),
                "unassessed_windows": len(timeline) - len(assessed),
                "false_leak_windows": sum(bool(row["extraction"]["mapping"]["leaks"])
                                         for _, row in assessed),
                "inspection_windows": sum(bool(row.get("authorized_inspection"))
                                          for _, row in assessed),
            })
    return {
        "episodes": episodes, "controls": controls,
        "basis": "Fresh source-matched final reports for each episode; retained reports for "
        "temporal coverage. Recovery scoring starts after one full window without the leak. "
        "Absent/failed reviews never prove clearance. Counts are overlapping source windows.",
    }


def agent_process_metrics(report: dict[str, Any]) -> dict[str, Any]:
    attempts = [row for row in report["cases"] if row.get("root_count")]
    planned = [row for row in report["cases"] if row.get("force_review") or row.get("root_count")
               or row.get("truth", {}).get("review_required")]
    tasks = {task["id"]: task for row in attempts for task in row.get("agent_tasks", [])
             if task.get("root_id") == row.get("root_id")}
    roles = []
    for role in ("sensor_quality", "event_diagnosis", "operator_response"):
        assigned = [task for task in tasks.values() if task["role"] == role]
        roles.append({
            "role": role, "assigned": len(assigned),
            "succeeded": sum(task["state"] == "SUCCEEDED" for task in assigned),
            "abstained": sum(task["state"] == "ABSTAINED" for task in assigned),
            "failed": sum(task["state"] == "FAILED" for task in assigned),
            "pending": sum(task["state"] not in {"SUCCEEDED", "ABSTAINED", "FAILED"}
                           for task in assigned),
        })
    checks = {}
    labels = {
        "persisted_results_revalidated": "Evidence-reference validation",
        "specialist_collaboration": "Specialist results consumed",
        "pinned_tool_scope": "Tools pinned to the reviewed snapshot",
        "read_only_role_authority": "Read-only tool authority",
        "critic_and_reflection": "Reviewer and revision protocol",
        "review_attestation": "Final review attestation",
        "bounded_execution": "Execution within declared limits",
    }
    for key, label in labels.items():
        values = [(row.get("agent_audit") or {}).get("checks", {}).get(key) for row in attempts]
        checks[key] = {
            "label": label, "passed": sum(value is True for value in values),
            "failed": sum(value is False for value in values),
            "not_recorded": sum(value is None for value in values), "denominator": len(attempts),
        }
    elapsed = sorted(row["agent_elapsed_seconds"] for row in attempts
                     if isinstance(row.get("agent_elapsed_seconds"), (int, float))
                     and not isinstance(row["agent_elapsed_seconds"], bool)
                     and math.isfinite(row["agent_elapsed_seconds"])
                     and row["agent_elapsed_seconds"] >= 0)
    return {
        "attempted_reviews": len(attempts),
        "planned_agent_reviews": len(planned),
        "not_attempted_reviews": sum(not row.get("root_count") for row in planned),
        "roles": roles,
        "terminal_reviews": sum(row.get("state") in {"SUCCEEDED", "ABSTAINED", "FAILED"}
                                for row in attempts),
        "accepted_reports": sum(bool(row.get("accepted_report")) for row in attempts),
        "mapped_reports": sum(bool(row.get("accepted_report"))
                              and row.get("status") == "completed"
                              and (row.get("extraction") or {}).get("status") == "completed"
                              and (row.get("extraction") or {}).get("mapping") is not None
                              for row in attempts),
        "failed_reviews": sum(row.get("status") == "failed" for row in attempts),
        "timeouts": sum(row.get("error_code") in {
            "deadline_exceeded", "spatial_root_watchdog", "model_timeout",
        } for row in attempts),
        "model_calls": sum(row.get("agent_calls") or 0 for row in attempts),
        "model_calls_not_recorded": sum(row.get("agent_calls") is None for row in attempts),
        "latency_samples": len(elapsed),
        "p50_wall_seconds": median(elapsed) if elapsed else None,
        "p95_wall_seconds": elapsed[math.ceil(len(elapsed) * 0.95) - 1] if elapsed else None,
        "max_wall_seconds": elapsed[-1] if elapsed else None,
        "checks": checks,
        "basis": "All dispatched reviews, including failures and timeouts. Protocol checks "
        "validate recorded references and handoffs, not semantic correctness of every claim. "
        "Missing audits are explicitly unverified; detection accuracy is scored separately.",
    }

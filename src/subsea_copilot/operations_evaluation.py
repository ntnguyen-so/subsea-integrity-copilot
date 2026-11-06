"""Evaluation-only, matched report rubric and persisted operation audit.

Fixture expectations never enter an agent prompt or the deterministic baseline.
Passing this rubric is not independent semantic adjudication of generated prose.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from datetime import datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import numpy as np

from .contracts import AgentResult, AgentTask, WindowSnapshot
from .evaluation import EXPECTED
from .history_evaluation import fixed_history_baseline
from .investigation import ACTION_LABELS
from .runtime.gateway import ToolGateway
from .runtime.registry import REGISTRY
from .store import Store
from .validation import ValidationError, compatible, validate_result

EXPECTED_CONTEXT = {
    "S1": {"unresolved"},
    "S2": {"instrumentation_context"},
    "S3": {"unresolved"},
    "S4": {"operating_change_plausible"},
    "S5": {"unresolved", "instrumentation_context"},
    "S6": {"unresolved"},
}
EXPECTED_RECORDS = {
    "S1": {"LOG-COVERAGE-001"},
    "S2": {"MAINT-CAL-P1-002", "MAINT-SPIKE-P2-001", "MAINT-LINK-P3-001"},
    "S3": {"LOG-COVERAGE-001"},
    "S4": {"OP-VALVE-001"},
    "S5": {"WO-TELEMETRY-001"},
    "S6": {"LOG-COVERAGE-001"},
}
EXPECTED_ACTIONS = {
    "S1": {"inspect_supported_interval", "check_operating_records", "human_review"},
    "S2": {"review_instrumentation"},
    "S3": {"restore_telemetry"},
    "S4": {"check_operating_records", "human_review"},
    "S5": {"restore_telemetry"},
    "S6": {"human_review", "check_operating_records"},
}


def report_rubric(
    scenario: str,
    question_index: int,
    report: dict[str, Any],
) -> dict[str, bool]:
    """Same checks for both methods; exact prose relevance remains unadjudicated."""
    inspection = report.get("inspection")
    inspection_correct = (
        inspection == {"segment_id": "P1", "start_m": 200.0, "end_m": 600.0}
        if scenario == "S1" and (question_index == 2 or inspection is not None)
        else inspection is None
    )
    documents = report.get("documents", [])
    cited_ids = set(report.get("cited_document_ids", []))
    current_ids = {d["id"] for d in documents if d.get("admissible")}
    read_ids = {d["id"] for d in documents}
    checks = {
        "completed_report": report.get("completed") is True,
        "physical_decision": report.get("physical_decision") == EXPECTED[scenario],
        "inspection_or_withholding": inspection_correct,
        "context_assessment": report.get("context_assessment") in EXPECTED_CONTEXT[scenario],
        "next_action": report.get("next_action") in EXPECTED_ACTIONS[scenario],
        "source_authority": bool(cited_ids) and cited_ids <= current_ids,
        "relevant_history_read": bool(read_ids & EXPECTED_RECORDS[scenario]),
        "measured_comparison": bool(report.get("comparisons")),
        "coverage_disclosed": report.get("coverage_disclosed") is True,
        "limitations_disclosed": report.get("limitations_disclosed") is True,
    }
    return checks


def _inspection(snapshot: WindowSnapshot) -> dict[str, Any] | None:
    fit = snapshot.location
    if not fit or fit.status != "located" or fit.best is None:
        return None
    return {
        "segment_id": fit.best.segment_id,
        "start_m": fit.inspection_start_m,
        "end_m": fit.inspection_end_m,
    }


def deterministic_report(
    store: Store, task: AgentTask, snapshot: WindowSnapshot, question_index: int
) -> dict[str, Any]:
    """Frozen quality-aware retrieval plus conservative templates, without an LLM."""
    started = time.perf_counter()
    # This task is not persisted or model-produced. The history validator examines
    # only investigation fields; no agent answer is used to choose the baseline.
    diagnosis = task.model_copy(
        update={
            "role": "event_diagnosis",
            "purpose": REGISTRY["event_diagnosis"].purpose,
            "result": AgentResult(
                outcome="supported", claim_refs=[], limitations=["synthetic_data", "read_only"]
            ),
        }
    )
    history = fixed_history_baseline(store, diagnosis, snapshot, quality_aware=True)
    if history["guard_error"]:
        raise ValidationError(history["guard_error"], "Fixed history baseline was rejected.")
    assessment = history["assessment"]
    action = (
        "restore_telemetry"
        if snapshot.quality.coverage < 0.6
        else "inspect_supported_interval"
        if _inspection(snapshot)
        else "review_instrumentation"
        if assessment == "instrumentation_context"
        else "check_operating_records"
        if assessment == "operating_change_plausible"
        else "human_review"
    )
    receipts = history["receipts"]
    documents = [
        document
        for receipt in receipts
        if receipt["name"] == "history.read"
        for document in receipt["result"]["documents"]
    ]
    report = {
        "completed": True,
        "physical_decision": snapshot.event.hypothesis,
        "inspection": _inspection(snapshot),
        "context_assessment": assessment,
        "next_action": action,
        "cited_document_ids": history["document_ids"],
        "documents": documents,
        "comparisons": [history["comparison"]],
        "coverage_disclosed": True,
        "limitations_disclosed": True,
    }
    headings = {
        1: "Leak versus sensor/telemetry assessment",
        2: "Supported inspection interval or explicit withholding",
        3: "Evidence and unresolved questions",
    }
    report["answer"] = (
        f"{headings[question_index]}. Numerical assessment: {report['physical_decision']}. "
        f"Inspection: {report['inspection'] or 'withheld'}. "
        f"Context: {assessment}. Usable coverage: {snapshot.quality.coverage:.3f}. "
        f"{ACTION_LABELS[action]} "
        f"Reviewed records: {', '.join(history['document_ids'])}. "
        "Measured before/after comparison is attached. "
        "History supplies context, not a confirmed root cause or proof of no leak. "
        "Missing observations remain unknown. Synthetic, uncalibrated pressure profiles; "
        "an interval is not an exact leak position. Read-only; humans retain safety authority."
    )
    return {
        "report": report,
        "elapsed_seconds": time.perf_counter() - started,
        "model_calls": 0,
        "tool_reads": history["tool_reads"],
        "receipts": receipts,
        "policy": history["policy"],
        "execution": "Actual scoped SQL/history reads and a fixed template; no model output.",
    }


def audit_operations(store: Store, root: AgentTask, snapshot: WindowSnapshot) -> dict[str, Any]:
    fresh = [t for t in store.list_tasks(root.generation_id) if t.root_id == root.id]
    dependency_map: dict[str, list[AgentTask]] = {}
    closure: dict[str, AgentTask] = {t.id: t for t in fresh}
    pending = list(fresh)
    while pending:
        task = pending.pop()
        dependencies = ToolGateway(store, task, snapshot, None).dependencies()
        dependency_map[task.id] = dependencies
        for dependency in dependencies:
            if dependency.id not in closure:
                closure[dependency.id] = dependency
                pending.append(dependency)
    receipts = {identifier: store.tool_receipts(identifier) for identifier in closure}
    models = {identifier: store.list_model_calls(identifier) for identifier in closure}
    accepted = root.state in {"SUCCEEDED", "ABSTAINED"} and root.result is not None
    validation_errors = []
    for task in closure.values():
        if task.state not in {"SUCCEEDED", "ABSTAINED"} or task.result is None:
            validation_errors.append({"task_id": task.id, "code": task.error_code or task.state})
            continue
        try:
            validate_result(task.result, task, snapshot, receipts[task.id], dependency_map[task.id])
        except ValidationError as exc:
            validation_errors.append({"task_id": task.id, "code": exc.code})
    linked = dependency_map[root.id]
    diagnoses = [t for t in linked if t.role == "event_diagnosis"]
    reads: list[dict[str, Any]] = [
        {"task_id": task.id, **receipt}
        for task in closure.values()
        for receipt in receipts[task.id]
    ]
    history_reads = [receipt for receipt in reads if str(receipt["name"]).startswith("history.")]
    documents = {
        document["id"]: document
        for receipt in history_reads
        if receipt["name"] == "history.read" and not receipt.get("error")
        for document in (receipt.get("result") or {}).get("documents", [])
    }
    result = root.result
    review = result.investigation if result else None
    comparisons = [
        {"call_id": receipt["call_id"], **receipt["result"]}
        for receipt in history_reads
        if receipt["name"] == "history.compare"
        and not receipt.get("error")
        and review is not None
        and receipt["call_id"] in review.comparison_call_ids
    ]
    selected_kinds = {
        snapshot.claims[ref].kind
        for ref in (result.claim_refs if result else [])
        if ref in snapshot.claims
    }
    report = {
        "completed": accepted,
        "physical_decision": (
            "insufficient_evidence"
            if result and result.outcome == "insufficient_evidence"
            else result.hypothesis
            if result
            else None
        ),
        "inspection": _inspection(snapshot) if "location" in selected_kinds else None,
        "context_assessment": review.assessment if review else None,
        "next_action": review.next_action if review else None,
        "cited_document_ids": review.document_ids if review else [],
        "documents": list(documents.values()),
        "comparisons": comparisons,
        "coverage_disclosed": "coverage" in selected_kinds,
        "limitations_disclosed": bool(
            result
            and {"synthetic_data", "SYNTHETIC_UNCALIBRATED"} & set(result.limitations)
            and root.answer
            and "READ ONLY" in root.answer
        ),
        "limitations": result.limitations if result else [],
        "answer": root.answer,
        "interpretation": result.interpretation.model_dump(mode="json")
        if result and result.interpretation
        else None,
    }
    fresh_models = [
        {"task_id": task.id, **metadata} for task in fresh for metadata in models[task.id]
    ]
    phases = Counter(str(metadata.get("phase")) for metadata in models[root.id])
    record = root.interpretation_review
    decisions = [r.assessment.decision for r in record.rounds] if record else []
    critic_sequence = (
        decisions == ["accept"]
        and phases["critic-0"] >= 1
        or decisions == ["revise", "accept"]
        and all(phases[p] >= 1 for p in ("critic-0", "reflection", "critic-1"))
    )
    links_consumed = all(
        any(
            receipt["name"] == "task.result"
            and not receipt.get("error")
            and isinstance(receipt["arguments"], dict)
            and receipt["arguments"].get("task_id") == dependency.id
            for receipt in receipts[task.id]
        )
        for task in closure.values()
        for dependency in dependency_map[task.id]
    )
    reuse = store.reuse_task_ids(root.id)
    scope = {
        "site_id": snapshot.site_id,
        "snapshot_id": snapshot.id,
        "pack_version": snapshot.pack_version,
        "baseline_version": snapshot.baseline_version,
        "parameter_version": snapshot.parameter_version,
    }
    as_of = store.get_replay(root.generation_id).epoch + timedelta(seconds=snapshot.clock_seconds)
    history_sequence = True
    for task in diagnoses:
        ordered = sorted(
            (r for r in history_reads if r["task_id"] == task.id and not r.get("error")),
            key=lambda r: r["result"]["investigation_step"],
        )
        searched = False
        for receipt in ordered:
            if receipt["name"] == "history.search":
                searched = True
            else:
                history_sequence &= searched
            history_sequence &= receipt["result"]["corpus_version"] == root.history_version
    checks = {
        "persisted_results_revalidated": accepted and not validation_errors,
        "specialist_collaboration": len(diagnoses) == 1
        and len(dependency_map[diagnoses[0].id]) == 1
        and dependency_map[diagnoses[0].id][0].role == "sensor_quality"
        and links_consumed,
        "scope_and_reuse": all(compatible(root, task, snapshot) for task in linked)
        and {t.id for t in linked if t.parent_id != root.id} == set(reuse),
        "model_receipt_accounting": all(len(models[t.id]) == t.model_calls for t in fresh),
        "tool_receipt_accounting": all(len(receipts[t.id]) == t.tool_calls for t in fresh),
        "read_only_role_authority": all(
            receipt["name"] in REGISTRY[closure[str(receipt["task_id"])].role].tools
            for receipt in reads
        ),
        "pinned_tool_scope": all(
            all(receipt["arguments"].get(key) == value for key, value in scope.items())
            for receipt in reads
        ),
        "incident_time_sources": all(
            all(
                datetime.fromisoformat(document[key]) <= as_of
                for key in ("available_at", "authored_at", "effective_from")
            )
            for document in documents.values()
        ),
        "observe_before_followup": bool(history_reads) and history_sequence,
        "bounded_execution": sum(t.model_calls for t in fresh) <= 10
        and sum(t.tool_calls for t in fresh) <= 18
        and len([t for t in fresh if t.parent_id]) <= 2
        and all(
            t.model_calls
            <= (
                6
                if t.role == "operator_response" and t.response_protocol == "engineer-v2"
                else REGISTRY[t.role].model_limit
            )
            and t.tool_calls <= REGISTRY[t.role].tool_limit
            for t in fresh
        ),
        "critic_and_reflection": accepted and bool(critic_sequence),
        "review_attestation": accepted and record is not None and not validation_errors,
    }
    steps = []
    for receipt in reads:
        identity = json.dumps(
            [
                receipt["task_id"],
                snapshot.id,
                receipt["name"],
                receipt["arguments"],
                "required-intake-v1",
            ],
            sort_keys=True,
        )
        steps.append(
            {
                **receipt,
                "origin": "application_required_intake"
                if receipt["call_id"] == str(uuid5(NAMESPACE_URL, identity))
                else "model_requested",
            }
        )
    return {
        "report": report,
        "checks": checks,
        "validation_errors": validation_errors,
        "fresh_model_calls": sum(t.model_calls for t in fresh),
        "fresh_tool_calls": sum(t.tool_calls for t in fresh),
        "reused_task_ids": reuse,
        "reused_prior_model_calls": sum(
            t.model_calls for t in closure.values() if t.root_id != root.id
        ),
        "root_model_phases": dict(phases),
        "critic_decisions": decisions,
        "review": record.model_dump(mode="json") if record else None,
        "tasks": [
            {
                "id": t.id,
                "role": t.role,
                "root_id": t.root_id,
                "parent_id": t.parent_id,
                "snapshot_id": t.snapshot_id,
                "state": t.state,
                "plan": t.plan,
                "model_calls": t.model_calls,
                "tool_calls": t.tool_calls,
                "dependencies": [dep.id for dep in dependency_map[t.id]],
            }
            for t in closure.values()
        ],
        "tool_receipts": steps,
        "model_receipts": fresh_models,
        "model_requested_history_actions": len(history_reads),
        "tool_errors": [
            {"task_id": r["task_id"], "call_id": r["call_id"], "error": r["error"]}
            for r in reads
            if r.get("error")
        ],
        "failure_report_withheld": None
        if accepted
        else root.answer is None and root.result is None,
    }


def summarize(
    rows: list[dict[str, Any]], expected_count: int, *, attempted_count: int | None = None
) -> dict[str, Any]:
    attempted_count = len(rows) if attempted_count is None else attempted_count
    if not len(rows) <= attempted_count <= expected_count:
        raise ValueError("Scored <= attempted <= planned must hold.")

    def metric(method: str, key: str) -> dict[str, Any]:
        values = [row[method][key] for row in rows]
        keys = sorted({name for value in values for name in value})
        return {
            name: {
                "passed": sum(value.get(name) is True for value in values),
                "denominator": expected_count,
            }
            for name in keys
        }

    def latency(method: str) -> dict[str, Any]:
        values = [row[method]["elapsed_seconds"] for row in rows]
        return {
            "attempts": len(values),
            "p50_seconds": float(np.percentile(values, 50)) if values else None,
            "p95_seconds": float(np.percentile(values, 95)) if values else None,
            "max_seconds": max(values) if values else None,
            "correct_reports_within_300s": sum(
                row[method]["rubric_passed"] and row[method]["elapsed_seconds"] <= 300
                for row in rows
            ),
            "denominator": expected_count,
        }

    agent_correct = sum(row["agent"]["rubric_passed"] for row in rows)
    fixed_correct = sum(row["deterministic"]["rubric_passed"] for row in rows)
    return {
        "planned": expected_count,
        "attempted": attempted_count,
        "scored": len(rows),
        "unscored_attempts": attempted_count - len(rows),
        "not_attempted": expected_count - attempted_count,
        "completed_agent_reports": sum(row["agent"]["report"]["completed"] for row in rows),
        "agent_correct_reports": agent_correct,
        "deterministic_correct_reports": fixed_correct,
        "report_checks": {
            method: metric(method, "rubric") for method in ("agent", "deterministic")
        },
        "operation_checks": metric("agent", "checks"),
        "latency": {method: latency(method) for method in ("agent", "deterministic")},
        "fresh_model_calls": sum(row["agent"]["fresh_model_calls"] for row in rows),
        "fresh_live_call_attempts": sum(
            metadata.get("mode") == "live"
            for row in rows
            for metadata in row["agent"].get("model_receipts", [])
        ),
        "fresh_hosted_requests": sum(
            metadata.get("mode") != "scripted" and bool(metadata.get("observed_model"))
            for row in rows
            for metadata in row["agent"].get("model_receipts", [])
        ),
        "revised_reports": sum(
            row["agent"]["critic_decisions"] == ["revise", "accept"] for row in rows
        ),
        "failure_release": {
            "observed_failed_attempts": sum(
                row["agent"].get("failure_report_withheld") is not None for row in rows
            ),
            "reports_withheld": sum(
                row["agent"].get("failure_report_withheld") is True for row in rows
            ),
            "meaning": "No successful attempt is counted as a failure-withholding test.",
        },
        "agent_faster_on_matched_correct_pairs": sum(
            row["agent"]["rubric_passed"]
            and row["deterministic"]["rubric_passed"]
            and row["agent"]["elapsed_seconds"] < row["deterministic"]["elapsed_seconds"]
            for row in rows
        ),
        "matched_correct_pairs": sum(
            row["agent"]["rubric_passed"] and row["deterministic"]["rubric_passed"] for row in rows
        ),
        "passed": len(rows) == expected_count
        and agent_correct == expected_count
        and all(all(row["agent"]["checks"].values()) for row in rows)
        and all(row["agent"]["elapsed_seconds"] <= 300 for row in rows),
        "superiority_demonstrated": False,
        "independent_prose_accuracy": None,
        "measured_human_review_seconds": None,
        "monetary_cost_usd": None,
    }

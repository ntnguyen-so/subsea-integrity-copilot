"""Check contextual assessments against actual retrieval and comparison receipts.

A history investigation must cite fully read admissible records and executed
comparisons from the pinned corpus, not search titles or unread IDs. Legacy
tasks additionally use explicit numerical plausibility gates; current LLM
policy checks provenance without choosing a causal label from fixed thresholds.
Rendered history is read-only context, never physical confirmation or control.
"""

from typing import Any

from subsea_copilot.contracts import AgentResult, AgentTask, HistoryInvestigation, WindowSnapshot
from subsea_copilot.validation import ValidationError

ACTION_LABELS = {
    "check_operating_records": "Ask the operator to verify operating records.",
    "review_instrumentation": "Review the cited instrumentation with the integrity engineer.",
    "inspect_supported_interval": (
        "Review the supported inspection interval with the integrity engineer."
    ),
    "restore_telemetry": "Restore observation coverage before selecting a pipeline search area.",
    "human_review": "Escalate the competing explanations for human review.",
}


def history_reference_ids(receipts: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Expose exact read identities, not inferred relevance or causal decisions."""
    reads = [receipt for receipt in receipts if not receipt.get("error")]
    documents = {
        document["id"]: document for receipt in reads if receipt["name"] == "history.read"
        for document in (receipt.get("result") or {}).get("documents", [])
    }
    return {
        "document_ids": sorted(
            key for key, document in documents.items() if document["admissible"]
        ),
        "rejected_document_ids": sorted(
            key for key, document in documents.items() if not document["admissible"]
        ),
        "comparison_call_ids": sorted(
            receipt["call_id"] for receipt in reads if receipt["name"] == "history.compare"
        ),
    }


def validate_investigation(
    result: AgentResult,
    task: AgentTask,
    snapshot: WindowSnapshot,
    receipts: list[dict[str, Any]],
) -> None:
    """Verify corpus/source authority before any policy-specific contextual plausibility checks."""
    review = result.investigation
    reads = [r for r in receipts if not r.get("error") and r["name"].startswith("history.")]
    if review is None or not any(r["name"] == "history.search" for r in reads):
        raise ValidationError(
            "history_required", "Diagnosis must search incident-time history and report its review."
        )
    if any((r.get("result") or {}).get("corpus_version") != task.history_version for r in reads):
        raise ValidationError("history_version", "History receipts must bind the task's corpus.")
    documents = {
        d["id"]: d
        for r in reads
        if r["name"] == "history.read"
        for d in (r.get("result") or {}).get("documents", [])
    }
    relevant_hits = [
        d
        for r in reads
        if r["name"] == "history.search"
        for d in (r.get("result") or {}).get("documents", [])
        if d.get("admissible")
    ]
    if relevant_hits and not documents:
        raise ValidationError(
            "history_followup", "Current search hits require a document read before concluding."
        )
    comparisons = {r["call_id"]: r["result"] for r in reads if r["name"] == "history.compare"}
    for selected in (review.document_ids, review.rejected_document_ids, review.comparison_call_ids):
        if len(set(selected)) != len(selected):
            raise ValidationError("history_citations", "Duplicate historical references.")
    if any(i not in documents or not documents[i]["admissible"] for i in review.document_ids):
        raise ValidationError(
            "history_citations", "Cite only fully read, current approved records.",
            details={
                "invalid_document_ids": [
                    identifier for identifier in review.document_ids
                    if identifier not in documents or not documents[identifier]["admissible"]
                ],
                "allowed_document_ids": [*history_reference_ids(receipts)["document_ids"]],
            },
        )
    if any(i not in documents or documents[i]["admissible"] for i in review.rejected_document_ids):
        raise ValidationError(
            "history_rejection", "Rejected references must be read and non-authoritative."
        )
    if any(i not in comparisons for i in review.comparison_call_ids):
        raise ValidationError(
            "history_comparison", "Comparison references must resolve to executed reads."
        )
    selected_docs = [documents[i] for i in review.document_ids]
    selected_comparisons = [comparisons[i] for i in review.comparison_call_ids]
    if review.assessment != "unresolved" and (not selected_docs or not selected_comparisons):
        raise ValidationError(
            "history_support", "A contextual explanation needs documents and measured comparison."
        )
    if task.decision_policy == "llm-diagnosis-v1":
        # The current policy keeps provenance gates but lets the LLM assess measurements.
        return
    if review.assessment == "operating_change_plausible":
        operations = [d for d in selected_docs if d["type"] == "operation"]
        supported = False
        from datetime import datetime

        epoch = snapshot.window_end.timestamp() - snapshot.end_seconds
        # Legacy demo rule: >=0.2 bar on >=2 segments with >=60% usable data per side
        # and a contemporaneous operation record; this is not calibrated causal confidence.
        for comparison in selected_comparisons:
            changed = {
                s["segment_id"]
                for s in comparison["sensors"]
                if s["change_bar"] is not None
                and abs(s["change_bar"]) >= 0.2
                and s["before_usable"] >= s["before_expected"] * 0.6
                and s["after_usable"] >= s["after_expected"] * 0.6
            }
            supported |= len(changed) >= 2 and any(
                comparison["start_seconds"]
                <= datetime.fromisoformat(d["effective_from"]).timestamp() - epoch
                < comparison["end_seconds"]
                for d in operations
            )
        if not supported:
            raise ValidationError(
                "history_operating_support",
                "Operating context needs a contemporaneous log and multi-segment pressure changes.",
            )
    if review.assessment == "instrumentation_context":
        concerned_sensors = {
            f.sensor_id
            for f in snapshot.quality.findings
            if f.hard_excluded
            or f.spike_count
            or f.drift_suspected
            or f.peer_disagreement
            or f.missing > f.expected * 0.1
        }
        compared_assets = {
            asset
            for comparison in selected_comparisons
            for sensor in comparison["sensors"]
            if sensor["sensor_id"] in concerned_sensors
            for asset in (sensor["sensor_id"], sensor["segment_id"], sensor["failure_domain"])
        }

        def matches(document: dict[str, Any]) -> bool:
            specific = [
                asset
                for asset in document["asset_ids"]
                if "-ST" in asset or asset.startswith("gateway-")
            ]
            return bool(compared_assets.intersection(specific or document["asset_ids"]))

        if not any(d["type"] == "maintenance" and matches(d) for d in selected_docs):
            raise ValidationError(
                "history_instrumentation_support",
                "Maintenance context must match compared instruments.",
                details={
                    "comparison_call_ids": [*review.comparison_call_ids],
                    "concerned_sensor_ids": [*sorted(concerned_sensors)],
                    "compared_assets": sorted(compared_assets),
                    "maintenance_documents": [
                        {"document_id": d["id"], "asset_ids": d["asset_ids"]}
                        for d in selected_docs
                        if d["type"] == "maintenance"
                    ],
                    "required_match": (
                        "A current cited maintenance record must match a concerned instrument "
                        "in the cited comparisons. Specific sensor or gateway references "
                        "must match those references, not merely their segment."
                    ),
                },
            )
    if review.next_action == "inspect_supported_interval" and not (
        snapshot.event.eligible_location
        and snapshot.location
        and snapshot.location.status == "located"
    ):
        raise ValidationError("history_action", "Inspection requires the computed interval.")
    if review.next_action == "restore_telemetry" and snapshot.quality.coverage >= 0.6:
        raise ValidationError(
            "history_action", "Telemetry restoration requires inadequate coverage."
        )


def render_investigation(review: HistoryInvestigation, receipts: list[dict[str, Any]]) -> str:
    """Render checked record excerpts and measured before/after counts from original receipts."""
    documents = {
        d["id"]: d
        for r in receipts
        if r["name"] == "history.read" and not r.get("error")
        for d in (r.get("result") or {}).get("documents", [])
    }
    comparisons = {
        r["call_id"]: r["result"]
        for r in receipts
        if r["name"] == "history.compare" and not r.get("error")
    }
    labels = {
        "operating_change_plausible": (
            "Operating-change explanation is plausible; a concurrent leak is not ruled out."
        ),
        "instrumentation_context": (
            "Maintenance history supports instrumentation review, not a proven hardware diagnosis."
        ),
        "unresolved": (
            "Historical context does not resolve the cause; "
            "absence of a log is not absence of an event."
        ),
    }
    lines = ["", "HISTORY-GROUNDED INVESTIGATION", labels[review.assessment]]
    for identifier in review.document_ids:
        doc = documents[identifier]
        lines.append(
            f"[{identifier} / revision {doc['revision']}] {doc['title']}: {doc['body'][:260]}"
        )
    for identifier in review.rejected_document_ids:
        document = documents[identifier]
        lines.append(
            f"Not current authority: [{identifier}] status={document['status']}, "
            f"effective_to={document.get('effective_to')}."
        )
    for identifier in review.comparison_call_ids:
        comparison = comparisons[identifier]
        lines.append(
            f"Measured comparison [{identifier}]: {comparison['start_seconds']}–"
            f"{comparison['end_seconds']}s; split {comparison['split_seconds']}s."
        )
        for sensor in comparison["sensors"]:
            delta = sensor["change_bar"]
            lines.append(
                f"{sensor['sensor_id']}: median change "
                f"{delta if delta is not None else 'unknown'} bar; "
                f"usable before {sensor['before_usable']}/{sensor['before_expected']}, "
                f"after {sensor['after_usable']}/{sensor['after_expected']}."
            )
    lines.extend(
        [
            ACTION_LABELS[review.next_action],
            "Verify the assessment with the integrity engineer before physical intervention.",
        ]
    )
    return "\n".join(lines)

"""Compare retained agent investigations with a declared fixed retrieval policy."""

import argparse
import json
from pathlib import Path

from subsea_copilot.config import Settings
from subsea_copilot.history_evaluation import (
    EXPECTED_CONTEXTS,
    fixed_history_baseline,
    history_answer_supported,
)
from subsea_copilot.store import Store
from subsea_copilot.validation import validate_result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cohort", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    report = json.loads(args.cohort.read_text(encoding="utf-8"))
    agents = report["agents"]
    settings = Settings.from_env()
    cases = []
    checked_answers = []
    with Store(
        settings.database_dsn,
        tenant_id=agents["qualification_tenant_id"],
        tools_dsn=settings.tools_dsn,
    ) as store:

        def dependencies(task):
            return [
                candidate
                for candidate in store.list_tasks(task.generation_id)
                if candidate.parent_id == task.id
            ] + [store.get_task(i) for i in store.reuse_task_ids(task.id)]

        for row in agents["results"]:
            root = store.get_task(row["root_id"])
            snapshot = store.get_window(root.snapshot_id)
            sources = dependencies(root)
            for source in sources:
                validate_result(
                    source.result,
                    source,
                    snapshot,
                    store.tool_receipts(source.id),
                    dependencies(source)
                    if source.role == "operator_response"
                    else [
                        other
                        for other in sources
                        if other.role == "sensor_quality" and source.role == "event_diagnosis"
                    ],
                )
            result = validate_result(
                root.result, root, snapshot, store.tool_receipts(root.id), sources
            )
            kinds = {snapshot.claims[ref].kind for ref in result.claim_refs}
            has_location = bool(
                snapshot.event.eligible_location
                and snapshot.location
                and snapshot.location.status == "located"
            )
            answers_question = (
                ("hypothesis" in kinds or root.state == "ABSTAINED")
                if row["question_index"] == 1
                else (("location" in kinds) == has_location)
                if row["question_index"] == 2
                else bool(kinds & {"coverage", "sensor_health"})
            )
            checked_answers.append(
                {
                    "root_id": root.id,
                    "scenario": row["scenario"],
                    "question_index": row["question_index"],
                    "accepted": root.state in {"SUCCEEDED", "ABSTAINED"}
                    and answers_question
                    and history_answer_supported(row["scenario"], result, root.state),
                    "assessment": result.investigation.assessment,
                    "next_action": result.investigation.next_action,
                    "original_cohort_gate": row["accepted_correct"],
                }
            )
        for scenario, targets in EXPECTED_CONTEXTS.items():
            row = next(item for item in agents["results"] if item["scenario"] == scenario)
            root = store.get_task(row["root_id"])
            linked = [
                task
                for task in store.list_tasks(root.generation_id)
                if task.parent_id == root.id and task.role == "event_diagnosis"
            ]
            if not linked:
                linked = [
                    store.get_task(identifier)
                    for identifier in store.reuse_task_ids(root.id)
                    if store.get_task(identifier).role == "event_diagnosis"
                ]
            if len(linked) != 1 or linked[0].result is None:
                raise ValueError(f"{scenario}: no accepted diagnosis to compare")
            diagnosis = linked[0]
            snapshot = store.get_window(root.snapshot_id)
            baseline = fixed_history_baseline(store, diagnosis, snapshot)
            quality_baseline = fixed_history_baseline(
                store, diagnosis, snapshot, quality_aware=True
            )
            actual = diagnosis.result.investigation
            history_reads = [
                receipt
                for receipt in store.tool_receipts(diagnosis.id)
                if str(receipt["name"]).startswith("history.")
            ]
            cases.append(
                {
                    "scenario": scenario,
                    "acceptable_contexts": sorted(targets),
                    "numerical_only": {"context": "not_reviewed", "model_calls": 0},
                    "fixed_policy": baseline,
                    "quality_aware_fixed_policy": quality_baseline,
                    "quality_aware_fixed_matches_context": (
                        quality_baseline["assessment"] in targets
                    ),
                    "adaptive": {
                        "assessment": actual.assessment if actual else None,
                        "matches_context": actual is not None and actual.assessment in targets,
                        "history_tool_choices": [
                            {"name": r["name"], "arguments": r["arguments"], "error": r["error"]}
                            for r in sorted(
                                history_reads,
                                key=lambda r: (r.get("result") or {}).get("investigation_step", 0),
                            )
                        ],
                        "diagnosis_model_calls": diagnosis.model_calls,
                        "diagnosis_tool_calls": diagnosis.tool_calls,
                    },
                    "fixed_matches_context": baseline["assessment"] in targets,
                }
            )
    summary = {
        "source_cohort": str(args.cohort),
        "mode": agents["mode"],
        "history_version": diagnosis.history_version,
        "cases": cases,
        "audited_answers": checked_answers,
        "audited_answer_count": len(checked_answers),
        "audited_accepted_count": sum(row["accepted"] for row in checked_answers),
        "audit_passed": bool(checked_answers)
        and all(row["accepted"] for row in checked_answers)
        and agents["stored_trace_tree_verified"],
        "audit_rule": (
            "Revalidate persisted root/specialist results against actual receipts. "
            "S5 may cite supported instrumentation context, but must retain physical "
            "abstention, no hypothesis and restore_telemetry. Raw cohort is unchanged."
        ),
        "adaptive_matches": sum(row["adaptive"]["matches_context"] for row in cases),
        "fixed_matches": sum(row["fixed_matches_context"] for row in cases),
        "quality_aware_fixed_matches": sum(
            row["quality_aware_fixed_matches_context"] for row in cases
        ),
        "denominator": len(cases),
        "buyer_decision": (
            "Consider a read-only shadow pilot; do not approve production "
            "or claim savings from these synthetic cases."
        ),
        "limitations": [
            "No new model calls in this comparison.",
            "Fixed retrieval is a credible low-cost alternative, not a graph-ML performance trial.",
            "Context labels are controlled fixture expectations, not field root-cause labels.",
            "A matching fixed workflow weakens the case for extra LLM calls on that case.",
            "Human investigation effort, customer ROI and novel-incident "
            "generalization remain unmeasured.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                key: summary[key]
                for key in (
                    "audit_passed",
                    "audited_accepted_count",
                    "audited_answer_count",
                    "adaptive_matches",
                    "fixed_matches",
                    "quality_aware_fixed_matches",
                    "denominator",
                )
            }
        )
    )


if __name__ == "__main__":
    main()

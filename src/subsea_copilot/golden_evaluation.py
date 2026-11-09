"""Golden qualification from authored measurements to accepted operator evidence.

The manifest first verifies four synthetic recipes against normalized measurements.
Content-addressed inputs then follow production monitoring, auto-pause and agent
dispatch in an isolated tenant: three pressure-triggered roots and one missing-only
no-agent control. Deterministic contract checks, model-authored interpretation, external
semantic opinion and stored telemetry verification remain separate evidence layers.

A full live run plans five judge calls: two authored calibration controls plus three
actual reports. No outcome is inferred from requested model identity or a numerical
contract tag alone. Recorded rejudging and one-case same-input retries are explicit
operations; selection retains original failures/calls and is not first-attempt
reliability. Receipts preserve manifests, hashes, task/casefile pointers and trace IO.
"""

from __future__ import annotations

import json
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .budgets import ROOT_WATCHDOG_SECONDS, WORKER_POLL_LIMIT
from .casefile import build_casefile
from .config import Settings
from .contracts import Mode, ReplaySession, WindowSnapshot, utc_now
from .golden_data import generate_golden, load_cases, write_manifest
from .golden_evidence import verify_stored_content
from .golden_judge import calibration_packets, run_judge
from .grounding import source_texts
from .ingest import CanonicalBuffer, normalize_records
from .monitoring import Monitor, SourceState
from .operations_evaluation import audit_operations
from .profiles import compact_comparison, expanded_evidence
from .qualification import MODEL_METADATA_KEYS, TERMINALS, qualification_model_factory
from .replay_sources import freeze_replay_source, load_frozen_replay_source
from .runtime.checkpointer import postgres_checkpointer
from .runtime.gateway import ToolGateway
from .runtime.workflow import AgentService
from .store import Store
from .synthetic import SOURCE_VERSION, ReplayDataset
from .telemetry import Telemetry


def install_golden_input(
    monitor: Monitor, dataset: ReplayDataset, mode: Mode, *, duration_seconds: int = 120,
) -> ReplaySession:
    """Evaluation-only source adapter; unchanged production clocks/gates/auto dispatch.

    Content-addressed scenario identities contain no truth labels. SOURCE_VERSION is the
    replay transport contract, not this dataset's identity (recorded in the manifest).
    No golden recipe/truth object is passed to the monitor or persisted in its store.
    """
    replay = monitor.store.create_replay(ReplaySession(
        id="golden-" + uuid4().hex, tenant_id=monitor.store.tenant_id,
        site_id=dataset.pack.id, scenario=freeze_replay_source(dataset),
        source_version=SOURCE_VERSION,
        duration_seconds=duration_seconds, epoch=dataset.epoch, mode=mode,
        workflow="agent_assisted", pause_on_anomaly=True,
    ))
    monitor._sources[replay.id] = SourceState(
        dataset=dataset, baseline=normalize_records(dataset.baseline, dataset.pack),
        received_seconds=[
            (datetime.fromisoformat(row.received_at) - dataset.epoch).total_seconds()
            for row in dataset.records
        ],
        buffer=CanonicalBuffer(dataset.pack), version=replay.version,
    )
    return replay


def grounded_case_evidence(snapshot: WindowSnapshot, audit: dict[str, Any]) -> dict[str, Any]:
    """Build a compact measured/reference packet, not a prewritten source narrative.

    Columnar tables and exact-value references remove repeated numbers without rounding
    away evidence. Grounded sources must equal their persisted pressure summaries.
    Historical comparisons describe post-start periods; they do not replace the normal
    preroll used by diagnostics and may show no change during a sustained deficit.
    """
    quality = snapshot.quality.model_dump(mode="json")
    findings = quality.pop("findings")
    finding_columns = list(findings[0]) if findings else []
    quality.update(
        finding_columns=finding_columns,
        finding_rows=[[finding[column] for column in finding_columns] for finding in findings],
        finding_encoding="columnar-quality-findings-v1",
    )
    summaries = [
        {"evidence_id": item.id, "sensor_id": item.sensor_id, **item.value}
        for item in snapshot.evidence.values()
        if item.kind == "channel_summary" and isinstance(item.value, dict)
    ]
    columns = list(summaries[0]) if summaries else []
    pressure_indices = {item["evidence_id"]: index for index, item in enumerate(summaries)}
    pressure_value_fields = [
        field for field in columns if field not in {"evidence_id", "sensor_id"}
    ]

    def pressure_source(reference: str, original: dict[str, Any]) -> dict[str, Any]:
        index = pressure_indices[reference]
        if original["value"] != {
            key: summaries[index][key] for key in original["value"]
        }:
            raise ValueError("Original pressure source differs from its measured table.")
        return {
            **{key: value for key, value in original.items() if key != "value"},
            "value_reference": f"case_evidence.pressure_summaries.rows.{index}",
            "value_columns_reference": "case_evidence.pressure_summaries.columns",
            **(
                {"value_fields_reference": "case_evidence.pressure_value_fields"}
                if set(original["value"]) == set(pressure_value_fields)
                else {"value_fields": list(original["value"])}
            ),
        }

    source_ledger = {}
    for reference, serialized in audit.get("grounded_source_texts", {}).items():
        claim = snapshot.claims.get(reference)
        if claim and claim.kind == "sensor_health":
            index = next(
                i for i, finding in enumerate(snapshot.quality.findings)
                if finding.evidence_ids == claim.evidence_ids
            )
            source_ledger[reference] = {
                "id": reference, "kind": claim.kind, "evidence_ids": claim.evidence_ids,
                "value_reference": f"case_evidence.quality.finding_rows.{index}",
                "value_columns_reference": "case_evidence.quality.finding_columns",
            }
        elif claim and claim.kind in {"coverage", "hypothesis", "location"}:
            source_ledger[reference] = {
                "id": reference, "kind": claim.kind, "evidence_ids": claim.evidence_ids,
                "value_reference": "case_evidence." + {
                    "coverage": "quality", "hypothesis": "event", "location": "location",
                }[claim.kind],
            }
        elif reference == "audited_pressure_summaries":
            originals = expanded_evidence(json.loads(serialized))["evidence"]
            linked = {
                key: pressure_source(key, value) for key, value in originals.items()
            }
            items = list(linked.values())
            shared = {
                key: value for key, value in items[0].items()
                if all(key in item and item[key] == value for item in items)
            } if items else {}
            source_ledger[reference] = {
                "encoding": "shared-referenced-pressure-evidence-v1",
                "evidence_shared_fields": shared,
                "evidence": {
                    key: {field: value for field, value in item.items() if field not in shared}
                    for key, item in linked.items()
                },
            }
        elif reference in pressure_indices:
            source_ledger[reference] = pressure_source(reference, json.loads(serialized))
        else:
            document_index = next((
                i for i, document in enumerate(audit["report"].get("documents", []))
                if document["id"] == reference
            ), None)
            comparison_index = next((
                i for i, comparison in enumerate(audit["report"].get("comparisons", []))
                if comparison["call_id"] == reference
            ), None)
            if document_index is not None or comparison_index is not None:
                source_ledger[reference] = {
                    "id": reference,
                    "value_reference": (
                        f"case_evidence.documents_actually_read.{document_index}"
                        if document_index is not None else
                        f"case_evidence.measured_comparisons.{comparison_index}"
                    ),
                }
            else:
                source_ledger[reference] = json.loads(serialized)
    evidence = {
        "snapshot_id": snapshot.id, "input_hash": snapshot.input_hash,
        "window": {
            "end_seconds": snapshot.end_seconds, "clock_seconds": snapshot.clock_seconds,
            "window_seconds": 60, "signal_scope": (
                "Current observations are compared to an independent normal preroll by the "
                "detector. Historical comparisons use post-start measurements only, so a "
                "persistent deficit can show no before/after change within this window."
            ),
        },
        "event": snapshot.event.model_dump(mode="json"),
        "quality": quality,
        "location": snapshot.location.model_dump(mode="json") if snapshot.location else None,
        "pressure_summaries": {
            "encoding": "columnar-pressure-summaries-v1", "columns": columns,
            "rows": [[row[column] for column in columns] for row in summaries],
        },
        "pressure_value_fields": pressure_value_fields,
        "claim_ledger": {
            key: value.model_dump(mode="json") for key, value in snapshot.claims.items()
            if not source_ledger and value.kind != "sensor_health"
        },
        "grounded_source_ledger": source_ledger,
        "documents_actually_read": audit["report"].get("documents", []),
        "measured_comparisons": [
            compact_comparison(comparison) if "sensors" in comparison else comparison
            for comparison in audit["report"].get("comparisons", [])
        ],
        "runtime_validation_checks": audit.get("checks", {}),
    }
    evidence["numeric_precision"] = (
        "Full persisted precision; shared measured values are referenced."
    )
    return evidence


def judge_candidate_report(report: dict[str, Any]) -> dict[str, Any]:
    """Make actual published prose the grading target, not its constrained numerical tag.

    Interpretation reference metadata is retained without duplicating paragraphs already
    in the public answer. Documents and comparisons belong in the evidence packet.
    """
    candidate = {key: value for key, value in report.items() if key not in {
        "documents", "comparisons", "interpretation", "physical_decision",
    }}
    candidate["numerical_contract_tag"] = report.get("physical_decision")
    candidate["classification_target"] = (
        "Grade the actual public answer and model-authored causal/regional interpretation, "
        "not this application-constrained numerical tag."
    )
    if report.get("interpretation"):
        interpretation = report["interpretation"]
        candidate["paragraph_references"] = {
            "answer": interpretation["answer"]["references"],
            "competing_causes": [
                {key: value for key, value in cause.items() if key != "text"}
                for cause in interpretation["competing_causes"]
            ],
            "regional_assessments": [
                {key: value for key, value in region.items() if key != "text"}
                for region in interpretation.get("regional_assessments", [])
            ],
            "note": "Public answer above already contains these paragraphs verbatim.",
        }
    return candidate


def deterministic_golden_checks(
    expected: dict[str, Any], snapshot: WindowSnapshot,
    audit: dict[str, Any] | None, *, paused: bool, root_count: int, state: str | None = None,
) -> dict[str, bool]:
    """Check measured trigger, production lifecycle, contract bounds and safe withholding.

    Missing-only expects neither auto-pause nor a root. Triggered cases require an
    accepted root with revalidated receipts. Explained abstention can satisfy the
    contract but cannot count as model leak classification; proposed inspection must
    equal the authored bounded interval, never the hidden exact source coordinate.
    """
    pressure = any(f.anomaly_count for f in snapshot.quality.findings)
    checks = {
        "pressure_trigger_matches_truth": pressure == expected["pressure_trigger"],
        "detector_class_matches_recipe_measurements": (
            snapshot.event.hypothesis == expected["hypothesis"]
        ),
        "missing_is_unknown": all(
            f.usable <= f.received <= f.expected and f.missing == f.expected - f.usable
            for f in snapshot.quality.findings
        ),
    }
    if not expected["pressure_trigger"]:
        return {
            **checks, "no_pause_for_missing_only": not paused,
            "no_agent_for_missing_only": root_count == 0,
        }
    report = (audit or {}).get("report", {})
    abstained = (
        state == "ABSTAINED" and report.get("physical_decision") == "insufficient_evidence"
        and report.get("inspection") is None and bool(report.get("limitations"))
    )
    inspection = report.get("inspection")
    interpretation = report.get("interpretation") or {}
    leak_interpreted_as_possible = any(
        cause.get("cause") == "leak" and cause.get("stance") == "possible"
        for cause in interpretation.get("competing_causes", [])
    ) or any(
        region.get("hypothesis") == "leak_pattern"
        for region in interpretation.get("regional_assessments", [])
    )
    return {
        **checks, "production_auto_pause": paused,
        "one_fresh_automatic_root": root_count == 1,
        "accepted_report_not_provider_failure": (
            state in {"SUCCEEDED", "ABSTAINED"} and report.get("completed") is True
        ),
        "class_or_explained_abstention": (
            report.get("physical_decision") == expected["hypothesis"] or abstained
        ),
        "model_leak_interpretation_not_abstention": (
            expected["hypothesis"] != "suspected_leak"
            or state == "SUCCEEDED" and leak_interpreted_as_possible
        ),
        # Withholding is conservative, but its rationale is assessed independently by the judge.
        "bounded_location_or_withholding": (
            inspection is None or inspection == expected["inspection"]
        ),
        "persisted_contract_revalidation": (audit or {}).get("checks", {}).get(
            "persisted_results_revalidated"
        ) is True,
        "model_and_tool_accounting": all(
            (audit or {}).get("checks", {}).get(key) is True
            for key in ("model_receipt_accounting", "tool_receipt_accounting")
        ),
    }


def operator_accuracy_receipt(
    expected: dict[str, Any], row: dict[str, Any], casefile: dict[str, Any] | None,
) -> dict[str, Any]:
    """Separate numerical eligibility, grounded prose classification and displayed inspection.

    Classification needs a succeeded root, model-authored possible cause/region and
    external class score 2. Inspection credit additionally requires the accepted
    casefile to match the root/snapshot and both report and golden interval.
    """
    report = (row.get("agent") or {}).get("report", {})
    interpretation = report.get("interpretation") or {}
    causes = interpretation.get("competing_causes", [])
    regions = interpretation.get("regional_assessments", [])
    judged_class = (
        ((row.get("external_judge") or {}).get("verdict") or {}).get("dimensions", {})
        .get("class_and_uncertainty", {}).get("score")
    )
    possible_leak = any(
        cause.get("cause") == "leak" and cause.get("stance") == "possible" for cause in causes
    ) or any(region.get("hypothesis") == "leak_pattern" for region in regions)
    instrumentation = any(
        cause.get("cause") == "instrumentation_or_telemetry" and cause.get("stance") == "possible"
        for cause in causes
    ) or any(region.get("hypothesis") == "instrumentation_or_telemetry" for region in regions)
    model_class_passed = (
        judged_class == 2 and row.get("state") == "SUCCEEDED"
        and bool(report.get("answer"))
        and (
            possible_leak if expected["hypothesis"] == "suspected_leak" else instrumentation
        )
    )
    displayed_inspection = (casefile or {}).get("inspection")
    matching_casefile = bool(
        casefile and casefile.get("task_id") in row["root_ids"]
        and casefile.get("snapshot_id") == row["snapshot_id"]
    )
    return {
        "numerical_contract_tag": report.get("physical_decision"),
        "numerical_tag_is_not_model_classification": True,
        "grounding_acceptance": (
            report.get("completed") is True
            and (row.get("agent") or {}).get("checks", {}).get(
                "persisted_results_revalidated"
            ) is True
        ),
        "model_authored_causal_interpretation": causes,
        "model_authored_regional_interpretation": regions,
        "published_operator_answer": report.get("answer"),
        "abstained": row.get("state") == "ABSTAINED",
        "external_class_and_uncertainty_score": judged_class,
        "synthetic_truth_operator_classification_passed": model_class_passed,
        "matching_accepted_casefile": matching_casefile,
        "actual_displayed_inspection": displayed_inspection,
        "displayed_inspection_matches_report": (
            matching_casefile and displayed_inspection == report.get("inspection")
        ),
        "displayed_inspection_matches_golden_interval": (
            matching_casefile and displayed_inspection == expected["inspection"]
        ),
        "scope": (
            "Classification grades model-authored causes/regions and actual published prose, "
            "not eligible detector labels. Abstention is not a leak-classification pass. "
            "Inspection is the accepted matching casefile consumed by the dashboard overlay."
        ),
    }


def audit_recorded_operator_outputs(output: Path) -> dict[str, Any]:
    """Read recorded roots/casefiles; no model construction, submission or record copying."""
    report: dict[str, Any] = json.loads((output / "qualification.json").read_text())
    settings = Settings.from_env()
    expected = {case["id"]: case["expected"] for case in load_cases()["cases"]}
    original_passed = report["passed"]
    report["operator_accuracy_audit_new_model_calls"] = 0
    report["site_id"] = settings.site_id
    report["run_id"] = output.name
    report["execution_environment"] = {
        "database": "subsea", "database_host": "127.0.0.1",
        "primary_operator_tenant_unchanged": True,
        "synthetic_trace_content": report.get("observability", {}).get("content_capture"),
    }
    with Store(
        settings.database_dsn, report["qualification_tenant_id"], settings.site_id,
        settings.tools_dsn, qualification=True,
    ) as store:
        for row in report["cases"]:
            if not row["root_ids"]:
                row["operator_accuracy"] = {
                    "not_applicable_no_pressure_trigger": True,
                    "zero_agents": not store.list_tasks(row["generation_id"]),
                }
                continue
            root = store.get_task(row["root_ids"][0])
            snapshot = store.get_window(row["snapshot_id"])
            file = None
            if root.state in {"SUCCEEDED", "ABSTAINED"} and root.result:
                dependencies = ToolGateway(store, root, snapshot, None).dependencies()
                history = [
                    {"task_id": dependency.id, **receipt}
                    for dependency in dependencies
                    for receipt in store.tool_receipts(dependency.id)
                    if str(receipt["name"]).startswith("history.")
                ]
                file = build_casefile(root, snapshot, dependencies, history).model_dump(mode="json")
                (output / f"casefile-{row['case_id']}.json").write_text(
                    json.dumps(file, indent=2, allow_nan=False), encoding="utf-8",
                )
            row["operator_accuracy"] = operator_accuracy_receipt(
                expected[row["case_id"]], row, file,
            )
    report["operator_truth_accuracy_passed"] = len(report["cases"]) == 4 and all(
        (
            row["operator_accuracy"].get("zero_agents") is True
            if not row["root_ids"] else
            row["operator_accuracy"]["synthetic_truth_operator_classification_passed"]
            and row["operator_accuracy"]["displayed_inspection_matches_report"]
            and row["operator_accuracy"]["displayed_inspection_matches_golden_interval"]
        )
        for row in report["cases"]
    )
    report["prior_qualification_passed_before_operator_audit"] = original_passed
    report["passed"] = original_passed and report["operator_truth_accuracy_passed"]
    write_recorded_receipts(output, report)
    _save_report(output, report)
    return report


def write_recorded_receipts(output: Path, report: dict[str, Any]) -> None:
    """Public recorded-run pointers and measured receipts; no provider or database calls."""
    if report.get("selected_retry_case"):
        report["all_attempts_passed"] = report["all_agent_attempts_passed"] and all(
            judge["status"] == "completed" for judge in report.get("prior_judge_attempts", [])
        )
        report["limitations"] = [
            f"One seed per case; one bounded same-input {report['selected_retry_case']} retry, "
            "with original failure retained. No reliability, expert certification or "
            "time-saving claim."
            if limitation.startswith("One seed/run per case") else limitation
            for limitation in report["limitations"]
        ]
    ui_cases = [
        {
            "case_id": row["case_id"], "replay_id": row["generation_id"],
            "root_task_id": (row["root_ids"] or [None])[0],
        }
        for row in report["cases"]
    ]
    ui_path = output / "qa-ui-cases.json"
    ui_path.write_text(json.dumps(ui_cases, indent=2), encoding="utf-8")
    cases = []
    for row in report["cases"]:
        audit = row.get("agent") or {}
        judge = row.get("external_judge") or {}
        root_id = (row["root_ids"] or [None])[0]
        cases.append({
            **next(case for case in ui_cases if case["case_id"] == row["case_id"]),
            "snapshot_id": row["snapshot_id"], "input_hash": row["input_hash"],
            "dataset_sha256": row["dataset_sha256"], "state": row["state"],
            "agent_calls": audit.get("fresh_model_calls", 0),
            "agent_elapsed_seconds": audit.get("elapsed_seconds"),
            "observed_agent_models": sorted({
                call["observed_model"] for call in audit.get("model_receipts", [])
                if call.get("observed_model")
            }),
            "runtime_root_trace": next((
                entry["trace"] for entry in report["trace_evidence"]
                if root_id is not None and entry.get("task_id") == root_id
            ), None),
            "judge_calls": judge.get("model_calls", 0),
            "judge_elapsed_seconds": judge.get("elapsed_seconds"),
            "judge_trace": judge.get("trace"),
            "judge_observed_model": (judge.get("model_receipt") or {}).get("observed_model"),
            "judge_input_sha256": judge.get("input_sha256"),
            "judge_output_sha256": judge.get("output_sha256"),
            "operator_accuracy": row.get("operator_accuracy"),
        })
    judges = [
        *report.get("prior_judge_attempts", []), *report["judge_calibration"],
        *(row["external_judge"] for row in report["cases"] if row.get("external_judge")),
    ]
    receipt = {
        "passed_selected_coverage": report["passed"], "run_id": report["run_id"],
        "tenant_id": report["qualification_tenant_id"], "site_id": report["site_id"],
        "model_calls_all_attempts": report["model_call_count"],
        "substantive_agent_attempt_count": report.get("substantive_agent_attempt_count"),
        "failed_agent_attempt_count": report.get("failed_agent_attempt_count"),
        "all_agent_attempts_passed": report.get("all_agent_attempts_passed"),
        "all_attempts_passed": report.get("all_attempts_passed"),
        "cases": cases, "judge_attempts": judges,
        "stored_observation_trees_and_io_verified": all(
            entry["stored_tree_verified"] and entry["stored_content"]["passed"]
            for entry in report["trace_evidence"]
        ),
        "stored_observation_tree_count": len(report["trace_evidence"]),
        "stored_evidence_scope": (
            "Runtime attempts and current validated calibration/case judges. Previous rejected "
            "judge attempts are retained separately, not promoted to passing IO verification."
        ),
        "api_dependencies": [
            "External tools\\load-environment.ps1 credentials loader; never persisted in receipts.",
            "Existing scoped PostgreSQL subsea database and LangGraph checkpoints.",
            "Existing hosted Copilot CLI proxy via qualification_model_factory.",
            "Configured local Langfuse OTLP exporter and /api/public/v2/observations reads.",
            "SUBSEA_TRACE_CONTENT=1 and SUBSEA_SYNTHETIC_ONLY=1; sync export enabled for this run.",
        ],
        "qa_command": (
            ".\\.venv\\Scripts\\subsea.exe serve-recorded --tenant "
            f"{report['qualification_tenant_id']} --port 8087"
        ),
        "qa_browser_environment_command": (
            "$env:SUBSEA_GOLDEN_UI_CASES_JSON = Get-Content -Raw "
            f"'{ui_path}'"
        ),
        "qa_browser_verification": "Parent-run 8087 browser verification remains pending.",
        "source_display": (
            "Stored frozen-pressure-<SHA256> is the authoritative measurement identity; "
            "the ordinary replay seed is ignored, never used to regenerate a frozen source. "
            "Prefer a neutral Recorded pressure sample / short replay ID display, keeping "
            "stored scenario and hashes unchanged. No truth labels belong in runtime/UI metadata."
        ),
        "limitations": report["limitations"],
    }
    receipt_path = output / "recorded-receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, allow_nan=False), encoding="utf-8")
    report["qa_ui_cases_artifact"] = str(ui_path)
    report["recorded_receipt_artifact"] = str(receipt_path)


def judge_recorded_reports(
    output: Path, *, judge_model: str = "gpt-6.1-sol",
) -> dict[str, Any]:
    """Fresh hosted judging of unchanged recorded reports; preserve failed prior calls.

    Agent execution is not rerun. Original qualification is snapshotted, calibration and
    verdicts are renewed, and stored trees/IO are reverified before operator-output audit.
    """
    report: dict[str, Any] = json.loads((output / "qualification.json").read_text())
    if len(report["cases"]) != 4 or not report.get("model_call_accounting_complete"):
        raise ValueError("Recorded cohort must finish before external judge requalification")
    initial = output / "qualification.initial.json"
    if not initial.exists():
        initial.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    prior = [
        *report["judge_calibration"],
        *(row["external_judge"] for row in report["cases"] if row.get("external_judge")),
    ]
    report.setdefault("prior_judge_attempts", []).extend(prior)
    report["requalification_scope"] = (
        "Hosted judge transport metadata omitted mode; initial attempts remain failed. "
        "New calibration and semantic verdicts use the exact original published agent reports. "
        "No agent reruns, task copying, numerical-tag classification credit or relaxed criteria."
    )
    report["judge_calibration"] = []
    report["trace_evidence"] = [
        entry for entry in report["trace_evidence"] if entry["kind"] == "runtime_agent"
    ]
    for row in report["cases"]:
        row["external_judge"] = None
    settings = Settings.from_env()
    manifest = json.loads((output / "manifest.json").read_text())
    fixtures = {case["case_id"]: case for case in manifest["cases"]}
    expected = {case["id"]: case["expected"] for case in load_cases()["cases"]}
    telemetry = Telemetry(runtime_dir=settings.runtime_dir)
    judge = qualification_model_factory(settings, judge_model)("operator_response", "live")
    new_judge_calls = 0
    report["passed"] = False
    try:
        with Store(
            settings.database_dsn, report["qualification_tenant_id"], settings.site_id,
            settings.tools_dsn, qualification=True,
        ) as store:
            for row in report["cases"]:
                if not row["root_ids"]:
                    continue
                if not row["agent"] or not row["agent"]["report"]["completed"]:
                    row["external_judge_status"] = "not_run_no_accepted_report"
                    continue
                snapshot = store.get_window(row["snapshot_id"])
                evidence = grounded_case_evidence(snapshot, row["agent"])
                hidden = {
                    **expected[row["case_id"]],
                    "source_truth": fixtures[row["case_id"]]["source_truth"],
                    "abstention_is_not_leak_classification_pass": True,
                }
                if not report["judge_calibration"]:
                    for control in calibration_packets(evidence, hidden):
                        result = run_judge(
                            judge, control["packet"], telemetry, identity=control["identity"],
                            tenant_id=report["qualification_tenant_id"],
                            generation_id=row["generation_id"],
                        )
                        result["expected_pass"] = control["expected_pass"]
                        report["judge_calibration"].append(result)
                        new_judge_calls += result["model_calls"]
                result = run_judge(
                    judge, {
                        "case_evidence": evidence, "hidden_expected_outcomes": hidden,
                        "candidate_report": judge_candidate_report(row["agent"]["report"]),
                    }, telemetry, identity=f"{row['case_id']}-recorded-operator-report",
                    tenant_id=report["qualification_tenant_id"],
                    generation_id=row["generation_id"],
                    linked_trace=store.latest_task_trace(row["root_ids"][0]),
                )
                row["external_judge"] = result
                row["external_judge_status"] = result["status"]
                new_judge_calls += result["model_calls"]
                row["deterministic_checks"] = deterministic_golden_checks(
                    expected[row["case_id"]], snapshot, row["agent"],
                    paused=bool(row["paused_window_id"]), root_count=len(row["root_ids"]),
                    state=row["state"],
                )
                row["deterministic_passed"] = all(row["deterministic_checks"].values())
                _save_report(output, report)
            for result in [
                *report["judge_calibration"],
                *(row["external_judge"] for row in report["cases"] if row["external_judge"]),
            ]:
                report["trace_evidence"].append({
                    "kind": "external_judge", "identity": result["identity"],
                    "trace": result.get("trace"),
                    "expected_input_hash": result.get("input_sha256"),
                    "expected_output_hash": result.get("output_sha256"),
                })
            telemetry.flush()
            for entry in report["trace_evidence"]:
                trace_id = (entry["trace"] or {}).get("trace_id")
                entry["stored_tree_verified"] = False
                for _ in range(3):
                    if isinstance(trace_id, str) and telemetry.verify_trace(
                        trace_id, required_types=(
                            ["generation"] if entry["kind"] == "external_judge" else
                            ["agent", "generation", "tool", "guardrail"]
                        ),
                    ):
                        entry["stored_tree_verified"] = True
                        break
                    time.sleep(2)
                entry["stored_content"] = verify_stored_content(
                    trace_id, entry["kind"], output,
                    expected_input_hash=entry.get("expected_input_hash"),
                    expected_output_hash=entry.get("expected_output_hash"),
                ) if isinstance(trace_id, str) else {"passed": False}
            report["judge_calibrated"] = (
                len(report["judge_calibration"]) == 2 and all(
                    result["status"] == "completed"
                    and result["passed"] == result["expected_pass"]
                    for result in report["judge_calibration"]
                )
            )
            report["passed"] = (
                all(row["deterministic_passed"] for row in report["cases"])
                and all(
                    row["external_judge"] and row["external_judge"]["passed"]
                    for row in report["cases"] if row["root_ids"]
                )
                and report["judge_calibrated"]
                and all(
                    entry["stored_tree_verified"] and entry["stored_content"]["passed"]
                    for entry in report["trace_evidence"]
                )
            )
    finally:
        report["model_call_count"]["external_judge"] += new_judge_calls
        report["current_judge_evaluation_calls"] = new_judge_calls
        report["agent_requalification_calls"] = 0
        report["observed_judge_models"] = sorted({
            str(result["model_receipt"]["observed_model"])
            for result in [
                *report["judge_calibration"],
                *(row["external_judge"] for row in report["cases"] if row["external_judge"]),
            ]
            if result.get("model_receipt", {}).get("observed_model")
        })
        telemetry.close()
        report["observability"] = telemetry.health()
        report["passed"] = report["passed"] and not report["observability"]["flush_failed"]
        _save_report(output, report)
    return audit_recorded_operator_outputs(output)


def retry_recorded_case(
    source_output: Path, output: Path, case_id: str,
) -> dict[str, Any]:
    """One explicitly accounted fresh pressure-triggered attempt on the identical frozen input."""
    previous = json.loads((source_output / "qualification.json").read_text())
    original = next(row for row in previous["cases"] if row["case_id"] == case_id)
    if original["state"] not in {"FAILED", "ABSTAINED"}:
        raise ValueError("A focused agent retry requires an original failed/abstained attempt")
    settings = Settings.from_env()
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((source_output / "manifest.json").read_text())
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    expected = next(case["expected"] for case in load_cases()["cases"] if case["id"] == case_id)
    telemetry = Telemetry(runtime_dir=settings.runtime_dir)
    report: dict[str, Any] = {
        "version": "golden-focused-retry-v1", "mode": "live", "passed": False,
        "qualification_tenant_id": previous["qualification_tenant_id"],
        "site_id": settings.site_id, "run_id": output.name,
        "original_attempt": original, "retry_limit": 1,
        "scope": "Fresh automatic root, identical frozen measurements, unchanged production gates.",
        "cases": [], "trace_evidence": [], "model_call_count": {"agent": 0, "external_judge": 0},
        "judge_calibration": [], "model_call_accounting_complete": False,
    }
    _save_report(output, report)
    try:
        with (
            Store(
                settings.database_dsn, previous["qualification_tenant_id"], settings.site_id,
                settings.tools_dsn, qualification=True,
            ) as store,
            postgres_checkpointer(settings.checkpoint_dsn) as saver,
        ):
            source_replay = store.get_replay(original["generation_id"])
            dataset = load_frozen_replay_source(source_replay)
            if dataset is None:
                raise ValueError("Retry source is not immutable")
            factory = qualification_model_factory(settings)
            service = AgentService(store, factory, saver, telemetry)
            monitor = Monitor(store, service, telemetry)
            replay = install_golden_input(monitor, dataset, "live")
            for index in range(13):
                current = monitor.control(replay.id, "step", None, f"focused-step-{index}")
                if current.investigation_window_id:
                    break
            if not current.latest_window_id:
                raise ValueError("Retry did not publish a numerical window")
            snapshot = store.get_window(current.latest_window_id)
            if snapshot.input_hash != original["input_hash"]:
                raise ValueError("Focused retry changed the original numerical inputs")
            roots = [task for task in store.list_tasks(replay.id) if task.parent_id is None]
            if len(roots) != 1:
                raise ValueError("Focused retry did not admit exactly one automatic root")
            root = roots[0]
            row = {
                "case_id": case_id, "generation_id": replay.id,
                "dataset_sha256": original["dataset_sha256"], "snapshot_id": snapshot.id,
                "input_hash": snapshot.input_hash, "clock_seconds": current.clock_seconds,
                "paused_window_id": current.investigation_window_id, "root_ids": [root.id],
                "state": None, "agent": None, "external_judge": None,
                "deterministic_checks": {}, "deterministic_passed": False,
                "external_judge_status": "not_run",
                "same_original_input_hash": True,
            }
            report["cases"].append(row)
            _save_report(output, report)
            started = time.monotonic()
            for _ in range(WORKER_POLL_LIMIT):
                if root.state in TERMINALS:
                    break
                if time.monotonic() - started > ROOT_WATCHDOG_SECONDS:
                    raise RuntimeError("Focused root exceeded its production deadline")
                if not service.run_once():
                    time.sleep(0.05)
                root = store.get_task(root.id)
            audit = audit_operations(store, root, snapshot)
            if root.result:
                audit["grounded_source_texts"] = source_texts(
                    root.result, snapshot, store.tool_receipts(root.id), root.knowledge_packet,
                )
            audit["elapsed_seconds"] = round(time.monotonic() - started, 3)
            row.update(state=root.state, agent=audit, error_code=root.error_code)
            row["deterministic_checks"] = deterministic_golden_checks(
                expected, snapshot, audit, paused=bool(current.investigation_window_id),
                root_count=1, state=root.state,
            )
            row["deterministic_passed"] = all(row["deterministic_checks"].values())
            report["model_call_count"]["agent"] = audit["fresh_model_calls"]
            for task in audit["tasks"]:
                report["trace_evidence"].append({
                    "case_id": case_id, "kind": "runtime_agent", "task_id": task["id"],
                    "role": task["role"], "trace": store.latest_task_trace(task["id"]),
                })
            report["model_call_accounting_complete"] = True
            report["agent_contract_passed"] = row["deterministic_passed"]
            report["passed"] = row["deterministic_passed"]
    except Exception as exc:
        report["integration_blocker"] = getattr(exc, "code", type(exc).__name__)
    finally:
        telemetry.close()
        report["observability"] = telemetry.health()
        _save_report(output, report)
    return report


def select_recorded_retry(
    previous: dict[str, Any], retry: dict[str, Any],
) -> dict[str, Any]:
    """Select real recorded pointers while retaining every failed attempt and call."""
    if (
        len(previous["cases"]) != 4 or len(retry["cases"]) != 1
        or not previous.get("model_call_accounting_complete")
        or not retry.get("model_call_accounting_complete")
        or previous["qualification_tenant_id"] != retry["qualification_tenant_id"]
        or previous["site_id"] != retry["site_id"]
        or not previous.get("judge_calibrated")
        or retry["model_call_count"]["external_judge"] != 0
    ):
        raise ValueError("Retry selection requires completed, same-scope calibrated recordings")
    selected = deepcopy(retry["cases"][0])
    original = next(row for row in previous["cases"] if row["case_id"] == selected["case_id"])
    if (
        original["state"] not in {"FAILED", "ABSTAINED"}
        or selected["state"] != "SUCCEEDED" or not selected["deterministic_passed"]
        or selected["input_hash"] != original["input_hash"]
        or selected["dataset_sha256"] != original["dataset_sha256"]
        or selected["generation_id"] == original["generation_id"]
        or set(selected["root_ids"]) & set(original["root_ids"])
        or selected.get("external_judge") is not None
    ):
        raise ValueError("Retry must be a fresh accepted root on the exact original measurements")
    for row in previous["cases"]:
        if row["case_id"] == selected["case_id"] or not row["root_ids"]:
            continue
        if not row["deterministic_passed"] or not (row.get("external_judge") or {}).get("passed"):
            raise ValueError("Previously selected substantive recordings must already qualify")
    report = deepcopy(previous)
    report["version"] = "golden-recorded-selection-v1"
    report["cases"] = [
        selected if row["case_id"] == selected["case_id"] else deepcopy(row)
        for row in previous["cases"]
    ]
    report["agent_attempts"] = [
        *deepcopy(previous["cases"]), deepcopy(selected),
    ]
    report["selected_retry_case"] = selected["case_id"]
    report["selection_scope"] = (
        "Artifact pointers only; no database records copied or relabelled. One bounded fresh "
        "automatic retry, identical source/input hash, unchanged gates and grounding criteria. "
        "Selected coverage is not first-attempt reliability; initial failure remains recorded."
    )
    report["limitations"] = [
        f"One seed per case; one bounded same-input {selected['case_id']} retry, "
        "with original failure retained. "
        "No reliability, expert certification or time-saving claim."
        if limitation.startswith("One seed/run per case") else limitation
        for limitation in report.get("limitations", [])
    ]
    report["all_agent_attempts_passed"] = all(
        row["deterministic_passed"] for row in report["agent_attempts"] if row["root_ids"]
    )
    report["all_attempts_passed"] = report["all_agent_attempts_passed"] and all(
        judge["status"] == "completed" for judge in report.get("prior_judge_attempts", [])
    )
    report["substantive_agent_attempt_count"] = sum(
        bool(row["root_ids"]) for row in report["agent_attempts"]
    )
    report["failed_agent_attempt_count"] = sum(
        bool(row["root_ids"]) and not row["deterministic_passed"]
        for row in report["agent_attempts"]
    )
    report["model_call_count"] = {
        key: previous["model_call_count"][key] + retry["model_call_count"][key]
        for key in ("agent", "external_judge")
    }
    report["trace_evidence"].extend(deepcopy(retry["trace_evidence"]))
    report["passed"] = False
    return report


def qualify_recorded_retry(
    source_output: Path, retry_output: Path, output: Path, *,
    judge_model: str = "gpt-6.1-sol",
) -> dict[str, Any]:
    """One new hosted verdict, retained calibration, and fresh stored-content verification."""
    if output.resolve() in {source_output.resolve(), retry_output.resolve()}:
        raise ValueError("Selection output must preserve both source attempt artifacts")
    if (output / "qualification.json").exists():
        raise ValueError("Selection output already exists; do not silently repeat hosted judging")
    previous = json.loads((source_output / "qualification.json").read_text())
    retry = json.loads((retry_output / "qualification.json").read_text())
    manifest = json.loads((source_output / "manifest.json").read_text())
    if manifest != json.loads((retry_output / "manifest.json").read_text()):
        raise ValueError("Retry manifest changed")
    report = select_recorded_retry(previous, retry)
    output.mkdir(parents=True, exist_ok=True)
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    report["source_attempt_artifacts"] = [
        str(source_output / "qualification.json"), str(retry_output / "qualification.json"),
    ]
    report["artifact"] = str(output / "qualification.json")
    report["manifest"] = str(output / "manifest.json")
    report["run_id"] = output.name
    _save_report(output, report)
    settings = Settings.from_env()
    telemetry = Telemetry(runtime_dir=settings.runtime_dir)
    try:
        if not telemetry.health()["content_capture"]:
            raise ValueError("Synthetic trace-content flags are required")
        judge = qualification_model_factory(settings, judge_model)("operator_response", "live")
        row = next(
            case for case in report["cases"] if case["case_id"] == report["selected_retry_case"]
        )
        expected = next(
            case["expected"] for case in load_cases()["cases"] if case["id"] == row["case_id"]
        )
        fixture = next(case for case in manifest["cases"] if case["case_id"] == row["case_id"])
        with Store(
            settings.database_dsn, report["qualification_tenant_id"], report["site_id"],
            settings.tools_dsn, qualification=True,
        ) as store:
            snapshot = store.get_window(row["snapshot_id"])
            result = run_judge(
                judge, {
                    "case_evidence": grounded_case_evidence(snapshot, row["agent"]),
                    "hidden_expected_outcomes": {
                        **expected, "source_truth": fixture["source_truth"],
                        "abstention_is_not_leak_classification_pass": True,
                    },
                    "candidate_report": judge_candidate_report(row["agent"]["report"]),
                }, telemetry, identity=f"{row['case_id']}-retry-published-operator-report",
                tenant_id=report["qualification_tenant_id"],
                generation_id=row["generation_id"],
                linked_trace=store.latest_task_trace(row["root_ids"][0]),
            )
        row["external_judge"] = result
        row["external_judge_status"] = result["status"]
        report["model_call_count"]["external_judge"] += result["model_calls"]
        report["selected_retry_judge_calls"] = result["model_calls"]
        report["trace_evidence"].append({
            "kind": "external_judge", "identity": result["identity"], "trace": result.get("trace"),
            "expected_input_hash": result.get("input_sha256"),
            "expected_output_hash": result.get("output_sha256"),
        })
        _save_report(output, report)
        telemetry.flush()
        for entry in report["trace_evidence"]:
            trace_id = (entry.get("trace") or {}).get("trace_id")
            entry["stored_tree_verified"] = bool(
                trace_id and telemetry.verify_trace(
                    trace_id, required_types=(
                        ["generation"] if entry["kind"] == "external_judge"
                        else ["agent", "generation", "tool", "guardrail"]
                    ),
                )
            )
            entry["stored_content"] = verify_stored_content(
                trace_id, entry["kind"], output,
                expected_input_hash=entry.get("expected_input_hash"),
                expected_output_hash=entry.get("expected_output_hash"),
            ) if trace_id else {"passed": False}
        report["passed"] = (
            all(case["deterministic_passed"] for case in report["cases"])
            and all(
                (case.get("external_judge") or {}).get("passed")
                for case in report["cases"] if case["root_ids"]
            )
            and report["judge_calibrated"]
            and all(
                entry["stored_tree_verified"] and entry["stored_content"]["passed"]
                for entry in report["trace_evidence"]
            )
        )
    except Exception as exc:
        report["integration_blocker"] = getattr(exc, "code", type(exc).__name__)
        report["passed"] = False
    finally:
        telemetry.close()
        report["observability"] = telemetry.health()
        report["passed"] = report["passed"] and not report["observability"]["flush_failed"]
        _save_report(output, report)
    return audit_recorded_operator_outputs(output)


def _save_report(output: Path, report: dict[str, Any]) -> None:
    (output / "qualification.json").write_text(
        json.dumps(report, indent=2, allow_nan=False), encoding="utf-8",
    )


def qualify_golden(
    mode: Mode, output: Path, *, agent_model: str = "gpt-6.1-sol",
    judge_model: str = "gpt-6.1-sol",
) -> dict[str, Any]:
    """Run the manifest, production workflow, judging and stored-evidence stages.

    Never reset the database or start/stop console workers; use a fresh isolated tenant.
    Live qualification requires all four cases, five observed live judge receipts,
    calibrated controls and verified runtime/judge trees plus stored IO. Provider
    blocking, missing traces and flush failure cannot pass. Scripted runs exercise
    contracts only and never satisfy the live pass criterion. Partial progress and
    integration blockers are persisted even when the bounded runner fails.
    """
    settings = Settings.from_env()
    manifest = write_manifest(output, site_id=settings.site_id)
    if not manifest["passed"]:
        raise ValueError("Golden measurements do not verify fixture expectations")
    tenant = "golden-eval-" + uuid4().hex[:12]
    corpus = load_cases()
    telemetry = Telemetry(runtime_dir=settings.runtime_dir)
    report: dict[str, Any] = {
        "version": "golden-qualification-v1", "created_at": utc_now().isoformat(),
        "mode": mode, "passed": False, "qualification_tenant_id": tenant,
        "manifest": str(output / "manifest.json"), "recipe_sha256": manifest["recipe_sha256"],
        "requested_agent_model": agent_model, "requested_judge_model": judge_model,
        "planned_cases": 4, "planned_pressure_triggered_agent_roots": 3,
        "planned_judge_calls": 5 if mode == "live" else 0,
        "model_call_accounting_complete": False,
        "provider_blocked": None, "cases": [], "judge_calibration": [],
        "model_call_count": {"agent": 0, "external_judge": 0},
        "trace_evidence": [], "monetary_cost": None,
        "limitations": [
            corpus["scope"],
            "One seed/run per case; no reliability, expert certification or time-saving claim.",
            "The external judge is semantic opinion separate from deterministic checks.",
            "Requested agent and judge models match; self/same-model judging is not independent."
            if agent_model == judge_model else
            "Different requested models do not establish independence; observed identities matter.",
            "Calibration controls are evaluation-only, never runtime answers/specialist results.",
            "Withholding can be conservative; the judge assesses whether abstention is justified.",
            "Langfuse verification checks observation types/trees, not expert answer validity.",
            "Synthetic input/output requires SUBSEA_TRACE_CONTENT=1 and SUBSEA_SYNTHETIC_ONLY=1.",
            "Scripted/unobserved models, provider failure and missing traces do not qualify.",
        ],
    }
    _save_report(output, report)
    try:
        with (
            Store(
                settings.database_dsn, tenant, settings.site_id, settings.tools_dsn,
                qualification=True,
            ) as store,
            postgres_checkpointer(settings.checkpoint_dsn) as saver,
        ):
            factory = qualification_model_factory(settings, agent_model)
            service = AgentService(store, factory, saver, telemetry)
            monitor = Monitor(store, service, telemetry)
            judge = qualification_model_factory(settings, judge_model)("operator_response", "live")
            for case, fixture in zip(corpus["cases"], manifest["cases"], strict=True):
                dataset = generate_golden(
                    case, corpus["seed"], corpus["duration_seconds"], settings.site_id,
                )
                replay = install_golden_input(monitor, dataset, mode)
                # Exact production step/watermark lifecycle; no manual submit_question.
                for index in range(13):
                    current = monitor.control(replay.id, "step", None, f"golden-step-{index}")
                    if current.investigation_window_id:
                        break
                if not current.latest_window_id:
                    raise RuntimeError("Production monitor did not publish a complete window")
                snapshot = store.get_window(current.latest_window_id)
                roots = [t for t in store.list_tasks(replay.id) if t.parent_id is None]
                row: dict[str, Any] = {
                    "case_id": case["id"], "generation_id": replay.id,
                    "dataset_sha256": fixture["dataset_sha256"], "snapshot_id": snapshot.id,
                    "input_hash": snapshot.input_hash, "clock_seconds": current.clock_seconds,
                    "paused_window_id": current.investigation_window_id,
                    "root_ids": [t.id for t in roots], "agent": None,
                    "external_judge": None, "state": None,
                    "deterministic_passed": False, "deterministic_checks": {},
                    "external_judge_status": "not_run",
                }
                report["cases"].append(row)
                _save_report(output, report)
                audit = None
                if roots:
                    root = roots[0]
                    started = time.monotonic()
                    for _ in range(WORKER_POLL_LIMIT):
                        if root.state in TERMINALS:
                            break
                        if time.monotonic() - started > ROOT_WATCHDOG_SECONDS:
                            raise RuntimeError("Golden root exceeded production deadline")
                        if not service.run_once():
                            time.sleep(0.05)
                        root = store.get_task(root.id)
                    if root.state not in TERMINALS:
                        raise RuntimeError("Golden root exceeded bounded runner iterations")
                    audit = audit_operations(store, root, snapshot)
                    if root.result:
                        audit["grounded_source_texts"] = source_texts(
                            root.result, snapshot, store.tool_receipts(root.id),
                            root.knowledge_packet,
                        )
                    audit["elapsed_seconds"] = round(time.monotonic() - started, 3)
                    # Persist explicit identities/usage but never provider captures or headers.
                    audit["model_receipts"] = [
                        {
                            "task_id": item["task_id"],
                            **{key: item.get(key) for key in MODEL_METADATA_KEYS},
                        }
                        for item in audit["model_receipts"]
                    ]
                    row.update(agent=audit, state=root.state, error_code=root.error_code)
                    report["model_call_count"]["agent"] += audit["fresh_model_calls"]
                    for task in audit["tasks"]:
                        trace = store.latest_task_trace(task["id"])
                        report["trace_evidence"].append({
                            "case_id": case["id"], "kind": "runtime_agent",
                            "task_id": task["id"], "role": task["role"], "trace": trace,
                        })
                    if root.error_code in {"proxy_auth", "proxy_quota"}:
                        report["provider_blocked"] = root.error_code
                    if mode == "live" and audit["report"]["completed"]:
                        evidence = grounded_case_evidence(snapshot, audit)
                        hidden = {
                            **case["expected"], "source_truth": fixture["source_truth"],
                            "bounded_synthetic_scope": corpus["scope"],
                        }
                        if not report["judge_calibration"]:
                            for control in calibration_packets(evidence, hidden):
                                result = run_judge(
                                    judge, control["packet"], telemetry,
                                    identity=control["identity"], tenant_id=tenant,
                                    generation_id=replay.id,
                                )
                                result["expected_pass"] = control["expected_pass"]
                                report["judge_calibration"].append(result)
                                report["model_call_count"]["external_judge"] += (
                                    result["model_calls"]
                                )
                                if result.get("error_code") in {"proxy_auth", "proxy_quota"}:
                                    report["provider_blocked"] = result["error_code"]
                                    break
                        if not report["provider_blocked"]:
                            row["external_judge"] = run_judge(
                                judge, {
                                    "case_evidence": evidence,
                                    "hidden_expected_outcomes": hidden,
                                    "candidate_report": judge_candidate_report(audit["report"]),
                                }, telemetry, identity=f"{case['id']}-actual-agent-report",
                                tenant_id=tenant, generation_id=replay.id,
                                linked_trace=store.latest_task_trace(root.id),
                            )
                            report["model_call_count"]["external_judge"] += (
                                row["external_judge"]["model_calls"]
                            )
                            if row["external_judge"].get("error_code") in {
                                "proxy_auth", "proxy_quota",
                            }:
                                report["provider_blocked"] = row["external_judge"]["error_code"]
                row["deterministic_checks"] = deterministic_golden_checks(
                    case["expected"], snapshot, audit,
                    paused=bool(current.investigation_window_id), root_count=len(roots),
                    state=row["state"],
                )
                row["deterministic_passed"] = all(row["deterministic_checks"].values())
                row["external_judge_status"] = (
                    row["external_judge"]["status"] if row["external_judge"] else
                    "not_applicable_no_pressure_trigger" if not case["expected"]["pressure_trigger"]
                    else "not_run_no_accepted_live_report"
                )
                _save_report(output, report)
                if report["provider_blocked"]:
                    break
            for result in [
                *report["judge_calibration"],
                *(row["external_judge"] for row in report["cases"] if row["external_judge"]),
            ]:
                report["trace_evidence"].append({
                    "kind": "external_judge", "identity": result["identity"],
                    "trace": result["trace"],
                    "expected_input_hash": result.get("input_sha256"),
                    "expected_output_hash": result.get("output_sha256"),
                })
            report["model_call_accounting_complete"] = True
            telemetry.flush()
            for entry in report["trace_evidence"]:
                trace_id = (entry["trace"] or {}).get("trace_id")
                entry["stored_tree_verified"] = False
                for _ in range(3):
                    if isinstance(trace_id, str) and telemetry.verify_trace(
                        trace_id, required_types=(
                            ["generation"] if entry["kind"] == "external_judge"
                            else ["agent", "generation", "tool", "guardrail"]
                        ),
                    ):
                        entry["stored_tree_verified"] = True
                        break
                    time.sleep(2)
                entry["stored_content"] = (
                    verify_stored_content(
                        trace_id, entry["kind"], output,
                        expected_input_hash=entry.get("expected_input_hash"),
                        expected_output_hash=entry.get("expected_output_hash"),
                    ) if isinstance(trace_id, str) else {"passed": False}
                )
            report["observability"] = telemetry.health()
            report["judge_calibrated"] = (
                len(report["judge_calibration"]) == 2 and all(
                    r["status"] == "completed" and r["passed"] == r["expected_pass"]
                    for r in report["judge_calibration"]
                )
            )
            receipts = [
                r for row in report["cases"] if row["agent"]
                for r in row["agent"]["model_receipts"]
            ]
            report["observed_agent_models"] = sorted({
                str(r["observed_model"]) for r in receipts if r.get("observed_model")
            })
            judge_receipts = [
                r["model_receipt"] for r in report["judge_calibration"]
                if r.get("model_receipt")
            ] + [
                row["external_judge"]["model_receipt"] for row in report["cases"]
                if row["external_judge"] and row["external_judge"].get("model_receipt")
            ]
            report["observed_judge_models"] = sorted({
                str(r["observed_model"]) for r in judge_receipts if r.get("observed_model")
            })
            report["observed_model_overlap"] = sorted(
                set(report["observed_agent_models"]) & set(report["observed_judge_models"])
            )
            report["actual_cases"] = len(report["cases"])
            report["unattempted_cases"] = 4 - len(report["cases"])
            report["passed"] = (
                mode == "live" and len(report["cases"]) == 4
                and all(row["deterministic_passed"] for row in report["cases"])
                and all(
                    row["external_judge"] and row["external_judge"]["passed"]
                    for row in report["cases"] if row["root_ids"]
                )
                and report["judge_calibrated"]
                and bool(receipts) and all(
                    r.get("mode") == "live" and bool(r.get("observed_model")) for r in receipts
                )
                and len(judge_receipts) == 5 and all(
                    r.get("mode") == "live" and bool(r.get("observed_model"))
                    for r in judge_receipts
                )
                and bool(report["trace_evidence"])
                and all(e["stored_tree_verified"] for e in report["trace_evidence"])
                and all(e["stored_content"]["passed"] for e in report["trace_evidence"])
                and report["observability"]["content_capture"] is True
                and not report["provider_blocked"]
            )
    except Exception as exc:
        report["integration_blocker"] = getattr(exc, "code", type(exc).__name__)
        report["passed"] = False
    finally:
        telemetry.close()
        report["observability"] = telemetry.health()
        report["passed"] = report["passed"] and not report["observability"]["flush_failed"]
        report["attempted_cases"] = len(report["cases"])
        report["unattempted_cases"] = 4 - len(report["cases"])
        report["artifact"] = str(output / "qualification.json")
        _save_report(output, report)
    if mode == "live" and report["model_call_accounting_complete"] and len(report["cases"]) == 4:
        return audit_recorded_operator_outputs(output)
    return report

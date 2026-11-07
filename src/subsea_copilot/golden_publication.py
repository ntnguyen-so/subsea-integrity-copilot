"""Small public qualification receipts; historical failures are never reconstructed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import content_hash, utc_now
from .golden_evidence import fetch_stored_observations, normalized_content
from .telemetry import Telemetry


def publish_recorded_receipts(output: Path) -> dict[str, Any]:
    report = json.loads((output / "qualification.json").read_text())
    receipt = json.loads((output / "recorded-receipt.json").read_text())
    manifest = json.loads((output / "manifest.json").read_text())
    destination = output / "public"
    destination.mkdir(parents=True, exist_ok=True)
    failures = []
    telemetry = Telemetry()
    try:
        for judge in report.get("prior_judge_attempts", []):
            trace_id = judge["trace"]["trace_id"]
            observations = fetch_stored_observations(trace_id)
            generations = [
                observation for observation in observations
                if str(observation["type"]).lower() == "generation"
            ]
            directory = output / "stored-rejected-observations"
            directory.mkdir(parents=True, exist_ok=True)
            (directory / f"{trace_id}.json").write_text(
                json.dumps(observations, indent=2, allow_nan=False), encoding="utf-8",
            )
            failures.append({
                "identity": judge["identity"], "trace_id": trace_id,
                "local_error_code": judge["error_code"],
                "stored_tree_verified": telemetry.verify_trace(
                    trace_id, required_types=["generation"],
                ),
                "stored_input_matches_original_submission": any(
                    content_hash(normalized_content(observation["input"]))
                    == judge["input_sha256"] for observation in generations
                ),
                "stored_output_present": any(
                    normalized_content(observation["output"]) not in (None, "", {}, [])
                    for observation in generations
                ),
                "stored_error_code_matches": any(
                    observation["public_model_metadata"].get("error.code") == judge["error_code"]
                    for observation in generations
                ),
                "stored_levels": [observation.get("level") for observation in generations],
                "stored_public_error_metadata": [
                    {
                        key: value for key, value in observation["public_model_metadata"].items()
                        if key in {"error.code", "error.type", "judge.outcome"}
                    }
                    for observation in generations
                ],
                "observed_model": judge["model_receipt"]["observed_model"],
                "request_id": judge["model_receipt"]["request_id"],
                "calls": judge["model_calls"], "elapsed_seconds": judge["elapsed_seconds"],
                "output_gap": (
                    "Original code recorded output only after transport validation. Missing wire "
                    "mode rejected these real calls before output capture. Original response text "
                    "was not retained; it cannot be truthfully reconstructed or backfilled."
                ),
            })
    finally:
        telemetry.close()

    original_g3 = next(
        row for row in report["agent_attempts"]
        if row["case_id"] == "G3" and row["state"] == "FAILED"
    )
    selected_g3 = next(row for row in report["cases"] if row["case_id"] == "G3")
    fixtures = next(row for row in manifest["cases"] if row["case_id"] == "G3")
    original_manifest = json.loads(
        (Path(report["source_attempt_artifacts"][0]).parent / "manifest.json").read_text()
    )
    original_truth = next(
        row["source_truth"] for row in original_manifest["cases"] if row["case_id"] == "G3"
    )
    failed_agent = {
        "case_id": "G3", "root_task_id": original_g3["root_ids"][0],
        "replay_id": original_g3["generation_id"], "state": original_g3["state"],
        "error_code": original_g3["error_code"],
        "agent_calls": original_g3["agent"]["fresh_model_calls"],
        "agent_elapsed_seconds": original_g3["agent"]["elapsed_seconds"],
        "history": (
            "Critic-0 requested a synthetic-limitation citation in the answer. Reflection "
            "addressed it but altered the regional shared-connectivity interpretation. Critic-1 "
            "found the region uncertain: selectively reviewed healthy/warning channels cannot "
            "exclude uninvestigated shared failures. The normal one-reflection budget was "
            "exhausted; grounding_rejected correctly withheld an accepted answer/inspection. "
            "The eligible numerical leak candidate was not counted as model classification."
        ),
    }
    history = {
        "all_attempts_passed": False, "failed_agent_attempt": failed_agent,
        "rejected_judge_attempts": failures,
        "changes_and_reruns": [
            "No golden source recipe, source truth, baseline, geometry, admission gate, numerical "
            "threshold, runtime agent prompt, knowledge card or grounding criterion was relaxed.",
            "Standalone Copilot CLI responses omitted mode, although observed model/request/usage "
            "were present. The external judge now supplies live mode only from actual owned "
            "CopilotCLIChatModel transport provenance; unobserved/scripted/provider failures fail.",
            "Rubric version, rubric bytes, six dimensions and minimum scores stayed unchanged. "
            "External judge prompt/protocol was strengthened to grade model-authored causes, "
            "regions and published prose; class references must include candidate_report.answer. "
            "The mechanical field became numerical_contract_tag; expected outcomes explicitly "
            "say abstention is not leak classification. Accepted matching overlays are audited.",
            "Re-ran two hosted calibration controls and judged unchanged recorded G1/G2 answers "
            "(four calls), not their agents. Ran one fresh normal pressure-triggered G3 attempt "
            "on identical frozen measurements (seven agent calls), then one hosted G3 judge. "
            "No further hosted calls were made to create these public receipts.",
            "After historical output gaps were discovered, future rejected judge calls were "
            "hardened to capture schema-valid public output before identity/reference validation "
            "and mark error span status; malformed/private content records only a safe marker. "
            "This does not retroactively repair the four original missing outputs.",
        ],
        "g3_fidelity": {
            "original_dataset_sha256": original_g3["dataset_sha256"],
            "selected_dataset_sha256": selected_g3["dataset_sha256"],
            "original_input_hash": original_g3["input_hash"],
            "selected_input_hash": selected_g3["input_hash"],
            "original_truth_sha256": content_hash(original_truth),
            "selected_truth_sha256": content_hash(fixtures["source_truth"]),
            "unchanged": (
                original_g3["dataset_sha256"] == selected_g3["dataset_sha256"]
                and original_g3["input_hash"] == selected_g3["input_hash"]
                and original_truth == fixtures["source_truth"]
            ),
            "recipe_sha256": manifest["recipe_sha256"],
            "rubric_sha256": report["judge_calibration"][0]["rubric_sha256"],
        },
    }
    judgments = [
        {
            key: judge.get(key) for key in (
                "identity", "status", "passed", "expected_pass", "rubric_version",
                "rubric_sha256", "judge_protocol_version", "verdict", "trace",
                "input_sha256", "output_sha256", "input_chars", "output_chars",
                "elapsed_seconds", "model_calls", "model_receipt",
            )
        }
        for judge in [
            *report["judge_calibration"],
            *(row["external_judge"] for row in report["cases"] if row.get("external_judge")),
        ]
    ]
    artifacts = {
        "golden-dataset-manifest.json": manifest,
        "qualification-summary.json": {
            key: receipt[key] for key in (
                "passed_selected_coverage", "run_id", "tenant_id", "site_id",
                "model_calls_all_attempts", "substantive_agent_attempt_count",
                "failed_agent_attempt_count", "all_attempts_passed", "cases", "limitations",
                "source_display", "qa_command", "qa_browser_environment_command",
            )
        },
        "qualification-failures.json": history,
        "judge-verdicts.json": judgments,
        "qa-ui-cases.json": json.loads((output / "qa-ui-cases.json").read_text()),
        "langfuse-trace-index.json": {
            "verified_at": utc_now().isoformat(),
            "runtime_and_completed_judge_trees": [
                {
                    **{key: entry.get(key) for key in (
                        "kind", "case_id", "task_id", "role", "identity", "trace",
                        "expected_input_hash", "expected_output_hash", "stored_tree_verified",
                    )},
                    "stored_io_verified": entry["stored_content"]["passed"],
                    "stored_generation_count": sum(
                        row["type"] == "generation"
                        for row in entry["stored_content"]["observations"]
                    ),
                    "stored_tool_count": sum(
                        row["type"] == "tool" for row in entry["stored_content"]["observations"]
                    ),
                    "hidden_truth_absent_from_runtime_inputs": all(
                        row.get("hidden_truth_absent_from_stored_input") is True
                        for row in entry["stored_content"]["observations"]
                    ) if entry["kind"] == "runtime_agent" else None,
                }
                for entry in report["trace_evidence"]
            ],
            "rejected_judge_trees": failures,
            "scope": (
                "17 complete verified trees = 12 runtime + 5 completed judge. Four additional "
                "rejected judge trees exist; input hashes/error metadata are verified separately. "
                "Missing rejected outputs are an explicit historical observability gap."
            ),
        },
    }
    sizes = {}
    for name, value in artifacts.items():
        serialized = json.dumps(value, indent=2, allow_nan=False)
        (destination / name).write_text(serialized, encoding="utf-8")
        sizes[name] = len(serialized.encode("utf-8"))
    return {
        "passed": True, "scope": "Public receipt export, not all-attempt qualification success.",
        "all_attempts_passed": False, "model_calls": 0, "destination": str(destination),
        "artifact_bytes": sizes,
        "historical_rejected_judge_outputs_complete": all(
            failure["stored_output_present"] for failure in failures
        ),
    }

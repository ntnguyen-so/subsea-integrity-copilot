"""Compare inspection priorities on identical numerical candidates and visible records."""

import argparse
import hashlib
import json
import time
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError as SchemaError

from subsea_copilot.config import Settings
from subsea_copilot.inspection_evaluation import (
    CASE_PATH,
    InspectionDecision,
    case_snapshot,
    fixed_inspection_baseline,
    inspection_candidates,
    load_inspection_suite,
    validate_inspection_decision,
    visible_records,
)
from subsea_copilot.llm.copilot_cli import CopilotCLIChatModel, ProviderError
from subsea_copilot.validation import ValidationError

POLICY = """You are a read-only subsea integrity investigation assistant.
Choose FIRST inspection priority from the supplied provisional numerical candidates.
Candidate coordinates are code-owned conditional brackets, NOT confirmed leak positions.
Never add candidates, coordinates or sensors; never clear a pipe of leaks.
Keep every unexplained candidate in first_priority. A verified current live-line
operation matching the pressure period AND the whole affected station group can
justify lower priority, not exclusion from all investigation or leak clearance.
Read what actually happened, not just asset tags or words like completed.
Distinguish executed work from plans, paperwork state, quoted earlier events,
isolated test apparatus, one-tap exercises and superseded/corrected statements.
Unresolved conflicting accounts cannot justify demotion. Future documents are
unavailable. Drafts cannot justify demotion. Only current approved records may be
cited. A correction supersedes the explicitly named earlier record.
Partition all candidates into first_priority and deprioritized, without duplicates.
For each demotion cite actual approved current document_ids and explain the scope
and temporal match. If candidates are empty, return empty lists, withholding location.
Explain uncertainty and verification needed; these priorities require engineer review.
Return a final inner JSON object matching response_schema, not tool calls.
The transport final envelope value must be the inner JSON encoded as a STRING.
"""


def score(decision: InspectionDecision | None, expected: list[str]) -> dict[str, object]:
    actual = set(decision.first_priority) if decision else set()
    return {
        "exact_first_priority": decision is not None and actual == set(expected),
        "unjustified_demotions": sorted(set(expected) - actual) if decision else [],
        "excess_priority_areas": sorted(actual - set(expected)),
        "failed_answer": decision is None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["fixed", "live"], default="fixed")
    parser.add_argument("--split", choices=["all", "development", "held_out"], default="all")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    suite = load_inspection_suite()
    code = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "subsea_copilot"
        / ("inspection_evaluation.py")
    )
    frozen = {
        "data_sha256": hashlib.sha256(CASE_PATH.read_bytes()).hexdigest(),
        "policy_and_numeric_code_sha256": hashlib.sha256(code.read_bytes()).hexdigest(),
        "evaluation_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "model_policy_sha256": hashlib.sha256(POLICY.encode()).hexdigest(),
    }
    model = (
        CopilotCLIChatModel(
            runtime_dir=Settings.from_env().runtime_dir,
            model_id="gpt-6.1-sol",
        )
        if args.mode == "live"
        else None
    )
    rows = []
    for case in suite.cases:
        if args.split != "all" and case.split != args.split:
            continue
        pack, snapshot = case_snapshot(case)
        candidates = inspection_candidates(pack, snapshot)
        records = visible_records(case)
        fixed = fixed_inspection_baseline(candidates, records)
        validate_inspection_decision(fixed, candidates, records)
        numerical = InspectionDecision(
            first_priority=[candidate.segment_id for candidate in candidates],
            deprioritized=[],
            explanation="Numerical-only: all computed candidate areas retain first priority.",
        )
        row = {
            "id": case.id,
            "split": case.split,
            "expected_first": case.expected_first,
            "candidates": [candidate.model_dump(mode="json") for candidate in candidates],
            "visible_records": [record.model_dump(mode="json") for record in records],
            "numerical_only": {
                "decision": numerical.model_dump(mode="json"),
                **score(numerical, case.expected_first),
            },
            "context_fixed": {
                "decision": fixed.model_dump(mode="json"),
                **score(fixed, case.expected_first),
            },
        }
        if model is not None:
            started = time.monotonic()
            receipt = {}
            decision = None
            error = None
            if not candidates:
                # Geometry abstention is a code decision, not an LLM success.
                decision = numerical
            else:
                evidence = {
                    "incident_clock_seconds": 185,
                    "pressure_window_seconds": [120, 180],
                    "signal_onset_seconds": 90,
                    "candidates": row["candidates"],
                    "records": row["visible_records"],
                    "response_schema": InspectionDecision.model_json_schema(),
                }
                try:
                    response = model.invoke(
                        [
                            SystemMessage(content=POLICY),
                            HumanMessage(content=json.dumps(evidence, separators=(",", ":"))),
                        ]
                    )
                    receipt = response.response_metadata
                    if not isinstance(response.content, str):
                        raise ValidationError("inspection_response", "Expected JSON text")
                    parsed = InspectionDecision.model_validate_json(response.content)
                    validate_inspection_decision(parsed, candidates, records)
                    decision = parsed
                except ProviderError as exc:
                    error, receipt = exc.code, exc.metadata
                except SchemaError:
                    error = "inspection_schema"
                except ValidationError as exc:
                    error = exc.code
            row["llm_context"] = {
                "decision": decision.model_dump(mode="json") if decision else None,
                "error_code": error,
                "model_calls": int(bool(candidates)),
                "elapsed_seconds": time.monotonic() - started,
                "receipt": receipt,
                **score(decision, case.expected_first),
            }
        rows.append(row)
        # Preserve partial results on interruption; never turn a failed answer into a tie.
        report = {
            "version": suite.version,
            "mode": args.mode,
            "split": args.split,
            **frozen,
            "scope": suite.scope,
            "limitations": [
                "Author-created synthetic rubric; held_out means excluded from development cases, "
                "not external customer validation or an independently authored blind trial.",
                "This separate evaluation harness does not add replay scenarios to the console "
                "or override its physical localization gate.",
                "All methods share the same numerical candidates and visible evidence.",
                "Citation/scope checks do not prove semantic entailment; engineer review required.",
                "First priority is not a leak clearance for any deprioritized area.",
                "No geometry improvement, field accuracy, cost savings or universal superiority "
                "can be inferred from this suite.",
                "An improved deterministic parser or structured execution data may close gaps.",
                "Zero-candidate answers are code-owned abstentions, with zero LLM calls.",
            ],
            "results": rows,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"case": case.id, "mode": args.mode}), flush=True)
    for split in ("all", "development", "held_out"):
        selected = [row for row in rows if split == "all" or row["split"] == split]
        for method in ("numerical_only", "context_fixed", "llm_context"):
            evaluated = [row[method] for row in selected if method in row]
            if evaluated:
                print(
                    json.dumps(
                        {
                            "split": split,
                            "method": method,
                            "exact": sum(item["exact_first_priority"] for item in evaluated),
                            "total": len(evaluated),
                            "failed": sum(item["failed_answer"] for item in evaluated),
                            "unjustified_demotions": sum(
                                len(item["unjustified_demotions"]) for item in evaluated
                            ),
                        }
                    )
                )
    if model and any(row["llm_context"]["failed_answer"] for row in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

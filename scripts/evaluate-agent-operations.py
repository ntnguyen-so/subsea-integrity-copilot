"""Run actual production workflows against a matched zero-LLM report baseline."""

# Inputs select synthetic seeds/scenarios/questions; output is an incremental cohort
# report with task/receipt provenance and a fixed-policy comparison on identical data.
# Requires configured database/checkpointer services in both modes. Live additionally
# requires authenticated hosted Copilot access; scripted checks contracts, not reasoning.
# Creates a new qualification tenant; refuses an existing output. Explicit retries
# create new attempts linked to failed roots, never rewrite the source cohort.
import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from subsea_copilot.config import Settings
from subsea_copilot.contracts import AgentTask, ReplaySession, utc_now
from subsea_copilot.diagnostics import analyze_window
from subsea_copilot.history_data import history_index_rows
from subsea_copilot.ingest import normalize_records
from subsea_copilot.llm.copilot_cli import CopilotCLIChatModel
from subsea_copilot.operations_evaluation import (
    EXPECTED_ACTIONS,
    EXPECTED_CONTEXT,
    EXPECTED_RECORDS,
    audit_operations,
    deterministic_report,
    report_rubric,
    summarize,
)
from subsea_copilot.runtime.checkpointer import postgres_checkpointer
from subsea_copilot.runtime.registry import REGISTRY
from subsea_copilot.runtime.scripted import ScriptedChatModel
from subsea_copilot.runtime.workflow import AgentService
from subsea_copilot.store import Store
from subsea_copilot.synthetic import (
    CUSTOMER_QUESTIONS,
    SCENARIOS,
    SOURCE_VERSION,
    generate_scenario,
)
from subsea_copilot.telemetry import Telemetry


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["scripted", "live"], default="scripted")
    parser.add_argument("--seeds", nargs="+", type=int, default=[91000])
    parser.add_argument("--scenarios", nargs="+", choices=list(SCENARIOS), default=list(SCENARIOS))
    parser.add_argument(
        "--question-indices", nargs="+", type=int, choices=[1, 2, 3], default=[1, 2, 3]
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--retry-from",
        type=Path,
        help="Explicit new attempts for failed cases only; never edits the original cohort.",
    )
    args = parser.parse_args()
    if not 1 <= len(args.seeds) <= 3 or len(set(args.seeds)) != len(args.seeds):
        parser.error("Choose one to three distinct seeds.")
    if len(set(args.scenarios)) != len(args.scenarios) or (
        len(set(args.question_indices)) != len(args.question_indices)
    ):
        parser.error("Scenario and question selections must be distinct.")
    if args.output.exists():
        parser.error("Output already exists; preserve each attempt in a new file.")
    retry_cases = None
    if args.retry_from:
        original = json.loads(args.retry_from.read_text(encoding="utf-8"))
        if original["mode"] != args.mode or original["source_version"] != SOURCE_VERSION:
            parser.error("Retry mode and source version must match the original cohort.")
        failed = [
            row
            for row in original["results"]
            if row["state"] in {"FAILED", "CANCELLED"} or not row["agent"]["rubric_passed"]
        ]
        retry_cases = {
            (row["seed"], row["scenario"], row["question_index"]): row["root_id"] for row in failed
        }
        if not retry_cases or len(retry_cases) != len(failed):
            parser.error("Retry input needs distinct failed cases.")
        args.seeds = sorted({key[0] for key in retry_cases})
        args.scenarios = sorted({key[1] for key in retry_cases})
        args.question_indices = sorted({key[2] for key in retry_cases})
    settings = Settings.from_env()
    telemetry = Telemetry(runtime_dir=settings.runtime_dir)
    tenant = "operations-" + uuid4().hex
    rows = []
    attempts = []
    expected_count = len(args.scenarios) * len(args.question_indices) * len(args.seeds)
    if retry_cases is not None:
        expected_count = len(retry_cases)
    report = {
        "schema_version": "agent-operations-v1",
        "started_at": utc_now().isoformat(),
        "finished_at": None,
        "mode": args.mode,
        "tenant_id": tenant,
        "source_version": SOURCE_VERSION,
        "response_protocol": "engineer-v2",
        "seeds": args.seeds,
        "scenarios": args.scenarios,
        "question_indices": args.question_indices,
        "retry_from": str(args.retry_from) if args.retry_from else None,
        "retry_parent_root_ids": list(retry_cases.values()) if retry_cases else [],
        "questions": list(CUSTOMER_QUESTIONS),
        "planned_reports": expected_count,
        "evaluation_expectations": {
            "contexts": {k: sorted(v) for k, v in EXPECTED_CONTEXT.items()},
            "relevant_record_any_of": {k: sorted(v) for k, v in EXPECTED_RECORDS.items()},
            "next_actions": {k: sorted(v) for k, v in EXPECTED_ACTIONS.items()},
        },
        "results": rows,
        "attempts": attempts,
        "summary": summarize(rows, expected_count),
        "error": None,
        "limitations": [
            "Synthetic authored rubric, not blind independent or field evaluation.",
            "Semantic correctness of every prose assertion requires independent expert review.",
            "Same-model critic agreement is not a hallucination-free guarantee.",
            "Both methods get identical arrival-gated observations, snapshot and history corpus.",
            "Baseline executes real SQL retrieval/comparison and a conservative fixed template.",
            "Timing starts at question submission, after the shared numerical snapshot is ready.",
            "First question per scenario/seed is cold; later questions may reuse specialists.",
            "Failures and unattempted planned cases stay in the planned denominator.",
            "Questions sharing specialists are correlated, not independent reliability trials.",
            "Ten-minute manual baseline is assumed; human time and total costs are unmeasured.",
            "Scripted results qualify contracts only, never model reasoning or accuracy.",
        ],
    }

    # Keep planned, attempted and completed counts distinct so interruption/provider
    # failures cannot improve the score by silently shrinking its denominator.
    def save() -> None:
        report["summary"] = summarize(rows, expected_count, attempted_count=len(attempts))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )

    save()
    try:
        with (
            Store(
                settings.database_dsn,
                tenant_id=tenant,
                tools_dsn=settings.tools_dsn,
                qualification=True,
            ) as store,
            postgres_checkpointer(settings.checkpoint_dsn) as saver,
        ):
            service = AgentService(
                store,
                lambda role, mode: (
                    CopilotCLIChatModel(runtime_dir=settings.runtime_dir, model_id="gpt-6.1-sol")
                    if mode == "live"
                    else ScriptedChatModel(role=role)
                ),
                saver,
                telemetry,
            )
            history_version = store.install_history(history_index_rows())
            blocked = False
            for seed in args.seeds:
                for scenario in args.scenarios:
                    source = generate_scenario(scenario, seed, duration_seconds=180)
                    replay = store.create_replay(
                        ReplaySession(
                            id="operations-" + uuid4().hex,
                            tenant_id=tenant,
                            scenario=scenario,
                            seed=seed,
                            source_version=SOURCE_VERSION,
                            mode=args.mode,
                            epoch=source.epoch,
                            clock_seconds=185,
                        )
                    )
                    # The 180s window is evaluated at receive-time 185s. Both methods
                    # see only arrivals available then, not future source records.
                    arrived = [
                        row
                        for row in source.records
                        if (
                            datetime.fromisoformat(row.received_at.replace("Z", "+00:00"))
                            - source.epoch
                        ).total_seconds()
                        <= 185
                    ]
                    observations = normalize_records(arrived, source.pack)
                    store.save_observations(replay.id, observations)
                    snapshot = store.save_window(
                        analyze_window(
                            source.pack,
                            normalize_records(source.baseline, source.pack),
                            observations,
                            replay.id,
                            180,
                            185,
                            source.epoch,
                            tenant_id=tenant,
                        )
                    )
                    for index, question in enumerate(CUSTOMER_QUESTIONS, 1):
                        if index not in args.question_indices:
                            continue
                        key = (seed, scenario, index)
                        if retry_cases is not None and key not in retry_cases:
                            continue
                        attempt = {
                            "scenario": scenario,
                            "seed": seed,
                            "question_index": index,
                            "started_at": utc_now().isoformat(),
                            "root_id": None,
                            "state": "STARTED",
                        }
                        attempts.append(attempt)
                        save()
                        baseline_task = AgentTask(
                            id="fixed-" + uuid4().hex,
                            root_id="not-an-agent-execution",
                            tenant_id=tenant,
                            site_id=snapshot.site_id,
                            generation_id=replay.id,
                            snapshot_id=snapshot.id,
                            role="operator_response",
                            purpose=REGISTRY["operator_response"].purpose,
                            question=question,
                            mode="scripted",
                            deadline=utc_now(),
                            history_version=history_version,
                        )
                        baseline = deterministic_report(store, baseline_task, snapshot, index)
                        baseline["rubric"] = report_rubric(scenario, index, baseline["report"])
                        baseline["rubric_passed"] = all(baseline["rubric"].values())
                        # Wall timing excludes the shared numerical preprocessing and
                        # baseline; later questions may reuse prior specialist work.
                        started = time.perf_counter()
                        root = service.submit_question(
                            replay, snapshot, question, f"operations:{index}"
                        )
                        attempt.update(root_id=root.id, state=root.state)
                        save()
                        iterations = 0
                        while root.state not in {"SUCCEEDED", "ABSTAINED", "FAILED", "CANCELLED"}:
                            if time.perf_counter() - started > 330 or iterations >= 100:
                                raise RuntimeError("Qualification task exceeded its outer bound.")
                            if not service.run_once():
                                time.sleep(0.05)
                            iterations += 1
                            root = store.get_task(root.id)
                        elapsed = time.perf_counter() - started
                        agent = audit_operations(store, root, snapshot)
                        agent["elapsed_seconds"] = elapsed
                        agent["rubric"] = report_rubric(scenario, index, agent["report"])
                        agent["rubric_passed"] = all(agent["rubric"].values())
                        before = [
                            (t.id, t.model_calls, t.tool_calls) for t in store.list_tasks(replay.id)
                        ]
                        same = service.submit_question(
                            replay, snapshot, question, f"operations:{index}"
                        )
                        agent["checks"]["idempotent_resubmission"] = same == root and before == [
                            (t.id, t.model_calls, t.tool_calls) for t in store.list_tasks(replay.id)
                        ]
                        rows.append(
                            {
                                "scenario": scenario,
                                "seed": seed,
                                "question_index": index,
                                "question": question,
                                "root_id": root.id,
                                "retry_parent_root_id": retry_cases[key] if retry_cases else None,
                                "snapshot_id": snapshot.id,
                                "input_hash": snapshot.input_hash,
                                "history_version": root.history_version,
                                "state": root.state,
                                "error_code": root.error_code,
                                "agent": agent,
                                "deterministic": baseline,
                            }
                        )
                        attempt.update(state=root.state, finished_at=utc_now().isoformat())
                        save()
                        print(
                            json.dumps(
                                {
                                    "scenario": scenario,
                                    "question": index,
                                    "state": root.state,
                                    "rubric_passed": agent["rubric_passed"],
                                    "failed_checks": [
                                        k for k, v in agent["checks"].items() if not v
                                    ],
                                    "failed_rubric": [
                                        k for k, v in agent["rubric"].items() if not v
                                    ],
                                    "seconds": round(elapsed, 2),
                                }
                            ),
                            flush=True,
                        )
                        if root.error_code in {"proxy_auth", "proxy_quota"}:
                            blocked = True
                            break
                    if blocked:
                        break
                if blocked:
                    break
            telemetry.flush()
    except Exception as exc:
        report["error"] = {
            "type": type(exc).__name__,
            "code": getattr(exc, "code", "evaluation_failed"),
        }
        raise
    finally:
        report["finished_at"] = utc_now().isoformat()
        save()
        telemetry.close()
    print(json.dumps(report["summary"], indent=2))
    if not report["summary"]["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

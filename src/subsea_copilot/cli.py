"""Local monitoring commands; live inference is an explicit operation."""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from .budgets import MODEL_TIMEOUT_SECONDS
from .config import Settings


def runtime_directory() -> Path:
    configured = os.environ.get("SUBSEA_RUNTIME_DIR")
    if configured:
        return Path(configured)
    return Path(os.environ["LOCALAPPDATA"]) / "SubseaCopilot"


def build_console() -> None:
    node = shutil.which("node")
    if node is None:
        raise ValueError("Node.js is required to build the dashboard before starting it.")
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [node, str(root / "scripts" / "build-console.cjs")], cwd=root, check=False,
    )
    if result.returncode:
        raise ValueError("Console build failed; the dashboard was not started.")


def provider_check(model_id: str | None = None) -> dict[str, object]:
    from .llm.copilot_cli import CopilotCLIChatModel

    model = CopilotCLIChatModel(runtime_dir=runtime_directory(), model_id=model_id)
    message = model.invoke(
        [
            SystemMessage(
                content=(
                    "This is one synthetic availability check. No tools or data access "
                    "are requested. Respond with the exact outer JSON envelope "
                    '{"kind":"final","value":{"outcome":"available"}}'
                )
            ),
            HumanMessage(content="Confirm the synthetic-only transport probe."),
        ],
        timeout=MODEL_TIMEOUT_SECONDS,
    )
    if not isinstance(message.content, str):
        raise ValueError("Provider probe did not return text")
    parsed = json.loads(message.content)
    if parsed != {"outcome": "available"}:
        raise ValueError("Provider probe returned an unexpected final payload")
    return {"outcome": "available", "mode": "live", "metadata": message.response_metadata}


def main() -> None:
    parser = argparse.ArgumentParser(prog="subsea")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("migrate", help="Create independent PostgreSQL roles/schema")
    serve = subparsers.add_parser("serve", help="Run console and independent worker threads")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8086)
    recorded = subparsers.add_parser(
        "serve-recorded", help="Read-only, no-worker QA console for an explicit recorded tenant"
    )
    recorded.add_argument("--tenant", required=True)
    recorded.add_argument("--host", default="127.0.0.1")
    recorded.add_argument("--port", type=int, default=8087)
    probe = subparsers.add_parser("provider-check", help="One explicit synthetic live call")
    probe.add_argument("--mode", choices=["live"], required=True)
    probe.add_argument("--model")
    knowledge = subparsers.add_parser("knowledge", help="Validate and preview advisory knowledge")
    knowledge.add_argument("--path", type=Path)
    knowledge.add_argument("--site", default="northsea")
    knowledge.add_argument("--pack-version", default="pressure-pack-v4-extended")
    generate = subparsers.add_parser("generate", help="Write original synthetic raw data")
    generate.add_argument("--seed", type=int, default=2026)
    generate.add_argument(
        "--scenario", choices=["S1", "S2", "S3", "S4", "S5", "S6", "S7"], default="S1"
    )
    generate.add_argument("--output", type=Path, default=Path("runtime") / "generated")
    golden = subparsers.add_parser(
        "golden", help="Generate verified golden datasets or explicitly qualify fresh agents/judge"
    )
    golden.add_argument(
        "--stage", choices=[
            "manifest", "qualify", "audit", "judge-recorded", "retry-case", "qualify-retry",
            "public-receipts",
        ],
        default="manifest",
    )
    golden.add_argument("--mode", choices=["scripted", "live"], default="scripted")
    golden.add_argument("--agent-model", default="gpt-6.1-sol")
    golden.add_argument("--judge-model", default="gpt-6.1-sol")
    golden.add_argument("--case", choices=["G1", "G2", "G3"], default="G3")
    golden.add_argument("--source-output", type=Path)
    golden.add_argument("--retry-output", type=Path)
    golden.add_argument("--output", type=Path, default=Path("eval") / "results" / "golden")
    ingest = subparsers.add_parser("ingest", help="Create a paused named synthetic replay")
    reference = subparsers.add_parser(
        "reference-evaluation", help="Live agents, truth-blind mapping and deterministic scores"
    )
    reference.add_argument("--seed", type=int, default=20261108)
    reference.add_argument("--split", choices=["development", "held_out"], required=True)
    reference.add_argument("--agent-model", default="gpt-6.1-sol")
    reference.add_argument("--evaluator-model", default="gpt-6.1-terra")
    reference.add_argument("--output", type=Path, required=True)
    spatial = subparsers.add_parser(
        "spatial-evaluation", help="S7-scale temporal recordings with real agent checkpoints"
    )
    spatial.add_argument("--seed", type=int, default=20261109)
    spatial.add_argument("--split", choices=["development", "held_out"], required=True)
    spatial.add_argument("--agent-model", default="gpt-6.1-sol")
    spatial.add_argument("--evaluator-model", default="gpt-6.1-terra")
    spatial.add_argument("--output", type=Path, required=True)
    spatial.add_argument("--suite", choices=["current", "recovery", "non_leak"], default="current")
    spatial.add_argument(
        "--no-publish", action="store_true",
        help="Run independently without replacing the active dashboard evaluation",
    )
    agent_eval = subparsers.add_parser(
        "agent-evaluation", help="Reference-backed answers and six-dimensional quality review"
    )
    agent_eval.add_argument("--split", choices=["development", "held_out", "all"],
                            default="held_out")
    agent_eval.add_argument("--agent-model", default="gpt-6.1-sol")
    agent_eval.add_argument("--judge-model", default="gpt-6.1-sol")
    agent_eval.add_argument("--output", type=Path, required=True)
    agent_audit = subparsers.add_parser(
        "agent-audit", help="Private read-only audit; never publishes customer reliability scores"
    )
    agent_audit.add_argument(
        "--suite", choices=["current", "recovery", "non_leak"], default="current"
    )
    agent_audit.add_argument("--output", type=Path, required=True)
    ingest.add_argument("--fixture-set", choices=["interview"], default="interview")
    ingest.add_argument(
        "--scenario", choices=["S1", "S2", "S3", "S4", "S5", "S6", "S7"], default="S1"
    )
    ingest.add_argument("--mode", choices=["scripted", "live"], default="scripted")
    evaluate = subparsers.add_parser("evaluate", help="Run frozen synthetic qualification")
    evaluate.add_argument(
        "--suite",
        choices=["diagnostics", "agents", "qualification", "knowledge"],
        default="diagnostics",
    )
    evaluate.add_argument("--mode", choices=["scripted", "live"], default="scripted")
    evaluate.add_argument("--repetitions", type=int, choices=[1, 2, 3], default=3)
    evaluate.add_argument("--output", type=Path, default=Path("eval") / "results")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        if args.command == "serve-recorded":
            from dataclasses import replace

            import uvicorn

            from .recorded_console import create_recorded_console

            if args.host not in ("127.0.0.1", "localhost", "::1"):
                parser.error("Recorded QA console may bind only to loopback")
            build_console()
            print(f"Recorded investigation console: http://{args.host}:{args.port}")
            uvicorn.run(
                create_recorded_console(
                    replace(Settings.from_env(), host=args.host, port=args.port), args.tenant,
                ),
                host=args.host, port=args.port,
            )
        elif args.command == "golden":
            if args.stage == "manifest":
                from .golden_data import write_manifest

                report = write_manifest(args.output)
            elif args.stage == "audit":
                from .golden_evaluation import audit_recorded_operator_outputs

                report = audit_recorded_operator_outputs(args.output)
            elif args.stage == "public-receipts":
                from .golden_publication import publish_recorded_receipts

                report = publish_recorded_receipts(args.output)
            elif args.stage == "judge-recorded":
                if args.mode != "live":
                    parser.error("Recorded-report judging requires explicit --mode live")
                from .golden_evaluation import judge_recorded_reports

                report = judge_recorded_reports(args.output, judge_model=args.judge_model)
            elif args.stage == "qualify-retry":
                if args.mode != "live" or args.source_output is None or args.retry_output is None:
                    parser.error("Retry qualification needs live mode and both source outputs")
                from .golden_evaluation import qualify_recorded_retry

                report = qualify_recorded_retry(
                    args.source_output, args.retry_output, args.output,
                    judge_model=args.judge_model,
                )
            elif args.stage == "retry-case":
                if args.mode != "live" or args.source_output is None:
                    parser.error("Focused retry needs --mode live and --source-output")
                from .golden_evaluation import retry_recorded_case

                report = retry_recorded_case(args.source_output, args.output, args.case)
            else:
                from .golden_evaluation import qualify_golden

                report = qualify_golden(
                    args.mode, args.output,
                    agent_model=args.agent_model, judge_model=args.judge_model,
                )
            print(json.dumps(report, indent=2))
            if not report.get("passed"):
                raise SystemExit(1)
        elif args.command == "agent-evaluation":
            from .agent_answer_quality import run_answer_quality_evaluation

            report = run_answer_quality_evaluation(
                args.output, split=args.split, model_id=args.agent_model,
                judge_model_id=args.judge_model,
            )
            print(json.dumps({"run_id": report["run_id"], "metrics": report["metrics"],
                              "answer_quality": report["answer_quality"]["metrics"]}))
        elif args.command == "agent-audit":
            from .temporal_evaluation import run_agent_evaluation

            report = run_agent_evaluation(args.output, suite=args.suite)
            print(json.dumps({
                "run_id": report["run_id"], "agent_process": report["agent_process"],
            }))
        elif args.command == "spatial-evaluation":
            from .spatial_evaluation import run_spatial_evaluation

            report = run_spatial_evaluation(
                args.output, seed=args.seed, split=args.split,
                agent_model=args.agent_model, evaluator_model=args.evaluator_model,
                suite=args.suite, publish=not args.no_publish,
            )
            print(json.dumps({"run_id": report["run_id"], "metrics": report["metrics"]}))
            if not report["metrics"]["target_met"]:
                raise SystemExit(1)
        elif args.command == "reference-evaluation":
            from .reference_evaluation import run_reference_evaluation

            report = run_reference_evaluation(
                args.output, seed=args.seed, split=args.split,
                agent_model=args.agent_model, evaluator_model=args.evaluator_model,
            )
            print(json.dumps({
                "run_id": report["run_id"], "status": report["status"],
                "metrics": report["metrics"],
            }, indent=2))
            if not report["metrics"]["target_met"]:
                raise SystemExit(1)
        elif args.command == "knowledge":
            from .contracts import utc_now
            from .knowledge import DEFAULT_KNOWLEDGE_PATH, load_knowledge, select_knowledge

            packet = select_knowledge(
                load_knowledge(args.path or DEFAULT_KNOWLEDGE_PATH),
                site_id=args.site,
                pack_version=args.pack_version,
                as_of=utc_now(),
            )
            print(packet.model_dump_json(indent=2))
        elif args.command == "provider-check":
            from .store import Store

            probe_result = provider_check(args.model)
            settings = Settings.from_env()
            with Store(settings.database_dsn, settings.tenant_id, settings.site_id) as store:
                store.clear_provider_failure()
            print(json.dumps(probe_result, indent=2))
        elif args.command == "generate":
            from .synthetic import generate_scenario

            data = generate_scenario(args.scenario, args.seed)
            args.output.mkdir(parents=True, exist_ok=True)
            destination = args.output / f"{args.scenario}-{args.seed}.jsonl"
            with destination.open("w", encoding="utf-8") as stream:
                for row in data.records:
                    stream.write(row.model_dump_json() + "\n")
            print(f"Synthetic raw records: {destination}")
        elif args.command == "migrate":
            from .runtime.checkpointer import postgres_checkpointer
            from .store import migrate

            settings = Settings.from_env()
            migrate(
                settings.admin_dsn,
                settings.app_password,
                settings.tools_password,
                settings.checkpoint_password,
            )
            with postgres_checkpointer(settings.checkpoint_dsn, setup=True):
                pass
            print("Independent PostgreSQL schema, scoped roles and graph checkpoints are ready.")
        elif args.command == "serve":
            import uvicorn

            from .api import create_app

            if args.host not in ("127.0.0.1", "localhost", "::1"):
                parser.error("This installation may bind only to loopback")
            build_console()
            print(f"Read-only pressure-monitoring console: http://{args.host}:{args.port}")
            uvicorn.run(create_app(Settings.from_env()), host=args.host, port=args.port)
        elif args.command == "ingest":
            from .contracts import ReplaySession
            from .store import Store
            from .synthetic import SOURCE_VERSION, generate_scenario

            settings = Settings.from_env()
            dataset = generate_scenario(args.scenario)
            store = Store(settings.database_dsn, settings.tenant_id, settings.site_id)
            try:
                import uuid

                result = store.create_replay(
                    ReplaySession(
                        id="replay-" + uuid.uuid4().hex,
                        scenario=args.scenario,
                        source_version=SOURCE_VERSION,
                        mode=args.mode,
                        epoch=dataset.epoch,
                    )
                )
                print(f"Paused synthetic replay: {result.id}")
            finally:
                store.close()
        else:
            from .qualification import run_qualification

            report = run_qualification(args.suite, args.mode, args.output, args.repetitions)
            print(json.dumps(report, indent=2))
            if not report.get("passed"):
                raise SystemExit(1)
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

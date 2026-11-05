"""Independent local demo commands; live inference is an explicit operation."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from .config import Settings


def runtime_directory() -> Path:
    configured = os.environ.get("SUBSEA_RUNTIME_DIR")
    if configured:
        return Path(configured)
    return Path(os.environ["LOCALAPPDATA"]) / "SubseaCopilot"


def provider_check(model_id: str | None = None) -> dict[str, object]:
    from .llm.copilot_cli import CopilotCLIChatModel

    model = CopilotCLIChatModel(runtime_dir=runtime_directory(), model_id=model_id)
    message = model.invoke(
        [
            SystemMessage(
                content=(
                    "This is one synthetic availability check. No tools or data access "
                    "are requested. Respond with the exact outer JSON envelope "
                    '{"kind":"final","value":"{\\"outcome\\":\\"available\\"}"}'
                )
            ),
            HumanMessage(content="Confirm the synthetic-only transport probe."),
        ],
        timeout=60,
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
    probe = subparsers.add_parser("provider-check", help="One explicit synthetic live call")
    probe.add_argument("--mode", choices=["live"], required=True)
    probe.add_argument("--model")
    generate = subparsers.add_parser("generate", help="Write original synthetic raw data")
    generate.add_argument("--seed", type=int, default=2026)
    generate.add_argument("--scenario", choices=["S1", "S2", "S3", "S4", "S5", "S6"], default="S1")
    generate.add_argument("--output", type=Path, default=Path("runtime") / "generated")
    ingest = subparsers.add_parser("ingest", help="Create a paused named synthetic replay")
    ingest.add_argument("--fixture-set", choices=["interview"], default="interview")
    ingest.add_argument("--scenario", choices=["S1", "S2", "S3", "S4", "S5", "S6"], default="S1")
    ingest.add_argument("--mode", choices=["scripted", "live"], default="scripted")
    evaluate = subparsers.add_parser("evaluate", help="Run frozen synthetic qualification")
    evaluate.add_argument(
        "--suite", choices=["diagnostics", "agents", "qualification"], default="diagnostics"
    )
    evaluate.add_argument("--mode", choices=["scripted", "live"], default="scripted")
    evaluate.add_argument("--repetitions", type=int, choices=[1, 2, 3], default=3)
    evaluate.add_argument("--output", type=Path, default=Path("eval") / "results")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        if args.command == "provider-check":
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
                parser.error("This demo may bind only to loopback")
            print(f"Read-only synthetic console: http://{args.host}:{args.port}")
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

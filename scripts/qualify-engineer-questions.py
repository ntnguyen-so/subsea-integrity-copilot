"""Exercise question-specific interpretation, not detection accuracy or business ROI."""

import argparse
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from subsea_copilot.config import Settings
from subsea_copilot.contracts import AgentResult, ReplaySession
from subsea_copilot.diagnostics import analyze_window
from subsea_copilot.ingest import normalize_records
from subsea_copilot.llm.copilot_cli import CopilotCLIChatModel
from subsea_copilot.qualification import model_receipts
from subsea_copilot.runtime.checkpointer import postgres_checkpointer
from subsea_copilot.runtime.scripted import ScriptedChatModel
from subsea_copilot.runtime.workflow import AgentService
from subsea_copilot.store import Store
from subsea_copilot.synthetic import SOURCE_VERSION, generate_scenario
from subsea_copilot.telemetry import Telemetry

QUESTIONS = {
    "S4": (
        "Could a valve change explain this pressure pattern? "
        "What should the engineer verify before accepting that root cause?"
    ),
    "S2": (
        "Is there evidence of sensor drift, or are we just assuming that every "
        "anomaly is a faulty sensor?"
    ),
    "S1": "Why is the proposed inspection area a range rather than an exact leak position?",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["scripted", "live"], default="scripted")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--inject-unsupported-draft",
        action="store_true",
        help="Synthetic S4 attack: inject a false cited paragraph before the real critic",
    )
    args = parser.parse_args()
    settings = Settings.from_env()
    rows = []
    telemetry = Telemetry(runtime_dir=settings.runtime_dir)
    try:
        with (
            Store(
                settings.database_dsn,
                tenant_id="engineer-" + uuid4().hex,
                tools_dsn=settings.tools_dsn,
                qualification=True,
            ) as store,
            postgres_checkpointer(settings.checkpoint_dsn) as saver,
        ):

            class QualificationService(AgentService):
                def _graph(self, task, snapshot, phase, candidate=None, criticism=None):
                    parsed, current = super()._graph(
                        task, snapshot, phase, candidate=candidate, criticism=criticism
                    )
                    if (
                        args.inject_unsupported_draft
                        and task.role == "operator_response"
                        and phase == "answer"
                    ):
                        draft = AgentResult.model_validate(parsed)
                        draft.interpretation.answer.text = (
                            "An independent inspection photograph confirms a pipe-wall crack."
                        )
                        draft.interpretation.answer.references = ["OP-VALVE-001"]
                        parsed = draft.model_dump(mode="json")
                    return parsed, current

            service = QualificationService(
                store,
                lambda role, mode: (
                    CopilotCLIChatModel(runtime_dir=settings.runtime_dir, model_id="gpt-6.1-sol")
                    if mode == "live"
                    else ScriptedChatModel(role=role)
                ),
                saver,
                telemetry,
            )
            for scenario, question in QUESTIONS.items():
                if args.inject_unsupported_draft and scenario != "S4":
                    continue
                source = generate_scenario(scenario, duration_seconds=180)
                replay = store.create_replay(
                    ReplaySession(
                        id="engineer-" + uuid4().hex,
                        tenant_id=store.tenant_id,
                        scenario=scenario,
                        source_version=SOURCE_VERSION,
                        mode=args.mode,
                        epoch=source.epoch,
                        clock_seconds=185,
                    )
                )
                observations = normalize_records(
                    [
                        row
                        for row in source.records
                        if datetime.fromisoformat(row.received_at.replace("Z", "+00:00"))
                        <= source.epoch + timedelta(seconds=185)
                    ],
                    source.pack,
                )
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
                        tenant_id=store.tenant_id,
                    )
                )
                started = time.monotonic()
                root = service.submit_question(replay, snapshot, question, "engineer-question")
                while root.state not in {"SUCCEEDED", "ABSTAINED", "FAILED", "CANCELLED"}:
                    if time.monotonic() - started > 330:
                        raise RuntimeError("Engineer question did not terminate within bounds")
                    if not service.run_once():
                        time.sleep(0.05)
                    root = store.get_task(root.id)
                tasks = [t for t in store.list_tasks(replay.id) if t.root_id == root.id]
                interpretation = root.result.interpretation if root.result else None
                accepted = root.state in {"SUCCEEDED", "ABSTAINED"} and interpretation is not None
                if args.inject_unsupported_draft:
                    accepted = (
                        accepted
                        and root.interpretation_review is not None
                        and [r.assessment.decision for r in root.interpretation_review.rounds]
                        == ["revise", "accept"]
                        and "photograph" not in root.answer.lower()
                    )
                rows.append(
                    {
                        "scenario": scenario,
                        "question": question,
                        "root_id": root.id,
                        "snapshot_id": snapshot.id,
                        "state": root.state,
                        "error_code": root.error_code,
                        "accepted": accepted,
                        "interpretation": interpretation.model_dump(mode="json")
                        if interpretation
                        else None,
                        "review": root.interpretation_review.model_dump(mode="json")
                        if root.interpretation_review
                        else None,
                        "answer": root.answer,
                        "elapsed_seconds": time.monotonic() - started,
                        "model_receipts": model_receipts(store, [t.id for t in tasks]),
                    }
                )
                if root.state == "FAILED":
                    break
            telemetry.flush()
    finally:
        telemetry.close()
    report = {
        "mode": args.mode,
        "response_protocol": "engineer-v2",
        "injected_unsupported_draft": args.inject_unsupported_draft,
        "passed": len(rows) == (1 if args.inject_unsupported_draft else len(QUESTIONS))
        and all(row["accepted"] for row in rows),
        "results": rows,
        "limitations": [
            "SCRIPTED is an offline contract example, not genuine interpretation.",
            "Separate same-model critic; exact quotes and paragraph coverage checked by code.",
            "Probabilistic semantic review cannot guarantee entailment or zero hallucinations.",
            "Model-written RCA context requires engineer review and is not a confirmed cause.",
            "These questions demonstrate functionality, not effort savings or superiority.",
            "Optional attack changes a new provisional draft, not an accepted answer or source.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "answers": len(rows), "mode": args.mode}))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

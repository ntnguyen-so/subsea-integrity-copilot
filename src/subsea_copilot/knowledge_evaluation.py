"""Paired synthetic knowledge ablation on one pinned S7 snapshot.

Both arms receive identical arrived measurements at endpoint 110/clock 115. The legacy
comparator removes only the knowledge packet; production AgentService supplies the
enabled arm. Persisted roots, casefiles, reads and comparisons provide utility evidence,
while input hashes check pairing. Scripted success checks contracts, not reasoning;
one seed/window per arm cannot establish causal benefit, field accuracy or time savings.
"""

import time
from datetime import timedelta
from uuid import uuid4

from langchain_core.language_models import BaseChatModel
from pydantic import JsonValue, TypeAdapter

from .budgets import ROOT_WATCHDOG_SECONDS, WORKER_POLL_LIMIT
from .casefile import build_casefile
from .config import Settings
from .contracts import AgentRole, Mode, ReplaySession, WindowSnapshot
from .diagnostics import analyze_window
from .ingest import normalize_records
from .knowledge import KnowledgePacket
from .llm.copilot_cli import CopilotCLIChatModel
from .runtime.checkpointer import postgres_checkpointer
from .runtime.gateway import ToolGateway
from .runtime.scripted import ScriptedChatModel
from .runtime.workflow import AgentService
from .store import Store
from .synthetic import SOURCE_VERSION, generate_scenario
from .telemetry import Telemetry


class KnowledgeOffService(AgentService):
    """Evaluation-only legacy comparator, never a customer-facing mode."""

    def _knowledge_for(self, snapshot: WindowSnapshot) -> KnowledgePacket | None:
        return None


def qualify_knowledge(mode: Mode) -> dict[str, JsonValue]:
    """Run bounded roots for both arms and record acceptance separately from utility checks.

    Passing requires matching input hashes and accepted roots. Cited operating/gateway
    records and a P5 comparison with absolute change >=0.2 bar are descriptive utility
    checks, not additional accuracy estimates or independent expert judgements.
    """
    settings = Settings.from_env()
    tenant = "knowledge-eval-" + uuid4().hex[:12]
    telemetry = Telemetry(runtime_dir=settings.runtime_dir)

    def factory(role: AgentRole, selected_mode: Mode) -> BaseChatModel:
        if selected_mode == "scripted":
            return ScriptedChatModel(role=role)
        return CopilotCLIChatModel(runtime_dir=settings.runtime_dir, model_id="gpt-6.1-sol")

    arms: list[dict[str, JsonValue]] = []
    try:
        with (
            Store(
                settings.database_dsn,
                tenant,
                settings.site_id,
                settings.tools_dsn,
                qualification=True,
            ) as store,
            postgres_checkpointer(settings.checkpoint_dsn) as saver,
        ):
            source = generate_scenario("S7", 2026, site_id=settings.site_id)
            rows = [
                row
                for row in normalize_records(source.records, source.pack)
                if row.received_at <= source.epoch + timedelta(seconds=115)
            ]
            baseline = normalize_records(source.baseline, source.pack)
            for enabled in (False, True):
                service = (AgentService if enabled else KnowledgeOffService)(
                    store, factory, saver, telemetry
                )
                replay = store.create_replay(
                    ReplaySession(
                        id="knowledge-" + uuid4().hex,
                        tenant_id=tenant,
                        site_id=settings.site_id,
                        scenario="S7",
                        source_version=SOURCE_VERSION,
                        mode=mode,
                        clock_seconds=115,
                        epoch=source.epoch,
                    )
                )
                store.save_observations(replay.id, rows)
                snapshot = store.save_window(
                    analyze_window(
                        source.pack,
                        baseline,
                        rows,
                        replay.id,
                        110,
                        115,
                        source.epoch,
                        tenant_id=tenant,
                    )
                )
                started = time.monotonic()
                root = service.submit_question(
                    replay,
                    snapshot,
                    "Leak or faulty sensors? Explain the competing pressure regions, "
                    "where to inspect and what remains unknown.",
                    idempotency_key="knowledge-ablation",
                )
                for _ in range(WORKER_POLL_LIMIT):
                    if root.state in {"SUCCEEDED", "ABSTAINED", "FAILED", "CANCELLED"}:
                        break
                    if time.monotonic() - started > ROOT_WATCHDOG_SECONDS:
                        raise RuntimeError("Knowledge ablation exceeded its bounded root deadline.")
                    progressed = service.run_once()
                    root = store.get_task(root.id)
                    if not progressed:
                        time.sleep(0.05)
                tasks = store.list_tasks(replay.id)
                accepted = root.state in {"SUCCEEDED", "ABSTAINED"}
                casefile = None
                if accepted:
                    dependencies = ToolGateway(store, root, snapshot, telemetry).dependencies()
                    receipts = [
                        {"task_id": dependency.id, **receipt}
                        for dependency in dependencies
                        for receipt in store.tool_receipts(dependency.id)
                        if str(receipt["name"]).startswith("history.")
                    ]
                    casefile = build_casefile(root, snapshot, dependencies, receipts)
                cited = {
                    str(item.document["id"])
                    for item in (casefile.sources if casefile else [])
                    if item.use == "cited"
                }
                comparisons = casefile.comparisons if casefile else []
                meaningful_p5 = any(
                    isinstance(sensors := comparison.get("sensors"), list)
                    and any(
                        isinstance(sensor, dict)
                        and str(sensor.get("sensor_id", "")).startswith("P5-")
                        and isinstance(change := sensor.get("change_bar"), (int, float))
                        and abs(change) >= 0.2
                        for sensor in sensors
                    )
                    for comparison in comparisons
                )
                arms.append(
                    TypeAdapter(dict[str, JsonValue]).validate_python(
                        {
                            "knowledge_enabled": enabled,
                            "input_hash": snapshot.input_hash,
                            "numerical_hypothesis": snapshot.event.hypothesis,
                            "state": root.state,
                            "error_code": root.error_code,
                            "contract_qualified": accepted,
                            "measured_elapsed_seconds": time.monotonic() - started,
                            "model_calls": sum(task.model_calls for task in tasks),
                            "tool_calls": sum(task.tool_calls for task in tasks),
                            "casefile": casefile.model_dump(mode="json") if casefile else None,
                            "root": root.model_dump(mode="json"),
                            "context_utility_checks": {
                                "current_operating_record_cited": "OP-P2-EXTENDED-001" in cited,
                                "current_gateway_record_cited": "MAINT-P7-GW-002" in cited,
                                "meaningful_p5_comparison": meaningful_p5,
                            },
                        }
                    )
                )
                if service.health().get("available") is False:
                    break
        matching = len(arms) == 2 and arms[0]["input_hash"] == arms[1]["input_hash"]
        return {
            "passed": matching and all(arm["contract_qualified"] is True for arm in arms),
            "mode": mode,
            "matching_input_hashes": matching,
            "arms": list(arms),
            "inference_retries": 0,
            "limitations": [
                "One synthetic seed/window and run per arm; no causal or accuracy estimate.",
                "SCRIPTED checks contracts, not actual knowledge reasoning benefit.",
                "Utility checks verify reads/comparisons, not complete RCA correctness.",
                "Same-model critic acceptance is not independent pipeline-expert validation.",
                "No measured engineer-time savings; monetary provider cost is unknown.",
                "A strong numerical and contextual workflow may match either arm.",
            ],
        }
    finally:
        telemetry.close()

"""Frozen synthetic qualification; results are measurements, not field reliability."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import JsonValue, TypeAdapter

from .budgets import ROOT_WATCHDOG_SECONDS, WORKER_POLL_LIMIT
from .config import Settings
from .contracts import AgentRole, Mode, ReplaySession, utc_now
from .diagnostics import analyze_window
from .history_evaluation import history_answer_supported
from .ingest import normalize_records
from .llm.copilot_cli import CopilotCLIChatModel
from .runtime.baseline import run_single_agent_baseline
from .runtime.checkpointer import postgres_checkpointer
from .runtime.scripted import ScriptedChatModel
from .runtime.workflow import AgentService
from .store import Store
from .synthetic import CUSTOMER_QUESTIONS, SOURCE_VERSION, generate_scenario
from .telemetry import Telemetry

PRIMARY_QUESTIONS = CUSTOMER_QUESTIONS
TERMINALS = {"SUCCEEDED", "ABSTAINED", "FAILED", "CANCELLED"}
JSON_ADAPTER = TypeAdapter[JsonValue](JsonValue)
MODEL_METADATA_KEYS = (
    "mode",
    "phase",
    "requested_model",
    "observed_model",
    "model_identity_source",
    "cli_version",
    "cli_version_source",
    "usage",
    "duration_ms",
    "error",
    "request_id",
)


def qualification_model_factory(
    settings: Settings, model_id: str = "gpt-6.1-sol",
) -> Callable[[AgentRole, Mode], BaseChatModel]:
    """Shared transport/role factory for qualification; no alternative agent stack."""
    def factory(role: AgentRole, selected_mode: Mode) -> BaseChatModel:
        if selected_mode == "scripted":
            return ScriptedChatModel(role=role)
        return CopilotCLIChatModel(runtime_dir=settings.runtime_dir, model_id=model_id)

    return factory


def model_receipts(store: Store, task_ids: list[str]) -> list[JsonValue]:
    return [
        {key: receipt.get(key) for key in MODEL_METADATA_KEYS}
        for task_id in task_ids
        for receipt in store.list_model_calls(task_id)
    ]


def qualify_agents(mode: Mode, repetitions: int = 3) -> dict[str, JsonValue]:
    if not 1 <= repetitions <= 3:
        raise ValueError("Agent qualification requires one to three repetitions")
    settings = Settings.from_env()
    tenant = "qualification-" + uuid.uuid4().hex[:12]
    store = Store(
        settings.database_dsn,
        tenant_id=tenant,
        site_id=settings.site_id,
        tools_dsn=settings.tools_dsn,
        qualification=True,
    )
    telemetry = Telemetry(runtime_dir=settings.runtime_dir)
    results: list[JsonValue] = []
    expected = {
        "S1": "suspected_leak",
        "S2": "sensor_or_telemetry_issue",
        "S4": "insufficient_evidence",
        "S5": "insufficient_evidence",
    }
    provider_blocked: str | None = None
    comparison: dict[str, JsonValue] | None = None
    trace_ids: list[str] = []
    measured_models: set[str] = set()
    measured_versions: set[str] = set()

    factory = qualification_model_factory(settings)

    try:
        with postgres_checkpointer(settings.checkpoint_dsn) as checkpointer:
            service = AgentService(store, factory, checkpointer, telemetry)
            for scenario in expected:
                source = generate_scenario(scenario, 2026, site_id=settings.site_id)
                replay = store.create_replay(
                    ReplaySession(
                        id="replay-" + uuid.uuid4().hex,
                        tenant_id=tenant,
                        site_id=settings.site_id,
                        scenario=scenario,
                        source_version=SOURCE_VERSION,
                        mode=mode,
                        clock_seconds=185,
                        epoch=source.epoch,
                    )
                )
                # The source adapter releases arrivals. Diagnostics receive no scenario/label.
                released = [
                    row
                    for row in source.records
                    if (
                        datetime.fromisoformat(row.received_at.replace("Z", "+00:00"))
                        - source.epoch
                    ).total_seconds()
                    <= 185
                ]
                canonical = normalize_records(released, source.pack)
                baseline = normalize_records(source.baseline, source.pack)
                store.save_observations(replay.id, canonical)
                snapshot = store.save_window(
                    analyze_window(
                        source.pack,
                        baseline,
                        canonical,
                        generation_id=replay.id,
                        end_seconds=180,
                        clock_seconds=185,
                        epoch=source.epoch,
                        tenant_id=tenant,
                    )
                )
                for repetition in range(repetitions):
                    for index, question in enumerate(PRIMARY_QUESTIONS):
                        started = time.monotonic()
                        root = service.submit_question(
                            replay,
                            snapshot,
                            question,
                            idempotency_key=f"cohort:{repetition}:{index}",
                        )
                        iterations = 0
                        while root.state not in TERMINALS:
                            if (
                                time.monotonic() - started > ROOT_WATCHDOG_SECONDS
                                or iterations >= WORKER_POLL_LIMIT
                            ):
                                raise RuntimeError(
                                    "Qualification root did not terminate within bounds"
                                )
                            progressed = service.run_once()
                            iterations += 1
                            root = store.get_task(root.id)
                            if not progressed:
                                time.sleep(0.05)
                        tasks = [
                            task for task in store.list_tasks(replay.id) if task.root_id == root.id
                        ]
                        claims = [
                            snapshot.claims[ref]
                            for ref in (root.result.claim_refs if root.result else [])
                            if ref in snapshot.claims
                        ]
                        selected_kinds = {claim.kind for claim in claims}
                        accepted = root.state in ("SUCCEEDED", "ABSTAINED")
                        supported = snapshot.event.hypothesis == expected[scenario]
                        supported = supported and history_answer_supported(
                            scenario, root.result, root.state
                        )
                        if index == 0:
                            supported = supported and (
                                "hypothesis" in selected_kinds or root.state == "ABSTAINED"
                            )
                        elif index == 1:
                            supported = supported and (
                                "location" in selected_kinds
                                if snapshot.event.eligible_location
                                and snapshot.location
                                and snapshot.location.status == "located"
                                else "location" not in selected_kinds
                            )
                        else:
                            supported = supported and bool(
                                selected_kinds & {"coverage", "sensor_health"}
                            )
                        error = root.error_code
                        if not trace_ids and accepted:
                            metadata = store.latest_task_trace(root.id)
                            if metadata and isinstance(metadata.get("trace_id"), str):
                                trace_ids.append(str(metadata["trace_id"]))
                        selected_refs: list[JsonValue] = (
                            list(root.result.claim_refs) if root.result else []
                        )
                        receipts = model_receipts(store, [task.id for task in tasks])
                        for receipt in receipts:
                            if isinstance(receipt, dict):
                                if isinstance(receipt.get("observed_model"), str):
                                    measured_models.add(str(receipt["observed_model"]))
                                if isinstance(receipt.get("cli_version"), str):
                                    measured_versions.add(str(receipt["cli_version"]))
                        results.append(
                            {
                                "scenario": scenario,
                                "question_index": index + 1,
                                "repetition": repetition + 1,
                                "root_id": root.id,
                                "snapshot_id": snapshot.id,
                                "state": root.state,
                                "accepted_correct": accepted and supported,
                                "legitimate_abstention": root.state == "ABSTAINED" and supported,
                                "error_code": error,
                                "elapsed_seconds": round(time.monotonic() - started, 3),
                                "roles": [task.role for task in tasks],
                                "child_count": len([task for task in tasks if task.parent_id]),
                                "model_calls": sum(task.model_calls for task in tasks),
                                "tool_calls": sum(task.tool_calls for task in tasks),
                                "specialist_model_calls": sum(
                                    task.model_calls for task in tasks if task.parent_id
                                ),
                                "claim_refs": selected_refs,
                                "history_version": root.history_version,
                                "investigation": root.result.investigation.model_dump(mode="json")
                                if root.result and root.result.investigation
                                else None,
                                "model_receipts": receipts,
                            }
                        )
                        if error in ("proxy_auth", "proxy_quota"):
                            provider_blocked = error
                            break
                    if provider_blocked:
                        break
                if provider_blocked:
                    break
                if scenario == "S1":
                    comparison = run_single_agent_baseline(
                        store,
                        snapshot,
                        mode,
                        factory,
                        telemetry,
                        question=PRIMARY_QUESTIONS[0],
                        checkpointer=checkpointer,
                    )
                    if comparison.get("error_code") in ("proxy_auth", "proxy_quota"):
                        provider_blocked = str(comparison["error_code"])
                        break
            telemetry.flush()
            trace_visible = False
            for _ in range(10):
                trace_visible = bool(trace_ids) and all(
                    telemetry.verify_trace(
                        trace_id, required_types=["agent", "generation", "tool", "guardrail"]
                    )
                    for trace_id in trace_ids
                )
                if trace_visible:
                    break
                time.sleep(2)
            return {
                "passed": len(results) == len(expected) * len(PRIMARY_QUESTIONS) * repetitions
                and all(isinstance(row, dict) and row["accepted_correct"] for row in results)
                and comparison is not None
                and comparison.get("check_accepted") is True
                and trace_visible,
                "mode": mode,
                "source_version": SOURCE_VERSION,
                "live_model_evidence": mode == "live" and bool(measured_models),
                "requested_model": "gpt-6.1-sol" if mode == "live" else None,
                "observed_models": list(sorted(measured_models)),
                "observed_cli_versions": list(sorted(measured_versions)),
                "qualification_tenant_id": tenant,
                "population": (
                    f"three questions x {repetitions} repetitions "
                    f"x {len(expected)} pinned snapshots"
                ),
                "questions": list(PRIMARY_QUESTIONS),
                "investigation_protocol": "bounded-history-v1",
                "generation_model_call_ceiling": 100,
                "cohort_maximum_model_calls": len(expected) * 100,
                "answer_count": len(results),
                "provider_blocked": provider_blocked,
                "results": results,
                "observability": JSON_ADAPTER.validate_python(telemetry.health()),
                "single_agent_comparison": comparison,
                "stored_trace_tree_verified": trace_visible,
                "verified_trace_ids": list(trace_ids),
                "monetary_inference_cost": None,
                "limitation": (
                    "Synthetic-only cohort; scripted runs are not live-model evidence. "
                    "Single-agent comparison is the numerical-only legacy policy, "
                    "not same-history evidence."
                ),
            }
    finally:
        telemetry.close()
        store.close()


def run_qualification(
    suite: Literal["diagnostics", "agents", "qualification", "knowledge"],
    mode: Mode,
    output: Path,
    repetitions: int = 3,
) -> dict[str, JsonValue]:
    report: dict[str, JsonValue] = {
        "created_at": utc_now().isoformat(),
        "suite": suite,
        "mode": mode,
    }
    if suite in ("diagnostics", "qualification"):
        from .evaluation import evaluate_diagnostics

        report["diagnostics"] = evaluate_diagnostics(seed_count=20)
    if suite in ("agents", "qualification"):
        report["agents"] = qualify_agents(mode, repetitions)
    if suite == "knowledge":
        from .knowledge_evaluation import qualify_knowledge

        report["knowledge"] = qualify_knowledge(mode)
    sections = [report[key] for key in ("diagnostics", "agents", "knowledge") if key in report]
    report["passed"] = all(
        isinstance(section, dict) and section.get("passed") is True for section in sections
    )
    output.mkdir(parents=True, exist_ok=True)
    destination = output / f"{suite}-{mode}-{utc_now():%Y%m%dT%H%M%SZ}.json"
    destination.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    report["artifact"] = str(destination)
    return report

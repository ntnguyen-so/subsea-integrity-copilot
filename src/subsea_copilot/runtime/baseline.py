"""CLI qualification only: one model task, no delegation and no production policy widening."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import timedelta
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from pydantic import JsonValue

from subsea_copilot.budgets import ROOT_DEADLINE_SECONDS, TASK_LEASE_SECONDS
from subsea_copilot.contracts import (
    AgentResult,
    AgentRole,
    AgentTask,
    Mode,
    WindowSnapshot,
    utc_now,
)
from subsea_copilot.prompts import prompt_manifest_sha256
from subsea_copilot.runtime.gateway import ToolGateway
from subsea_copilot.runtime.registry import tool_schemas
from subsea_copilot.runtime.workflow import AgentService
from subsea_copilot.validation import ValidationError, validate_grounded_result

if TYPE_CHECKING:
    from subsea_copilot.store import Store
    from subsea_copilot.telemetry import Telemetry

BASELINE_PURPOSE = "evaluate_single_agent_baseline"
BASELINE_TOOLS = frozenset(
    {
        "quality.coverage",
        "quality.sensor_patterns",
        "event.assess",
        "location.fit",
        "evidence.get",
    }
)
BASELINE_REQUIRED = frozenset({"quality.coverage", "quality.sensor_patterns", "event.assess"})
BASELINE_CLAIMS = frozenset({"coverage", "sensor_health", "hypothesis", "location", "limitation"})
DEFAULT_QUESTION = (
    "The alarms started together. Is this a possible leak or an instrumentation issue?"
)


def baseline_schemas() -> list[dict[str, Any]]:
    schemas = {}
    for role in ("sensor_quality", "event_diagnosis"):
        for schema in tool_schemas(role):
            name = schema["function"]["name"]
            if name in BASELINE_TOOLS:
                schemas[name] = schema
    return [schemas[name] for name in sorted(schemas)]


class _BaselineGateway(ToolGateway):
    def _authorize(self, name: str, arguments: dict[str, Any]) -> None:
        if self.task.purpose != BASELINE_PURPOSE or name not in BASELINE_TOOLS:
            raise ValidationError("baseline_authority", "Tool is outside the CLI baseline policy.")
        self._validate_scope(arguments)

    def _argument_schemas(self) -> dict[str, Any]:
        return {s["function"]["name"]: s["function"]["parameters"] for s in baseline_schemas()}

    def _read(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = super()._read(name, arguments)
        if name == "quality.coverage":
            result["metadata"] = [
                e.model_dump(mode="json")
                for e in self.snapshot.evidence.values()
                if e.kind == "sensor_metadata"
            ]
        return result


class _BaselineService(AgentService):
    baseline_task_id: str

    def _claim_task(self) -> AgentTask | None:
        return self.store.claim_task(
            self.owner, ttl_seconds=TASK_LEASE_SECONDS, task_id=self.baseline_task_id
        )

    def _gateway(self, task: AgentTask, snapshot: WindowSnapshot) -> ToolGateway:
        return _BaselineGateway(self.store, task, snapshot, self.telemetry)

    def _schemas(self, task: AgentTask) -> list[dict[str, Any]]:
        return baseline_schemas()

    def _prompt_name(self, task: AgentTask) -> str:
        return "baseline.md"

    def _context(self, task: AgentTask, snapshot: WindowSnapshot, phase: str) -> dict[str, Any]:
        context = super()._context(task, snapshot, phase)
        context.update(
            {
                "baseline": True,
                "compatible_tasks": [],
                "required_tools": sorted(BASELINE_REQUIRED),
            }
        )
        return context

    def _orchestrate(self, task: AgentTask, snapshot: WindowSnapshot) -> AgentTask:
        if (
            task.purpose != BASELINE_PURPOSE
            or task.parent_id
            or task.automatic
            or task.role != "operator_response"
        ):
            raise ValidationError("baseline_authority", "Only the declared manual baseline root.")
        return task

    def _accept(
        self,
        value: str,
        task: AgentTask,
        snapshot: WindowSnapshot,
        gateway: ToolGateway,
    ) -> AgentResult:
        receipts = cast(list[dict[str, Any]], self.store.tool_receipts(task.id))
        received = {r["name"] for r in receipts if not r.get("error")}
        if not BASELINE_REQUIRED <= received:
            raise ValidationError("required_receipts", "Baseline needs quality and event reads.")
        if not any(
            r["name"] == "quality.coverage"
            and not r.get("error")
            and (r.get("result") or {}).get("metadata")
            for r in receipts
        ):
            raise ValidationError("required_metadata", "Baseline needs pinned sensor metadata.")
        result = validate_grounded_result(
            value,
            task,
            snapshot,
            receipts,
            claim_kinds=BASELINE_CLAIMS,
        )
        required_limits = {
            code
            for r in receipts
            if not r.get("error")
            for code in (r.get("result") or {}).get("limitations", [])
        }
        if not required_limits <= set(result.limitations):
            raise ValidationError(
                "review_scope", "Baseline must retain bounded review limitations."
            )
        read_claims = {
            ref
            for r in receipts
            if not r.get("error")
            for ref in (r.get("result") or {}).get("claims", {})
        }
        if not set(result.claim_refs) <= read_claims:
            raise ValidationError("evidence_receipts", "Baseline must read each claimed finding.")
        return result


def run_single_agent_baseline(
    store: Store,
    snapshot: WindowSnapshot,
    mode: Mode,
    model_factory: Callable[[AgentRole, Mode], BaseChatModel],
    telemetry: Telemetry,
    *,
    question: str = DEFAULT_QUESTION,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> dict[str, JsonValue]:
    """Consume the explicitly declared baseline allowance and shared generation budget."""
    if not store.qualification:
        raise ValidationError("baseline_authority", "Baseline requires a CLI qualification store.")
    if not question.strip() or len(question) > 4000:
        raise ValidationError("question", "Baseline question must be bounded.")
    replay = store.get_replay(snapshot.generation_id)
    if replay.mode != mode or store.get_window(snapshot.id) != snapshot:
        raise ValidationError("scope", "Baseline must use persisted same-mode replay evidence.")
    identifier = "baseline-" + uuid4().hex
    task = AgentTask(
        id=identifier,
        root_id=identifier,
        tenant_id=snapshot.tenant_id,
        site_id=snapshot.site_id,
        generation_id=snapshot.generation_id,
        snapshot_id=snapshot.id,
        role="operator_response",
        purpose=BASELINE_PURPOSE,
        question=question,
        mode=mode,
        deadline=utc_now() + timedelta(seconds=ROOT_DEADLINE_SECONDS),
        plan=["answer"],
        idempotency_key=identifier,
        prompt_catalog_sha256=prompt_manifest_sha256(),
    )
    started = time.monotonic()
    task = store.create_task(task)
    service = _BaselineService(store, model_factory, checkpointer, telemetry)
    service.baseline_task_id = task.id
    service.run_once()
    finished = store.get_task(task.id)
    accepted = finished.state in {"SUCCEEDED", "ABSTAINED"}
    return {
        "task_id": finished.id,
        "snapshot_id": snapshot.id,
        "mode": mode,
        "population": "single model task with governed numerical tools",
        "state": finished.state,
        "check_accepted": accepted,
        "model_calls": finished.model_calls,
        "tool_calls": finished.tool_calls,
        "child_count": 0,
        "elapsed_seconds": time.monotonic() - started,
        "hypothesis": finished.result.hypothesis if finished.result else None,
        "claim_refs": list(finished.result.claim_refs) if finished.result else [],
        "outcome": finished.result.outcome if finished.result else None,
        "error_code": finished.error_code,
        "live_model_evidence": mode == "live" and accepted and finished.model_calls > 0,
    }

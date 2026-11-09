"""Durable serial business orchestration around the shared checkpointed graph.

Replay questions bind immutable snapshots, then a response root plans serial
quality -> diagnosis -> answer tasks or explicitly reuses compatible specialists.
PostgreSQL task leases/budgets govern business state; LangGraph checkpoints govern
conversation progress. Model/tool effects run outside graph nodes, with original
read receipts and provenance retained across worker restarts.

New questions use measurement-only LLM diagnosis and independently reviewed
engineer-v2 prose; archived legacy tasks retain numerical eligibility rules.
Neither model output, research guidance nor cached success is trusted without
the corresponding scope, receipt and result checks.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import psycopg
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command
from pydantic import BaseModel

from subsea_copilot.agent_evidence import measurement_snapshot
from subsea_copilot.budgets import (
    BUDGET_MULTIPLIER,
    FRESH_REFLECTION_LIMIT,
    GRAPH_RECURSION_LIMIT,
    HISTORY_DOCUMENT_LIMIT,
    HISTORY_RANGE_SECONDS,
    MODEL_TIMEOUT_SECONDS,
    REFLECTION_LIMIT,
    ROOT_DEADLINE_SECONDS,
    SCHEMA_REPAIR_LIMIT,
    TASK_LEASE_SECONDS,
)
from subsea_copilot.contracts import (
    AgentResult,
    AgentRole,
    AgentTask,
    GroundingAssessment,
    GroundingRound,
    InterpretationReview,
    Mode,
    ReplaySession,
    WindowSnapshot,
    content_hash,
    utc_now,
)
from subsea_copilot.grounding import (
    GroundingCheckBatch,
    InterpretationRevision,
    apply_revision,
    candidate_hash,
    critic_context,
    reusable_checks,
    source_texts,
    validate_assessment,
    validate_revision,
)
from subsea_copilot.investigation import history_reference_ids
from subsea_copilot.knowledge import KnowledgePacket, load_knowledge, select_knowledge
from subsea_copilot.prompts import load_prompt, prompt_manifest_sha256
from subsea_copilot.public_activity import ROLE_NAMES
from subsea_copilot.runtime.agent import (
    WorkPlan,
    build_graph,
    checked_plan_sources,
    model_tool_result,
    repair_model_messages,
    tool_messages,
)
from subsea_copilot.runtime.context import model_context
from subsea_copilot.runtime.diagnostics import transport_diagnostic, validation_diagnostic
from subsea_copilot.runtime.gateway import ToolGateway, context_sensors
from subsea_copilot.runtime.provenance import (
    BOUND_ENVELOPE,
    RUNTIME_ENVELOPE,
    harness_provenance,
)
from subsea_copilot.runtime.registry import LIMITATIONS, REGISTRY, role_policy, tool_schemas
from subsea_copilot.validation import (
    ValidationError,
    abstention_claim_allowed,
    bind_read_claim_evidence,
    compatible,
    dependency_limitations,
    investigation_facts_available,
    parse_json,
    quality_facts_available,
    question_requires_location,
    read_evidence_reference,
    render_result,
    validate_result,
)

if TYPE_CHECKING:
    from subsea_copilot.store import Store
    from subsea_copilot.telemetry import Telemetry

PROMPT_NAMES = {
    "sensor_quality": "quality.md",
    "event_diagnosis": "diagnosis.md",
    "operator_response": "response.md",
}
LOGGER = logging.getLogger(__name__)


class AgentService:
    """Bridge leased business tasks, checkpointed conversations and checked public reports."""
    def __init__(
        self,
        store: Store,
        model_factory: Callable[[AgentRole, Mode], BaseChatModel],
        checkpointer: BaseCheckpointSaver[Any] | None,
        telemetry: Telemetry,
        *,
        root_id: str | None = None,
    ) -> None:
        self.store, self.model_factory = store, model_factory
        self.checkpointer, self.telemetry = checkpointer, telemetry
        self.root_id = root_id
        self.owner = "agent-worker-" + uuid4().hex
        self._provider_error: str | None = None
        self._attempt_id = ""
        self._agent_trace: dict[str, Any] = {}
        self._last_error: dict[str, Any] | None = None
        self._prompt_catalog_sha256 = prompt_manifest_sha256()
        self.completed_task: AgentTask | None = None

    def health(self) -> dict[str, Any]:
        self._provider_error = self.store.get_provider_failure()
        return {
            "available": self._provider_error is None,
            "error_code": self._provider_error,
            "automatic_retry": False,
            "last_error": self._last_error,
        }

    def _optional_task(self, identifier: str) -> AgentTask | None:
        try:
            return self.store.get_task(identifier)
        except Exception as exc:
            if getattr(exc, "code", None) == "not_found":
                return None
            raise

    def reset_provider_availability(self, generation_id: str) -> None:
        """Only an explicit successful provider check may call this administrative hook."""
        self.store.clear_provider_failure()
        self._provider_error = None

    def _check_provider(self, generation_id: str, mode: Mode) -> None:
        if mode != "live":
            return
        self._provider_error = self.store.get_provider_failure()
        if self._provider_error:
            raise ValidationError(self._provider_error, "Provider unavailable; no automatic retry.")

    def submit_question(
        self,
        session: ReplaySession,
        snapshot: WindowSnapshot,
        question: str,
        idempotency_key: str,
        automatic: bool = False,
        episode_id: str | None = None,
    ) -> AgentTask:
        """Create an idempotent root pinned to persisted evidence and the prompt catalog."""
        from datetime import timedelta

        if session.workflow == "sensor_alerts":
            raise ValidationError(
                "workflow_disabled",
                "Sensor alerts only: agent investigation is disabled. Start an agent-assisted run.",
            )
        if (
            session.id != snapshot.generation_id
            or session.site_id != snapshot.site_id
            or session.tenant_id != snapshot.tenant_id
        ):
            raise ValidationError("scope", "Question scope does not match the replay and window.")
        pinned = self.store.get_window(snapshot.id)
        if pinned is None or pinned != snapshot:
            raise ValidationError(
                "snapshot", "Question must bind the persisted immutable snapshot."
            )
        if not question.strip() or len(question) > 4000 or not idempotency_key:
            raise ValidationError("question", "Question and idempotency key must be bounded.")
        identifier = str(
            uuid5(
                NAMESPACE_URL,
                json.dumps(
                    [
                        session.tenant_id,
                        session.site_id,
                        session.id,
                        idempotency_key,
                    ]
                ),
            )
        )
        existing = self._optional_task(identifier)
        # A retry of the same submission retains its original history, policy and guidance.
        if existing is None:
            self._check_provider(session.id, session.mode)
        history_version = existing.history_version if existing else None
        if existing is None:
            from subsea_copilot.synthetic import SOURCE_VERSION

            if session.source_version == SOURCE_VERSION:
                from subsea_copilot.history_data import EXTENDED_HISTORY_PATH, history_index_rows
                from subsea_copilot.synthetic import EXTENDED_PACK_VERSION

                history_rows = history_index_rows(
                    EXTENDED_HISTORY_PATH
                    if snapshot.pack_version == EXTENDED_PACK_VERSION
                    else None
                )
                if (
                    snapshot.pack_version == EXTENDED_PACK_VERSION
                    and session.scenario.startswith("frozen-pressure-")
                ):
                    # Bind layout-wide records to the source identity, not a workload name.
                    history_rows = [
                        {**row, "scenarios": [session.scenario]} for row in history_rows
                    ]
                history_version = self.store.install_history(history_rows)
        task = AgentTask(
            id=identifier,
            root_id=identifier,
            site_id=session.site_id,
            tenant_id=session.tenant_id,
            generation_id=session.id,
            snapshot_id=snapshot.id,
            episode_id=episode_id,
            role="operator_response",
            purpose=REGISTRY["operator_response"].purpose,
            question=question,
            mode=session.mode,
            deadline=utc_now() + timedelta(seconds=ROOT_DEADLINE_SECONDS),
            automatic=automatic,
            idempotency_key=idempotency_key,
            history_version=history_version,
            prompt_catalog_sha256=(
                existing.prompt_catalog_sha256 if existing else self._prompt_catalog_sha256
            ),
            knowledge_packet=existing.knowledge_packet
            if existing
            else (self._knowledge_for(snapshot) if history_version else None),
            decision_policy=existing.decision_policy if existing else "llm-diagnosis-v1",
            response_protocol=existing.response_protocol
            if existing
            else "engineer-v2",
        )
        return self.store.create_task(task)

    def _event(self, task: AgentTask, name: str, payload: dict[str, Any]) -> None:
        self.store.publish_event(
            task.generation_id, name, payload, snapshot_id=task.snapshot_id, task_id=task.id
        )

    def _harness_event(self, task: AgentTask, name: str, payload: dict[str, Any]) -> None:
        assert task.lease_token is not None
        self.store.record_task_event(task.id, task.lease_token, name, payload)

    def _knowledge_for(self, snapshot: WindowSnapshot) -> KnowledgePacket | None:
        """Pin applicable reviewed guidance; invalid guidance withholds RCA, not monitoring."""
        try:
            packet = select_knowledge(
                load_knowledge(),
                site_id=snapshot.site_id,
                pack_version=snapshot.pack_version,
                as_of=utc_now(),
            )
        except (ValueError, OSError) as exc:
            raise ValidationError(
                "knowledge_unavailable",
                "Knowledge validation failed; numerical monitoring remains active.",
            ) from exc
        if not any("operator_response" in card.roles for card in packet.cards):
            raise ValidationError(
                "knowledge_unavailable",
                "No applicable reviewed research guidance; expert RCA is withheld.",
            )
        return packet

    def _save(self, task: AgentTask) -> AgentTask:
        return self.store.save_task(
            task, expected_version=task.version, lease_token=task.lease_token
        )

    def _claim_task(self) -> AgentTask | None:
        if self.root_id is not None:
            return self.store.claim_task(
                self.owner, ttl_seconds=TASK_LEASE_SECONDS, root_id=self.root_id,
            )
        return self.store.claim_task(self.owner, ttl_seconds=TASK_LEASE_SECONDS)

    def _gateway(self, task: AgentTask, snapshot: WindowSnapshot) -> ToolGateway:
        return ToolGateway(self.store, task, snapshot, self.telemetry)

    def _schemas(self, task: AgentTask) -> list[dict[str, Any]]:
        """Hide completed intake-only reads and bind current-policy schemas to exact scope."""
        completed = {
            receipt["name"]
            for receipt in self.store.tool_receipts(task.id)
            if not receipt.get("error")
        }
        intake_only = role_policy(task.role, task.decision_policy).required | {"location.fit"}
        schemas = [
            schema
            for schema in tool_schemas(task.role, task.decision_policy)
            if schema["function"]["name"] == "evidence.get"
            or schema["function"]["name"] not in completed & intake_only
        ]
        if task.decision_policy == "llm-diagnosis-v1":
            snapshot = self.store.get_window(task.snapshot_id)
            if snapshot is None:
                raise ValidationError("scope", "Pinned tool-schema window is unavailable.")
            scope = {
                "site_id": snapshot.site_id,
                "snapshot_id": snapshot.id,
                "pack_version": snapshot.pack_version,
                "baseline_version": snapshot.baseline_version,
                "parameter_version": snapshot.parameter_version,
            }
            for schema in schemas:
                properties = schema["function"]["parameters"]["properties"]
                for key, value in scope.items():
                    properties[key]["const"] = value
        return schemas

    def _prompt_name(self, task: AgentTask) -> str:
        if task.decision_policy == "llm-diagnosis-v1":
            return "llm-" + PROMPT_NAMES[task.role]
        return PROMPT_NAMES[task.role]

    @staticmethod
    def _model_limit(task: AgentTask) -> int:
        """Allow engineer-v2 coordinator review/reflection within one shared 18-call ceiling."""
        return (
            6 * BUDGET_MULTIPLIER
            if task.role == "operator_response" and task.response_protocol == "engineer-v2"
            else REGISTRY[task.role].model_limit
        )

    def _accept(
        self,
        value: str,
        task: AgentTask,
        snapshot: WindowSnapshot,
        gateway: ToolGateway,
    ) -> AgentResult:
        """Attach only already-read sources, then validate without choosing model findings."""
        receipts = self.store.tool_receipts(task.id)
        candidate = (
            bind_read_claim_evidence(
                AgentResult.model_validate(parse_json(value)), snapshot, receipts,
                include_read_kinds=frozenset({"channel_summary"})
                if task.role == "event_diagnosis"
                and task.decision_policy == "llm-diagnosis-v1" else frozenset(),
            )
            if task.role == "operator_response" or task.decision_policy == "llm-diagnosis-v1"
            else value
        )
        return validate_result(
            candidate,
            task,
            snapshot,
            receipts,
            gateway.dependencies(),
        )

    def _required_intake(
        self,
        task: AgentTask,
        snapshot: WindowSnapshot,
        context: dict[str, Any],
        gateway: ToolGateway,
    ) -> tuple[list[dict[str, Any]], AgentTask]:
        """Perform mandatory reads through the gateway, distinct from model-selected actions."""
        names = set(context["required_tools"])
        pressure_ids: set[str] = set()
        if task.role == "event_diagnosis":
            pressure_ids = {
                sensor["pressure_summary_evidence_id"]
                for sensor in context.get("history_sensors", [])
                if sensor.get("pressure_summary_evidence_id")
            }
            if context.get("network_pressure_table"):
                pressure_ids.update(
                    item.id for item in snapshot.evidence.values()
                    if item.kind == "channel_summary"
                )
            if task.decision_policy == "llm-diagnosis-v1":
                pressure_ids.update(
                    ref for candidate in context["compatible_tasks"]
                    if candidate["role"] == "sensor_quality"
                    for ref in candidate["evidence_ids"]
                )
        if pressure_ids:
            names.add("evidence.get")
        if context.get("initial_record_search"):
            names.add("history.search")
        if context.get("initial_pressure_comparisons"):
            names.add("history.compare")
        if task.role == "event_diagnosis" or context.get("baseline"):
            if snapshot.event.eligible_location:
                names.add("location.fit")
        outputs = []
        for name in sorted(names, key=lambda item: (item == "history.compare", item)):
            targets = context["compatible_tasks"] if name == "task.result" else [None]
            if name == "history.compare":
                targets = context["initial_pressure_comparisons"]
            if name == "evidence.get":
                ids = sorted(
                    pressure_ids if task.role == "event_diagnosis" else
                    {ref for t in context["compatible_tasks"] for ref in t["evidence_ids"]}
                )
                if task.role == "operator_response":
                    ids.extend(
                        item.id for item in snapshot.evidence.values()
                        if item.kind == "location_fit" and item.id not in ids
                    )
                by_kind: dict[str, list[str]] = {}
                for identifier in ids:
                    kind = (
                        snapshot.evidence[identifier].kind
                        if task.role == "operator_response" and len(ids) > 24 else "batch"
                    )
                    by_kind.setdefault(kind, []).append(identifier)
                targets = [
                    {"ids": group[start:start + 24]}
                    for group in by_kind.values()
                    for start in range(0, len(group), 24)
                ]
            if task.role == "event_diagnosis" and name == "task.result":
                targets = [t for t in targets if t is not None and t["role"] == "sensor_quality"]
            if (
                name == "task.result" and task.role == "operator_response"
                and task.decision_policy == "llm-diagnosis-v1"
            ):
                targets = [
                    {**candidate, "comparison_offset": offset}
                    for candidate in context["compatible_tasks"]
                    for offset in range(max(
                        1, len((candidate.get("investigation") or {}).get(
                            "comparison_call_ids", [],
                        )),
                    ))
                ]
            for target in targets:
                arguments = dict(context["scope"])
                if target is not None and name == "task.result":
                    arguments["task_id"] = target["id"]
                    if "comparison_offset" in target:
                        arguments["comparison_offset"] = target["comparison_offset"]
                if name == "evidence.get":
                    if target is None:
                        raise ValidationError("required_intake", "Evidence batch is missing.")
                    arguments["ids"] = target["ids"]
                if name == "history.search":
                    arguments.update(context["initial_record_search"])
                if name == "history.compare":
                    if target is None:
                        raise ValidationError("required_intake", "Pressure comparison is missing.")
                    arguments.update(target)
                    arguments.update(
                        knowledge_ids=context["comparison_knowledge_ids"],
                        check_question=(
                            "Do paired time profiles support a joint pressure change "
                            "or an individual reading problem?"
                        ),
                        intent="test_instrumentation",
                    )
                identity = json.dumps(
                    [task.id, snapshot.id, name, arguments, "required-intake-v1"], sort_keys=True
                )
                # Stable application call IDs let checkpoint recovery replay receipts safely.
                call = {
                    "id": str(uuid5(NAMESPACE_URL, identity)),
                    "name": name,
                    "args": arguments,
                    "origin": "application_required_intake",
                }
                output = gateway.dispatch(call)
                if output["error"]:
                    raise ValidationError(output["error"], "Mandatory scoped intake read failed.")
                outputs.append(
                    {
                        "call_id": call["id"],
                        "name": name,
                        "output": output,
                        "origin": call["origin"],
                    }
                )
        if task.role == "event_diagnosis" and task.decision_policy == "llm-diagnosis-v1":
            document_ids = sorted({
                document["id"] for item in outputs if item["name"] == "history.search"
                for document in item["output"]["result"].get("documents", [])
            })
            for start in range(0, len(document_ids), HISTORY_DOCUMENT_LIMIT):
                search = context["initial_record_search"]
                arguments = {
                    **context["scope"],
                    "document_ids": document_ids[start:start + HISTORY_DOCUMENT_LIMIT],
                    "knowledge_ids": search["knowledge_ids"],
                    "intent": search["intent"],
                    "check_question": (
                        "Read actual records and contradictions relevant to the paired "
                        "measurements, not just titles; records alone do not establish cause."
                    ),
                }
                identity = json.dumps(
                    [task.id, snapshot.id, "history.read", arguments, "required-intake-v1"],
                    sort_keys=True,
                )
                call = {
                    "id": str(uuid5(NAMESPACE_URL, identity)), "name": "history.read",
                    "args": arguments, "origin": "application_required_intake",
                }
                output = gateway.dispatch(call)
                if output["error"]:
                    raise ValidationError(output["error"], "Original record intake read failed.")
                outputs.append({
                    "call_id": call["id"], "name": call["name"], "output": output,
                    "origin": call["origin"],
                })
        if task.role == "sensor_quality" and task.decision_policy == "llm-diagnosis-v1":
            reviewed_claims = {
                ref
                for item in outputs
                if item["name"] in {
                    "quality.coverage", "quality.conflicts", "quality.sensor_patterns",
                }
                for ref, body in item["output"]["result"].get("claims", {}).items()
                if ref in snapshot.claims
                and body == snapshot.claims[ref].model_dump(mode="json")
            }
            ids = sorted({
                ref for claim_id in reviewed_claims
                for ref in snapshot.claims[claim_id].evidence_ids
            })
            for start in range(0, len(ids), 24):
                arguments = {**context["scope"], "ids": ids[start:start + 24]}
                identity = json.dumps(
                    [task.id, snapshot.id, "evidence.get", arguments, "required-intake-v1"],
                    sort_keys=True,
                )
                call = {
                    "id": str(uuid5(NAMESPACE_URL, identity)),
                    "name": "evidence.get",
                    "args": arguments,
                    "origin": "application_required_intake",
                }
                output = gateway.dispatch(call)
                if output["error"]:
                    raise ValidationError(output["error"], "Reviewed quality source read failed.")
                outputs.append({
                    "call_id": call["id"], "name": call["name"], "output": output,
                    "origin": call["origin"],
                })
        return outputs, gateway.task

    def _context(self, task: AgentTask, snapshot: WindowSnapshot, phase: str) -> dict[str, Any]:
        """Bind role instructions to rechecked dependencies, measurements and result schema."""
        scope = {
            "site_id": snapshot.site_id,
            "snapshot_id": snapshot.id,
            "pack_version": snapshot.pack_version,
            "baseline_version": snapshot.baseline_version,
            "parameter_version": snapshot.parameter_version,
        }
        fresh = task.automatic and self.store.get_replay(task.generation_id).pause_on_anomaly
        candidates = [
            t
            for t in self.store.list_tasks(task.generation_id)
            if t.role != "operator_response"
            and compatible(task, t, snapshot)
            and (
                task.prompt_catalog_sha256 is None
                or t.prompt_catalog_sha256 == task.prompt_catalog_sha256
            )
            and (not fresh or t.root_id == task.root_id)
        ]
        checked_candidates = []
        # Cached acceptance is only a candidate: validate its current contract and dependencies.
        for candidate in candidates:
            gateway = ToolGateway(self.store, candidate, snapshot, self.telemetry)
            dependencies = gateway.dependencies()
            try:
                for dependency in dependencies:
                    assert dependency.result is not None
                    validate_result(
                        dependency.result,
                        dependency,
                        snapshot,
                        self.store.tool_receipts(dependency.id),
                        ToolGateway(
                            self.store, dependency, snapshot, self.telemetry
                        ).dependencies(),
                    )
                assert candidate.result is not None
                validate_result(
                    candidate.result,
                    candidate,
                    snapshot,
                    self.store.tool_receipts(candidate.id),
                    dependencies,
                )
            except ValidationError:
                continue  # Incompatible cached contracts require fresh work, never a weaker check.
            checked_candidates.append(candidate)
        candidates = checked_candidates
        requires_location = question_requires_location(task.question)
        if (
            phase == "plan"
            and requires_location
            and snapshot.event.eligible_location
            and snapshot.location
            and snapshot.location.status in {"located", "ambiguous"}
        ):
            candidates = [
                t
                for t in candidates
                if t.role != "event_diagnosis"
                or t.result is not None
                and (
                    t.result.outcome == "insufficient_evidence"
                    or any(snapshot.claims[r].kind == "location" for r in t.result.claim_refs)
                )
            ]
        if phase != "plan" and "reuse" in task.plan:
            bound_ids = self.store.reuse_task_ids(task.id)
            candidates = [t for t in candidates if t.id in bound_ids]
        elif phase != "plan":
            candidates = [
                t
                for t in candidates
                if t.parent_id == (task.id if task.role == "operator_response" else task.parent_id)
            ]
        elif candidates:
            diagnoses = [t for t in candidates if t.role == "event_diagnosis"]
            if diagnoses:
                selected = max(diagnoses, key=lambda t: (t.created_at, t.id))
                quality = [
                    t
                    for t in candidates
                    if t.role == "sensor_quality" and t.parent_id == selected.parent_id
                ]
                candidates = quality[:1] + [selected]
            else:
                candidates = [max(candidates, key=lambda t: (t.created_at, t.id))]
        result_schema = (
            WorkPlan.model_json_schema() if phase == "plan" else AgentResult.model_json_schema()
        )
        if phase == "plan" and (task.history_version or fresh):
            result_schema["properties"]["steps"]["enum"] = [
                ["quality", "diagnosis", "answer"],
            ] + ([] if fresh else [["reuse", "answer"]])
        if phase != "plan":
            ledger_codes = {
                str(c.value.get("code")) if isinstance(c.value, dict) else str(c.value)
                for c in snapshot.claims.values()
                if c.kind == "limitation"
            }
            result_schema["properties"]["limitations"]["items"] = {
                "type": "string",
                "enum": sorted(LIMITATIONS | ledger_codes),
            }
            if task.decision_policy == "llm-diagnosis-v1":
                result_schema["properties"]["evidence_ids"]["description"] = (
                    "Leave empty: the application attaches already read sources for your "
                    "chosen claim_refs. Diagnosis also forwards its actually read pressure "
                    "measurements. Never put bundle tokens or document IDs in this field."
                )
                claim_ids = sorted(
                    ref for ref, claim in snapshot.claims.items()
                    if claim.kind in role_policy(task.role, task.decision_policy).claim_kinds
                )
                if claim_ids:
                    result_schema["properties"]["claim_refs"]["items"] = {
                        "type": "string", "enum": claim_ids,
                    }
                else:
                    result_schema["properties"]["claim_refs"]["maxItems"] = 0
                required_limits = dependency_limitations(candidates)
                if required_limits:
                    result_schema["properties"]["limitations"]["allOf"] = [
                        {"contains": {"const": code}} for code in sorted(required_limits)
                    ]
            if task.role != "operator_response" or task.response_protocol not in {
                "engineer-v1",
                "engineer-v2",
            }:
                result_schema["properties"]["interpretation"] = {"type": "null"}
                for name in (
                    "EngineerInterpretation",
                    "CitedExplanation",
                    "CauseExplanation",
                    "RegionalAssessment",
                ):
                    result_schema.get("$defs", {}).pop(name, None)
            else:
                result_schema["required"].append("interpretation")
                result_schema["properties"]["interpretation"] = {
                    "$ref": "#/$defs/EngineerInterpretation"
                }
            result_schema["properties"]["summary"] = {"type": "string", "const": ""}
            if task.decision_policy == "llm-diagnosis-v1" and task.role != "operator_response":
                result_schema["properties"]["summary"] = {"type": "string", "maxLength": 3000}
            if task.role == "sensor_quality":
                if task.decision_policy == "legacy-v1" and quality_facts_available(snapshot):
                    result_schema["properties"]["outcome"] = {
                        "type": "string",
                        "const": "supported",
                    }
                result_schema["properties"]["hypothesis"] = {"type": "null"}
                result_schema["properties"]["recommendation_ids"] = {
                    "type": "array",
                    "maxItems": 0,
                }
            child_abstained = any(t.state == "ABSTAINED" for t in candidates)
            assesses_event = (
                task.role == "event_diagnosis"
                or task.purpose == "evaluate_single_agent_baseline"
                or any(t.role == "event_diagnosis" for t in candidates)
            )
            must_abstain = (
                task.decision_policy == "legacy-v1" and task.role != "sensor_quality"
                and (
                    child_abstained
                    or assesses_event
                    and snapshot.event.hypothesis == "insufficient_evidence"
                    and not investigation_facts_available(task, snapshot)
                )
            )
            if (
                not child_abstained
                and task.decision_policy == "legacy-v1"
                and assesses_event
                and investigation_facts_available(task, snapshot)
            ):
                result_schema["properties"]["outcome"] = {
                    "type": "string", "const": "supported",
                }
                result_schema["properties"]["hypothesis"] = {
                    "type": "string", "const": "insufficient_evidence",
                }
                result_schema["properties"]["limitations"]["contains"] = {
                    "const": "insufficient_evidence",
                }
            if must_abstain:
                result_schema["properties"]["outcome"] = {
                    "type": "string",
                    "const": "insufficient_evidence",
                }
                result_schema["properties"]["hypothesis"] = {"type": "null"}
                eligible_refs = [
                    ref
                    for ref, claim in snapshot.claims.items()
                    if claim.kind in REGISTRY[task.role].claim_kinds
                    and abstention_claim_allowed(claim)
                ]
                result_schema["properties"]["claim_refs"]["items"] = (
                    {"type": "string", "enum": eligible_refs}
                    if len(eligible_refs) <= 32 * BUDGET_MULTIPLIER
                    else {
                        "type": "string",
                        "description": (
                            "Use actual read coverage, sensor_health or limitation claim IDs. "
                            "Application validation independently rejects every other claim."
                        ),
                    }
                )
            if (
                task.decision_policy == "legacy-v1" and child_abstained
                and task.role != "sensor_quality"
            ):
                result_schema["properties"]["limitations"]["contains"] = {
                    "const": "child_abstained",
                }
        profile_comparisons = self._initial_pressure_comparisons(
            snapshot, measurements_only=task.decision_policy == "llm-diagnosis-v1",
        ) if (
            task.role == "event_diagnosis" and task.history_version and task.knowledge_packet
            and len(snapshot.quality.findings) > 32 * BUDGET_MULTIPLIER
        ) else []
        context: dict[str, Any] = {
            "phase": phase,
            "role": task.role,
            "mode": task.mode,
            "scope": scope,
            "question": task.question,
            "task_id": task.id,
            "read_evidence_reference": (
                read_evidence_reference(task.snapshot_id, self.store.tool_receipts(task.id))
                if phase != "plan" and task.role == "operator_response" else None
            ),
            "plan": task.plan,
            "compatible_tasks": [
                {
                    "id": t.id,
                    "role": t.role,
                    "state": t.state,
                    "claim_refs": t.result.claim_refs,
                    "evidence_ids": t.result.evidence_ids,
                    "summary": t.result.summary,
                    "question": t.question,
                    "investigation": t.result.investigation.model_dump(mode="json")
                    if t.result.investigation
                    else None,
                    "investigation_reads": [
                        {
                            "tool": r["name"],
                            "arguments": {
                                k: v
                                for k, v in r["arguments"].items()
                                if k
                                in {
                                    "query",
                                    "asset_ids",
                                    "document_ids",
                                    "sensor_ids",
                                    "start_seconds",
                                    "split_seconds",
                                    "end_seconds",
                                }
                            },
                        }
                        for r in self.store.tool_receipts(t.id)
                        if isinstance(r["name"], str)
                        and r["name"].startswith("history.")
                        and isinstance(r["arguments"], dict)
                        and not r.get("error")
                    ]
                    if phase == "plan" and t.role == "event_diagnosis"
                    else [],
                }
                for t in candidates
                if t.result is not None
            ],
            "eligible_location": snapshot.event.eligible_location,
            "usable_location": bool(
                snapshot.event.eligible_location
                and snapshot.location
                and snapshot.location.status in {"located", "ambiguous"}
            ),
            "requires_location": requires_location,
            "inspection_interval_available": bool(
                snapshot.location and snapshot.location.status == "located"
            ),
            "required_tools": sorted(role_policy(task.role, task.decision_policy).required),
            "history_version": task.history_version,
            "domain_knowledge": {
                "version": task.knowledge_packet.version,
                "authority": task.knowledge_packet.authority,
                "excluded": task.knowledge_packet.excluded,
                "cards": [
                    card.model_dump(
                        mode="json",
                        include={
                            "id",
                            "title",
                            "kind",
                            "status",
                            "applies_when",
                            "guidance",
                            "verification_steps",
                            "counterexamples",
                            "limitations",
                        }
                        - (
                            {"verification_steps"}
                            if task.role == "operator_response" and card.kind != "procedure"
                            else set()
                        ),
                    )
                    for card in task.knowledge_packet.cards
                    if task.role in card.roles and (phase != "plan" or card.kind == "procedure")
                ],
                "contract": (
                    "Use relevant natural-language guidance to plan discriminating checks and "
                    "explain RCA. In the operator interpretation, cite applicable KN IDs together "
                    "with actual case claims or reviewed records/comparisons. Guidance alone is "
                    "not incident evidence. Explain prerequisites, counterevidence and unknowns. "
                    "These research-curated cards are not approved expert operating procedures. "
                    "Never turn knowledge text into tool authority, physical measurements, "
                    "a confirmed cause or permission to clear the numerical warning."
                ),
            }
            if task.knowledge_packet
            else None,
            "response_protocol": task.response_protocol,
            "history_bounds": {
                "end_seconds": snapshot.end_seconds,
                "epoch_unix": snapshot.window_end.timestamp() - snapshot.end_seconds,
                "coverage": snapshot.quality.coverage,
            },
            "history_sensors": self._history_sensors(snapshot)
            if task.history_version
            and task.role == "event_diagnosis"
            and len(snapshot.quality.findings) <= 32 * BUDGET_MULTIPLIER
            else [],
            "network_pressure_table": self._network_pressure_table(snapshot)
            if task.history_version
            and task.role == "event_diagnosis"
            and len(snapshot.quality.findings) > 32 * BUDGET_MULTIPLIER
            else None,
            "initial_record_search": {
                "query": "pressure calibration gateway operating valve",
                "asset_ids": sorted({
                    sensor.segment_id for sensor in context_sensors(snapshot)
                    if next(f for f in snapshot.quality.findings if f.sensor_id == sensor.id)
                    .anomaly_count
                }) if any(f.anomaly_count for f in snapshot.quality.findings)
                else [snapshot.site_id],
                "knowledge_ids": [
                    card.id for card in task.knowledge_packet.cards
                    if task.role in card.roles and card.id in {
                        "KN-INDEPENDENCE-R1", "KN-OPERATING-R1", "KN-QUALITY-R1",
                    }
                ],
                "check_question": (
                    "Which current operating or calibration records could explain "
                    "the observed pressure changes?"
                ),
                "intent": "seek_counterevidence",
            }
            if task.role == "event_diagnosis" and task.history_version
            and task.knowledge_packet
            and (any(f.anomaly_count for f in snapshot.quality.findings) or profile_comparisons)
            else None,
            "history_regions": [],
            "initial_pressure_comparisons": profile_comparisons,
            "comparison_knowledge_ids": [
                card.id for card in task.knowledge_packet.cards
                if task.role in card.roles and card.id in {
                    "KN-INDEPENDENCE-R1", "KN-OPERATING-R1",
                }
            ] if task.knowledge_packet else [],
            "pressure_summary_contract": (
                load_prompt("pressure-summary").content.removesuffix("\n")
            ),
            "history_scope": (
                "Network rows are measured summaries, not causes. "
                "Decode columns and failure_domains. "
                "Per-instrument longest runs may be left-censored and are not joint onsets. "
                "Comparisons need >=10s per side; records are incident-time filtered."
            )
            if task.history_version and task.role == "event_diagnosis"
            else None,
            "result_schema": result_schema,
            "batch_instruction": load_prompt("batch").content.removesuffix("\n"),
        }
        context["decision_policy"] = task.decision_policy
        if task.decision_policy == "llm-diagnosis-v1":
            for field in (
                "eligible_location", "usable_location", "inspection_interval_available",
                "requires_location",
            ):
                # Do not leak archived eligibility/location decisions into current reasoning.
                context.pop(field, None)
            for sensor in context["history_sensors"]:
                sensor.pop("event_support", None)
                sensor.pop("quality_concern", None)
            table = context.get("network_pressure_table")
            if table:
                index = table["columns"].index("quality_concern")
                table["columns"].pop(index)
                for row in table["rows"]:
                    row.pop(index)
        return context

    @staticmethod
    def _initial_pressure_comparisons(
        snapshot: WindowSnapshot, *, measurements_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Batch station-paired profiles; current policy includes every instrument, not labels."""
        from subsea_copilot.monitoring import instrument_signals
        from subsea_copilot.synthetic import generate_pack

        pack = generate_pack(snapshot.site_id, version=snapshot.pack_version)
        findings = {finding.sensor_id: finding for finding in snapshot.quality.findings}
        by_id = {sensor.id: sensor for sensor in pack.sensors}
        selected = set(by_id) if measurements_only else {
            identifier for identifier, finding in findings.items()
            if finding.anomaly_count or finding.spike_count
            or finding.drift_suspected or finding.peer_disagreement
        }
        selected.update(identifier for identifier, _kind in instrument_signals(snapshot, pack))
        stations = {(by_id[identifier].segment_id, by_id[identifier].station_id)
                    for identifier in selected}
        selected.update(
            sensor.id for sensor in pack.sensors
            if (sensor.segment_id, sensor.station_id) in stations
        )
        for branch in ([] if measurements_only else pack.segments):
            alerts = [
                sensor for sensor in pack.sensors
                if sensor.segment_id == branch.id and findings[sensor.id].anomaly_count
            ]
            domains = {sensor.failure_domain_id for sensor in alerts}
            if len(domains) != 1 or len({sensor.station_id for sensor in alerts}) < 2:
                continue
            quiet = [
                sensor for sensor in pack.sensors
                if sensor.segment_id == branch.id and sensor.failure_domain_id not in domains
                and not (
                    findings[sensor.id].anomaly_count or findings[sensor.id].spike_count
                    or findings[sensor.id].peer_disagreement
                )
                and findings[sensor.id].usable >= findings[sensor.id].expected * pack.min_coverage
            ]
            if quiet:
                reference = min(
                    quiet,
                    key=lambda sensor: (
                        min(abs(sensor.chainage_m - alert.chainage_m) for alert in alerts),
                        sensor.id,
                    ),
                )
                selected.update(
                    sensor.id for sensor in pack.sensors
                    if sensor.segment_id == reference.segment_id
                    and sensor.station_id == reference.station_id
                )
        identifiers = sorted(selected)
        end = snapshot.end_seconds
        start = max(0, end - HISTORY_RANGE_SECONDS)
        # Paired-only results avoid cross-station matrices and keep station pairs together.
        return [
            {
                "sensor_ids": identifiers[index:index + 24],
                "paired_only": True,
                "start_seconds": start,
                "split_seconds": start + (end - start) // 2,
                "end_seconds": end,
            }
            for index in range(0, len(identifiers), 24)
        ]

    @staticmethod
    def _network_pressure_table(snapshot: WindowSnapshot) -> dict[str, Any]:
        """Project all measured summaries; rounding is display compaction, not new evidence."""
        from subsea_copilot.synthetic import generate_pack

        pack = generate_pack(snapshot.site_id, version=snapshot.pack_version)
        domains = list(dict.fromkeys(sensor.failure_domain_id for sensor in pack.sensors))
        findings = {finding.sensor_id: finding for finding in snapshot.quality.findings}
        summaries = {
            item.sensor_id: item.value
            for item in snapshot.evidence.values()
            if item.kind == "channel_summary" and isinstance(item.value, dict)
        }

        def rounded_drop(identifier: str) -> float | None:
            value = summaries.get(identifier, {}).get("recent_5s_pressure_drop_bar")
            if value is None:
                return None
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValidationError("measurement_summary", "Invalid measured pressure delta.")
            return round(value, 4)

        return {
            "columns": [
                "sensor_id",
                "chainage_m",
                "failure_domain_index",
                "usable_fraction",
                "recent_5s_pressure_drop_bar",
                "max_abs_score",
                "anomaly_count",
                "quality_concern",
                "drop_run_seconds",
                "rise_run_seconds",
                "recent_5s_usable_samples",
            ],
            "recent_period_seconds": [snapshot.end_seconds - 5, snapshot.end_seconds],
            "drop_reference": (
                "Supplied normal-baseline median minus usable median in the final "
                "five source seconds for every instrument, without threshold conditioning. "
                "Positive means below normal; negative means above normal. "
                "This reference is not a completed field verification. "
                "Null means no baseline or usable final-five-second observations. "
                "Twenty-second and screening statistics remain in original pressure evidence."
            ),
            "failure_domains": domains,
            "rows": [
                [
                    sensor.id,
                    sensor.chainage_m,
                    domains.index(sensor.failure_domain_id),
                    round(findings[sensor.id].usable / max(findings[sensor.id].expected, 1), 3),
                    rounded_drop(sensor.id),
                    round(findings[sensor.id].max_score, 2),
                    findings[sensor.id].anomaly_count,
                    bool(
                        findings[sensor.id].missing
                        or findings[sensor.id].hard_excluded
                        or findings[sensor.id].spike_count
                        or findings[sensor.id].peer_disagreement
                        or findings[sensor.id].drift_suspected
                    ),
                    summaries.get(sensor.id, {}).get("pressure_drop_period_seconds"),
                    summaries.get(sensor.id, {}).get("pressure_rise_period_seconds"),
                    summaries.get(sensor.id, {}).get("recent_5s_usable_samples"),
                ]
                for sensor in pack.sensors
            ],
            "total_instruments": len(pack.sensors),
            "scope": "all_instruments_measurement_summary_not_a_causal_diagnosis",
        }

    @staticmethod
    def _history_sensors(snapshot: WindowSnapshot) -> list[dict[str, Any]]:
        """Link the small-layout context to actual pressure-summary source identities."""
        findings = {finding.sensor_id: finding for finding in snapshot.quality.findings}
        concerns = {
            f.sensor_id
            for f in snapshot.quality.findings
            if f.spike_count
            or f.drift_suspected
            or f.peer_disagreement
            or f.hard_excluded
            or f.missing > f.expected * 0.1
        }
        sensors = context_sensors(snapshot)
        pressure_summaries = {
            evidence.sensor_id: evidence.id for evidence in snapshot.evidence.values()
            if evidence.kind == "channel_summary"
        }
        return [
            {
                "id": s.id,
                "segment_id": s.segment_id,
                "failure_domain": s.failure_domain_id,
                "quality_concern": s.id in concerns,
                "event_support": s.id in snapshot.event.supporting_sensor_ids,
                "anomalous_samples": findings[s.id].anomaly_count,
                "pressure_summary_evidence_id": pressure_summaries.get(s.id),
            }
            for s in sensors
        ]

    def _graph(
        self,
        task: AgentTask,
        snapshot: WindowSnapshot,
        phase: str,
        candidate: AgentResult | None = None,
        criticism: GroundingAssessment | None = None,
        previous_candidate: AgentResult | None = None,
    ) -> tuple[dict[str, Any], AgentTask]:
        """Run or resume one phase, fulfilling bounded interrupts and auditing every attempt."""
        gateway = self._gateway(task, snapshot)

        critic = phase.startswith("critic-")
        reflection = phase.startswith("reflection")
        sources = (
            source_texts(
                candidate, snapshot, self.store.tool_receipts(task.id), task.knowledge_packet
            )
            if candidate
            else {}
        )
        carried = (
            reusable_checks(
                previous_candidate, candidate, criticism,
                source_texts(
                    previous_candidate, snapshot, self.store.tool_receipts(task.id),
                    task.knowledge_packet,
                ),
                sources, require_quotes=task.decision_policy != "llm-diagnosis-v1",
            )
            if critic and previous_candidate is not None and candidate is not None
            and criticism is not None else []
        )

        def rejection(
            error: Exception, repairs: int, retry: bool, value: str | None
        ) -> dict[str, Any]:
            current = self.store.get_task(task.id)
            diagnostic = {
                **validation_diagnostic(error),
                "phase": phase,
                "role": task.role,
                "attempt_id": self._attempt_id,
                "candidate_sha256": content_hash(value),
                "repair_requested": (
                    retry and current.model_calls < self._model_limit(current)
                    and current.deadline > utc_now()
                ),
                "repair_attempt": repairs + 1,
            }
            diagnostic["rejection_id"] = "rejection-" + content_hash(diagnostic)
            self._harness_event(current, "validation.rejected", diagnostic)
            if diagnostic["repair_requested"]:
                self._harness_event(current, "validation.repair_requested", {
                    "phase": phase, "rejection_id": diagnostic["rejection_id"],
                    "repair_attempt": repairs + 1,
                    "candidate_sha256": diagnostic["candidate_sha256"],
                })
            return diagnostic

        def validate(value: str) -> BaseModel:
            current = self.store.get_task(task.id)
            with self.telemetry.span(
                "guardrail", {"task_id": task.id, "role": task.role, "phase": phase}
            ) as guardrail:
                guardrail.set_attribute("langfuse.observation.input", value)
                try:
                    accepted: BaseModel
                    if phase == "plan":
                        accepted = WorkPlan.model_validate(parse_json(value))
                        assert isinstance(accepted, WorkPlan)
                        checked_plan_sources(
                            accepted, bool(current.history_version), context["compatible_tasks"]
                        )
                    elif critic:
                        assert candidate is not None
                        batch = GroundingCheckBatch.model_validate(parse_json(value))
                        expected = set(context["candidate_paragraphs"])
                        received = [check.paragraph_id for check in batch.checks]
                        if len(set(received)) != len(received) or set(received) != expected:
                            raise ValidationError(
                                "grounding_coverage", "Review every requested unit exactly once.",
                            )
                        assessment = GroundingAssessment(
                            decision=batch.decision, checks=[*carried, *batch.checks],
                        )
                        accepted = validate_assessment(
                            assessment, candidate, sources,
                            require_quotes=task.decision_policy != "llm-diagnosis-v1",
                            require_corrections=(
                                task.decision_policy == "llm-diagnosis-v1" and task.mode == "live"
                            ),
                        )
                    else:
                        if reflection:
                            assert candidate is not None
                            assert criticism is not None
                            value = apply_revision(value, candidate, criticism).model_dump_json()
                        result = self._accept(value, current, snapshot, gateway)
                        if candidate is not None:
                            validate_revision(candidate, result)
                        accepted = result
                except (ValueError, TypeError) as exc:
                    diagnostic = validation_diagnostic(exc)
                    code = diagnostic["code"]
                    guardrail.set_attribute("error.code", code)
                    guardrail.set_attribute("validation.status", "failed")
                    guardrail.update_name(
                        f"{ROLE_NAMES[task.role]} / {phase} check: failed ({code})"
                    )
                    repairs = output.get("repairs", 0)
                    repair_available = (
                        repairs < SCHEMA_REPAIR_LIMIT
                        and current.model_calls < self._model_limit(current)
                        and current.deadline > utc_now()
                    )
                    guardrail.set_attribute(
                        "validation.repair_requested", repair_available
                    )
                    guardrail.set_attribute(
                        "langfuse.observation.output",
                        json.dumps(
                            {
                                "status": "failed",
                                **diagnostic,
                                "repair_requested": repair_available,
                                "repair_attempt": (
                                    repairs + 1 if repair_available else None
                                ),
                                "repair_instruction": (
                                    "Regenerate a complete valid result using the supplied "
                                    "evidence and this feedback. The invalid draft is excluded "
                                    "from the retry prompt."
                                    if repair_available
                                    else None
                                ),
                            }
                        ),
                    )
                    raise
                guardrail.set_attribute("validation.status", "passed")
                guardrail.update_name(f"{ROLE_NAMES[task.role]} / {phase} check: passed")
                resolved = [
                    identifier
                    for message in output.get("messages", [])
                    if isinstance(message, HumanMessage)
                    and isinstance(message.content, str)
                    and message.additional_kwargs.get("validation_repair")
                    if isinstance(
                        identifier := json.loads(message.content).get("rejection_id"), str
                    )
                ]
                guardrail.set_attribute(
                    "langfuse.observation.output",
                    json.dumps({"status": "passed", "resolved_rejection_ids": resolved}),
                )
                self._harness_event(current, "validation.passed", {
                    "phase": phase, "role": task.role, "candidate_sha256": content_hash(value),
                    "resolved_rejection_ids": resolved,
                })
                return accepted

        thread_id = hashlib.sha256(
            json.dumps(
                [
                    task.tenant_id,
                    task.site_id,
                    task.generation_id,
                    task.snapshot_id,
                    task.role,
                    task.id,
                    phase,
                ]
            ).encode()
        ).hexdigest()
        # A phase-specific thread separates plan/answer/reviews and all tenant/window scopes.
        config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": GRAPH_RECURSION_LIMIT,
        }
        if (
            task.prompt_catalog_sha256 is not None
            and task.prompt_catalog_sha256 != self._prompt_catalog_sha256
        ):
            raise ValidationError(
                "prompt_catalog_changed",
                "Investigation is pinned to another prompt catalog; start a fresh investigation.",
            )
        prompt_asset = load_prompt(
            ("llm-critic" if task.decision_policy == "llm-diagnosis-v1" else "critic")
            if critic else "reflection" if reflection
            else self._prompt_name(task).removesuffix(".md")
        )
        prompt = prompt_asset.content
        context: dict[str, Any] = (
            self._context(task, snapshot, "answer" if reflection else phase)
            if not critic and not reflection
            else critic_context(task, candidate, sources, phase)
            if candidate
            else {}
        )
        feedback = [
            {
                "paragraph_id": check.paragraph_id, "reason": check.reason,
                "corrections": [
                    correction.model_dump(mode="json") for correction in check.corrections
                ],
            }
            for check in criticism.checks if check.verdict != "supported"
        ] if criticism is not None else []
        if critic and previous_candidate is not None:
            context["previous_review_feedback"] = feedback
        if reflection:
            assert candidate is not None and candidate.interpretation is not None
            assert criticism is not None
            target_ids = {
                check.paragraph_id for check in criticism.checks if check.verdict != "supported"
            }
            context["revision_targets"] = {
                identifier: paragraph
                for identifier, paragraph in context.pop("candidate_paragraphs").items()
                if identifier in target_ids
            }
            context.update(
                {
                    "phase": "reflection",
                    "role": task.role,
                    "result_schema": InterpretationRevision.model_json_schema(),
                    "critic_feedback": feedback,
                    "reflection_instruction": (
                        load_prompt("reflection").content.removesuffix("\n")
                    ),
                    "pressure_summary_contract": (
                        load_prompt("pressure-summary").content.removesuffix("\n")
                    ),
                }
            )
        if carried:
            retained_ids = {check.paragraph_id for check in carried}
            context["candidate_paragraphs"] = {
                identifier: paragraph
                for identifier, paragraph in context["candidate_paragraphs"].items()
                if identifier not in retained_ids
            }
            context["unchanged_previously_grounded_units"] = sorted(retained_ids)
            if not any(
                identifier.startswith("question:") for identifier in context["candidate_paragraphs"]
            ):
                needed_sources = {
                    reference
                    for paragraph in context["candidate_paragraphs"].values()
                    for reference in paragraph["references"]
                }
                context["source_texts"] = {
                    reference: text for reference, text in sources.items()
                    if reference in needed_sources
                }
            self._harness_event(task, "grounding.checks_reused", {
                "phase": phase, "paragraph_ids": sorted(retained_ids),
                "basis": "identical unit and original source bytes; exact anchors revalidated",
            })
        graph = build_graph(
            self.checkpointer,
            validate,
            context["result_schema"],
            rejection,
        )
        prior = graph.get_state(config) if self.checkpointer is not None else None
        base_model = None
        if prior and prior.values and not prior.next:
            prompt_limit = prior.values.get("harness", {}).get("policy", {}).get(
                "prompt_limit", 144000
            )
        else:
            base_model = self.model_factory(task.role, task.mode)
            prompt_limit = getattr(base_model, "max_prompt_chars", 144000)
        if type(prompt_limit) is not int or prompt_limit <= 0:
            raise ValidationError("context_policy", "Model-input limit must be a positive integer.")
        provenance = harness_provenance(
            task, phase, prompt, context, prompt_limit=prompt_limit, prompt_asset=prompt_asset
        )
        messages: list[AnyMessage] = [
            SystemMessage(
                content=prompt
                + BOUND_ENVELOPE
                + json.dumps(context, allow_nan=False, separators=(",", ":"))
            )
        ]
        if prior and prior.values and prior.values.get("harness_id") not in (
            None, provenance["harness_id"]
        ):
            raise ValidationError(
                "harness_changed", "Checkpoint harness changed; start a fresh investigation."
            )
        legacy_checkpoint = bool(
            prior and prior.values and not prior.values.get("harness_id")
        )
        if legacy_checkpoint:
            assert prior is not None
            inherited = next(
                (message.content for message in prior.values["messages"]
                 if isinstance(message, SystemMessage) and isinstance(message.content, str)
                 and BOUND_ENVELOPE in message.content),
                None,
            )
            if inherited is None:
                raise ValidationError(
                    "harness_unavailable",
                    "Unversioned checkpoint has no attributable system prompt.",
                )
            inherited_prompt, inherited_context = inherited.split(BOUND_ENVELOPE, 1)
            provenance = harness_provenance(
                task, phase, inherited_prompt, json.loads(inherited_context),
                prompt_limit=prompt_limit,
            )
        if prior and prior.values and not prior.next:
            if prior.values.get("failure"):
                raise ValidationError(prior.values["failure"], "Previously rejected output.")
            return dict(prior.values["parsed"]), task
        self._harness_event(task, "harness.started", {
            "phase": phase, "attempt_id": self._attempt_id, **provenance,
            "legacy_checkpoint": legacy_checkpoint,
            "historical_harness_known": not legacy_checkpoint,
        })
        if prior and prior.values:
            output = graph.invoke(None, config)
        else:
            if phase != "plan" and not critic and not reflection:
                intake, task = self._required_intake(task, snapshot, context, gateway)
                messages.append(
                    HumanMessage(
                        content=json.dumps(
                            {
                                "application_intake": [
                                    {**item, "output": model_tool_result(item["output"])}
                                    for item in intake
                                ],
                                "instruction": (
                                    "Required reads are complete and audited. "
                                    "Interpret this evidence; do not exhaust health pagination. "
                                    "The supplied successful history reads count as completed "
                                    "investigation. Request additional reads only for concrete "
                                    "unresolved evidence gaps, batching independent requests. "
                                    "Do not reopen a receipt merely to cite it when its original "
                                    "body is already present in this model view. "
                                    "Otherwise return the final schema."
                                    if task.decision_policy == "llm-diagnosis-v1"
                                    else "Required reads are complete and audited. "
                                    "Interpret this evidence; do not exhaust health pagination. "
                                    "If diagnosis has a history_version, "
                                    "investigate with history tools "
                                    "before returning the final schema. Otherwise return final."
                                ),
                            },
                            allow_nan=False,
                            separators=(",", ":"),
                        )
                    )
                )
            output = graph.invoke({
                "messages": messages, "phase": phase, "repairs": 0,
                "harness_id": provenance["harness_id"],
                "harness": provenance,
            }, config)
        resumed: Any
        transport_repairs = 0
        transport_feedback: dict[str, str] | None = None
        while output.get("__interrupt__"):
            request = output["__interrupt__"][0].value
            remaining = (task.deadline - utc_now()).total_seconds()
            if remaining <= 0:
                raise ValidationError("deadline", "Root workflow elapsed-time bound exhausted.")
            if request["kind"] == "model":
                self._check_provider(task.generation_id, task.mode)
                assert task.lease_token is not None
                task = self.store.reserve_model_call(
                    task.id, task.lease_token, self._model_limit(task)
                )
                # Reserve before inference: failed calls/restarts never replenish the allowance.
                gateway.task = task
                receipts = self.store.tool_receipts(task.id)
                seen = {r["name"] for r in receipts if not r.get("error")}
                missing_reads = sorted(set(context["required_tools"]) - seen)
                remaining_turns = self._model_limit(task) - task.model_calls
                call_policy = {
                    "transport_contract": load_prompt("transport").content.removesuffix("\n"),
                    "transport_repair_attempt": transport_repairs,
                    "transport_repair_feedback": transport_feedback,
                    "read_evidence_reference": read_evidence_reference(
                        task.snapshot_id, receipts
                    ) if task.role == "operator_response" and phase != "plan" else None,
                    "history_reference_ids": history_reference_ids(receipts)
                    if task.role == "event_diagnosis" else None,
                    "model_turns_after_this_reply": remaining_turns,
                    "new_tool_calls_available": REGISTRY[task.role].tool_limit - task.tool_calls,
                    "mandatory_reads_outstanding": missing_reads,
                    "final_schema_source": "BOUND_CONTEXT.result_schema",
                    "final_only": remaining_turns == 0
                    or task.tool_calls >= REGISTRY[task.role].tool_limit
                    or (
                        task.role == "event_diagnosis"
                        and remaining_turns == 1
                        and {"history.read", "history.compare"} <= seen
                    )
                    or phase == "plan"
                    or critic
                    or reflection,
                    "preferred_action": "investigate_history_then_final"
                    if task.role == "event_diagnosis"
                    and task.history_version
                    and remaining_turns
                    and task.tool_calls < REGISTRY[task.role].tool_limit
                    else "final"
                    if not missing_reads or phase == "plan"
                    else "one_batch_of_all_independent_required_reads",
                    "review_scope": "Bounded health claims, not exhaustive pagination.",
                }
                if call_policy["final_only"]:
                    call_policy["preferred_action"] = "final"
                invocation_messages = [
                    *repair_model_messages(request["messages"]),
                    SystemMessage(
                        content=RUNTIME_ENVELOPE
                        + json.dumps(call_policy, allow_nan=False, separators=(",", ":"))
                    ),
                ]
                call_id = str(uuid4())
                started = time.monotonic()
                metadata: dict[str, Any] = {
                    "call_id": call_id,
                    "model.turn.index": task.model_calls,
                    "attempt_id": self._attempt_id,
                    "role": task.role,
                    "phase": phase,
                    "transport_repair_attempt": transport_repairs,
                    "mode": task.mode,
                    "lease_token_hash": hashlib.sha256(
                        (task.lease_token or "").encode()
                    ).hexdigest(),
                    "prompt_hash": None,
                    "agent_trace_id": self._agent_trace.get("trace_id"),
                    "agent_span_id": self._agent_trace.get("span_id"),
                    "harness": {key: value for key, value in provenance.items() if key != "policy"},
                }
                try:
                    schemas = [] if call_policy["final_only"] else self._schemas(task)
                    try:
                        view = model_context(
                            invocation_messages, receipts, schemas, limit=prompt_limit
                        )
                    except ValidationError as exc:
                        rejection(exc, 0, False, None)
                        raise
                    invocation_messages = view.messages
                    metadata["prompt_hash"] = hashlib.sha256(view.prompt.encode()).hexdigest()
                    metadata["context"] = view.metadata()
                    self._event(task, "model.started", metadata)
                    if view.stage or view.consolidated_receipts:
                        self._harness_event(task, "model.context_compacted", {
                            "phase": phase, "call_id": call_id, **view.metadata(),
                            "harness_id": provenance["harness_id"],
                            "prompt_sha256": metadata["prompt_hash"],
                        })
                    assert base_model is not None
                    model = base_model.bind_tools(schemas)
                    with self.telemetry.span(
                        f"generation.{task.role}.{phase}",
                        {
                            "task_id": task.id,
                            "role": task.role,
                            "phase": phase,
                            "mode": task.mode,
                            "call_id": call_id,
                            "prompt_hash": metadata["prompt_hash"],
                            "harness.id": provenance["harness_id"],
                            "harness.policy.sha256": provenance["policy_sha256"],
                            **({
                                "harness.asset.id": provenance["prompt_asset"]["prompt_id"],
                                "harness.asset.version": provenance["prompt_asset"]["version"],
                            } if provenance["prompt_asset"] is not None else {}),
                            "harness.catalog.sha256": self._prompt_catalog_sha256,
                            "harness.investigation.catalog.known": (
                                task.prompt_catalog_sha256 is not None
                            ),
                            "harness.bound_schema.sha256": provenance["bound_schema_sha256"],
                            "harness.implementation.sha256": content_hash(
                                provenance["implementation"]
                            ),
                            **{
                                f"harness.template.{key}.sha256": value
                                for key, value in provenance["templates"].items()
                            },
                            "context.stage": view.stage,
                            "context.original_chars": view.original_chars,
                            "context.prompt_chars": len(view.prompt),
                            "langfuse.observation.input": json.dumps(
                                [
                                    {
                                        "role": {"human": "user", "ai": "assistant"}.get(
                                            message.type, message.type
                                        ),
                                        "content": message.content,
                                        **(
                                            {"tool_calls": message.tool_calls}
                                            if isinstance(message, AIMessage) and message.tool_calls
                                            else {}
                                        ),
                                        **(
                                            {"tool_call_id": message.tool_call_id}
                                            if isinstance(message, ToolMessage)
                                            else {}
                                        ),
                                    }
                                    for message in invocation_messages
                                ],
                                allow_nan=False,
                            ),
                        },
                    ) as span:
                        remaining = (task.deadline - utc_now()).total_seconds()
                        if remaining <= 0:
                            raise ValidationError("deadline", "Root elapsed-time bound exhausted.")
                        response = model.invoke(
                            invocation_messages,
                            timeout=min(float(MODEL_TIMEOUT_SECONDS), remaining),
                        )
                        requested_tools = list(
                            dict.fromkeys(
                                call["name"]
                                if call["name"] in role_policy(
                                    task.role, task.decision_policy
                                ).tools
                                else "unauthorized tool"
                                for call in response.tool_calls
                            )
                        )
                        repair_feedback = [
                            json.loads(message.content)["repair"]
                            for message in invocation_messages
                            if isinstance(message, HumanMessage)
                            and message.additional_kwargs.get("validation_repair") is True
                            and isinstance(message.content, str)
                        ]
                        action = (
                            "Request tools: " + ", ".join(requested_tools)
                            if requested_tools
                            else "Repair answer"
                            if repair_feedback
                            else "Submit " + phase
                        )
                        span.update_name(
                            f"Turn {task.model_calls}: {ROLE_NAMES[task.role]} / {action}"
                        )
                        span.set_attribute("model.repair_attempt", len(repair_feedback))
                        span.set_attribute("model.tool_count", len(response.tool_calls))
                        for tool_call in response.tool_calls:
                            span.add_event(
                                "model.tool_selected",
                                {
                                    "call_id": tool_call["id"],
                                    "model_call_id": call_id,
                                    "tool": (
                                        tool_call["name"]
                                        if tool_call["name"] in role_policy(
                                            task.role, task.decision_policy
                                        ).tools
                                        else "unauthorized tool"
                                    ),
                                    "source": "observed_model_tool_request",
                                    "model.turn.index": task.model_calls,
                                },
                            )
                        if response.usage_metadata:
                            for key in ("input_tokens", "output_tokens", "total_tokens"):
                                span.set_attribute(
                                    f"gen_ai.usage.{key}", response.usage_metadata[key]
                                )
                        span.set_attribute(
                            "langfuse.observation.output",
                            json.dumps(
                                {
                                    "turn": task.model_calls,
                                    "action": action,
                                    "repair_codes": repair_feedback,
                                    "content": response.content,
                                    "tool_calls": response.tool_calls,
                                },
                                allow_nan=False,
                            ),
                        )
                        metadata.update(response.response_metadata)
                        if (
                            task.mode == "live"
                            and response.response_metadata.get("mode") == "scripted"
                        ):
                            raise ValidationError("mode_mismatch", "Scripted output is not live.")
                        if response.tool_calls and (
                            remaining_turns == 0 or phase == "plan" or critic or reflection
                        ):
                            raise ValidationError(
                                "final_turn_reserved",
                                "This reply must be a structured final, not another tool request.",
                            )
                        for key, value in metadata.items():
                            if value is not None and isinstance(value, (str, bool, int, float)):
                                span.set_attribute(key, value)
                    resumed = response
                except Exception as exc:
                    metadata["error"] = getattr(exc, "code", "model_failed")
                    metadata.update(getattr(exc, "metadata", {}))
                    if task.mode == "live" and metadata["error"] in {"proxy_auth", "proxy_quota"}:
                        self._provider_error = metadata["error"]
                    if metadata["error"] == "invalid_structured_output" and (
                        task.decision_policy == "llm-diagnosis-v1"
                    ):
                        # Envelope repair is separate from schema repair, but spends the same
                        # persisted model-call budget and deadline; auth/quota do not enter it.
                        transport_feedback = transport_diagnostic(
                            metadata.get("response_validation_stage")
                        )
                        retry = transport_repairs < SCHEMA_REPAIR_LIMIT and remaining_turns > 0
                        metadata["transport_retry_scheduled"] = retry
                        metadata["transport_repair_feedback"] = transport_feedback
                        self._harness_event(
                            task,
                            "validation.repair_requested" if retry else "validation.rejected",
                            {
                                **transport_feedback,
                                "phase": phase,
                                "model_call_id": call_id,
                                "repair_requested": retry,
                                "repair_attempt": transport_repairs,
                                "repair_limit": SCHEMA_REPAIR_LIMIT,
                            },
                        )
                        if retry:
                            transport_repairs += 1
                            continue
                    raise
                finally:
                    metadata["duration_ms"] = (time.monotonic() - started) * 1000
                    record = getattr(self.store, "record_model_call", None)
                    if record is not None:
                        record(task.id, task.lease_token, call_id, metadata)
                    else:
                        self._event(task, "model.completed", metadata)
            else:
                results = [gateway.dispatch(call) for call in request["calls"]]
                task = gateway.task
                resumed = tool_messages(request["calls"], results)
            output = graph.invoke(Command(resume=resumed), config)
        if output.get("failure"):
            raise ValidationError(
                output["failure"], "Structured output repair allowance exhausted."
            )
        if phase == "answer" and (
            task.role == "operator_response" or task.decision_policy == "llm-diagnosis-v1"
        ):
            assert isinstance(resumed, AIMessage) and isinstance(resumed.content, str)
            authored = AgentResult.model_validate(parse_json(resumed.content))
            added = set(output["parsed"]["evidence_ids"]) - set(authored.evidence_ids)
            if added:
                self._event(
                    task,
                    "evidence.bound",
                    {
                        "added_evidence_ids": sorted(added),
                        "authority": "immutable claim ledger and successful evidence.get receipts",
                        "authored_result_sha256": content_hash(authored.model_dump(mode="json")),
                        "bound_result_sha256": content_hash(output["parsed"]),
                    },
                )
        return output["parsed"], task

    def _review_interpretation(
        self,
        task: AgentTask,
        snapshot: WindowSnapshot,
        result: AgentResult,
    ) -> tuple[AgentResult, AgentTask]:
        """Review all prose units, allow bounded revisions, and withhold persistent rejection."""
        from subsea_copilot.grounding import review_material_hash

        rounds = []
        previous_result = None
        previous_assessment = None
        compact = task.decision_policy == "llm-diagnosis-v1"
        limit = FRESH_REFLECTION_LIMIT if compact else REFLECTION_LIMIT
        # Three author revisions permit four reviews; acceptance stops the loop immediately.
        for index in range(limit + 1):
            if result.interpretation is not None:
                self._event(
                    task,
                    "agent.draft",
                    {
                        "agent": ROLE_NAMES[task.role],
                        "role": task.role,
                        "status": "draft_pending_review",
                        "round": index + 1,
                        "text": result.interpretation.answer.text,
                        "references": result.interpretation.answer.references,
                    },
                )
            self._event(
                task,
                "agent.review_requested",
                {
                    "agent": "Grounding Reviewer",
                    "role": "grounding_reviewer",
                    "round": index + 1,
                    "candidate_hash": candidate_hash(result),
                    "purpose": "Check each explanation against its cited evidence "
                    "before releasing the report",
                },
            )
            reviewed, task = self._graph(
                task, snapshot, f"critic-{index}", candidate=result,
                criticism=previous_assessment, previous_candidate=previous_result,
            )
            assessment = GroundingAssessment.model_validate(reviewed)
            sources = source_texts(
                result, snapshot, self.store.tool_receipts(task.id), task.knowledge_packet
            )
            rounds.append(
                GroundingRound(
                    candidate_hash=candidate_hash(result), assessment=assessment,
                    material_hash=review_material_hash(task, result, sources) if compact else None,
                )
            )
            self._event(
                task,
                "answer.critique",
                {
                    "round": index + 1,
                    "decision": assessment.decision,
                    "issues": sum(check.verdict != "supported" for check in assessment.checks),
                    "checks": [check.model_dump(mode="json") for check in assessment.checks],
                },
            )
            if assessment.decision == "accept":
                task.interpretation_review = InterpretationReview(
                    rounds=rounds,
                    source_hash=content_hash({key: value for key, value in sources.items()}),
                    protocol="semantic-grounding-v2" if compact else "grounding-v1",
                )
                return result, task
            if index < limit:
                previous_result, previous_assessment = result, assessment
                revised, task = self._graph(
                    task,
                    snapshot,
                    "reflection" if index == 0 else f"reflection-{index}",
                    candidate=result,
                    criticism=assessment,
                )
                result = AgentResult.model_validate(revised)
        raise ValidationError(
            "grounding_rejected",
            "Independent review still found unsupported language after revision; report withheld.",
            details={
                "phase": f"critic-{limit}",
                "review_round": limit + 1,
                "rejected_checks": [
                    check.model_dump(mode="json") for check in assessment.checks
                    if check.verdict != "supported"
                ],
            },
        )

    def _orchestrate(self, task: AgentTask, snapshot: WindowSnapshot) -> AgentTask | None:
        """Persist a serial plan and one child at a time; None means an atomic parent wait."""
        parsed: dict[str, Any] | None = None
        if not task.plan:
            parsed, task = self._graph(task, snapshot, "plan")
            task.plan = parsed["steps"]
            task = self._save(task)
        if "reuse" in task.plan:
            if self.store.reuse_task_ids(task.id):
                return task
            if parsed is None:
                parsed, task = self._graph(task, snapshot, "plan")
            selected = checked_plan_sources(
                WorkPlan.model_validate(parsed), bool(task.history_version),
                self._context(task, snapshot, "plan")["compatible_tasks"],
            )
            assert task.lease_token is not None
            self.store.authorize_reuse(task.id, [t["id"] for t in selected], task.lease_token)
            return task
        checked_plan_sources(WorkPlan(steps=task.plan), bool(task.history_version), [])
        for index, step in enumerate(task.plan):
            if step == "answer":
                return task
            role: AgentRole = "sensor_quality" if step == "quality" else "event_diagnosis"
            identifier = str(uuid5(NAMESPACE_URL, f"{task.id}:plan:1:step:{index}"))
            # Child identity survives a crash after commit, preventing duplicate specialist work.
            existing = self._optional_task(identifier)
            if existing is not None:
                if (
                    existing.parent_id != task.id
                    or existing.role != role
                    or existing.snapshot_id != snapshot.id
                ):
                    raise ValidationError("child_conflict", "Durable child identity changed scope.")
                if existing.state in {"FAILED", "CANCELLED"}:
                    raise ValidationError(
                        "child_failed",
                        f"{ROLE_NAMES[existing.role]} ({existing.id}) failed with "
                        f"{existing.error_code or existing.state}; synthesis blocked.",
                        details={
                            "failed_role": existing.role,
                            "failed_task_id": existing.id,
                            "cause_code": existing.error_code or existing.state,
                        },
                    )
                if existing.state in {"SUCCEEDED", "ABSTAINED"}:
                    assert existing.result is not None
                    gateway = ToolGateway(self.store, existing, snapshot, self.telemetry)
                    validate_result(
                        existing.result,
                        existing,
                        snapshot,
                        self.store.tool_receipts(existing.id),
                        gateway.dependencies(),
                    )
                    continue
            child = AgentTask(
                id=identifier,
                root_id=task.root_id,
                parent_id=task.id,
                tenant_id=task.tenant_id,
                site_id=task.site_id,
                generation_id=task.generation_id,
                snapshot_id=task.snapshot_id,
                episode_id=task.episode_id,
                role=role,
                purpose=REGISTRY[role].purpose,
                question=task.question,
                mode=task.mode,
                deadline=task.deadline,
                automatic=task.automatic,
                history_version=task.history_version,
                prompt_catalog_sha256=task.prompt_catalog_sha256,
                knowledge_packet=task.knowledge_packet,
                decision_policy=task.decision_policy,
            )
            self.store.create_child(child, index, plan_revision=1, lease_token=task.lease_token)
            parent = self.store.get_task(task.id)
            if parent.state not in {
                "WAITING_ON_CHILD",
                "QUEUED",
                "SUCCEEDED",
                "ABSTAINED",
                "FAILED",
                "CANCELLED",
            }:
                raise ValidationError(
                    "child_wait_atomicity",
                    "Child creation must atomically persist the parent wait.",
                )
            return None
        raise ValidationError("plan", "Plan has no answer step.")

    def run_once(self) -> bool:
        """Claim one task; execute, wait or finalize only while its worker lease remains valid."""
        self.completed_task = None
        task = self._claim_task()
        if task is None:
            return False
        try:
            assert task.lease_token is not None
            begin_attempt = getattr(self.store, "begin_attempt", None)
            self._attempt_id = (
                begin_attempt(task.id, task.lease_token) if begin_attempt else uuid4().hex
            )
            latest_trace = getattr(self.store, "latest_task_trace", lambda task_id: None)
            first_trace = getattr(self.store, "first_task_trace", lambda task_id: None)
            investigation_trace = first_trace(task.root_id)
            unified = investigation_trace is None or (
                investigation_trace.get("trace_layout") == "investigation-v1"
            )
            parent_trace = None
            if unified and investigation_trace:
                parent_trace = (
                    latest_trace(task.parent_id) if task.parent_id else investigation_trace
                )
                if not parent_trace or parent_trace.get("trace_id") != investigation_trace.get(
                    "trace_id"
                ):
                    raise ValidationError(
                        "trace_context", "Investigation handoff context mismatch."
                    )
            elif unified and task.parent_id:
                raise ValidationError("trace_context", "Investigation root context is missing.")
            linked = (
                latest_trace(task.id)
                or (latest_trace(task.parent_id) if task.parent_id else None)
                or {}
            )
            with self.telemetry.span(
                "agent.investigation" if unified and parent_trace is None else f"agent.{task.role}",
                {
                    "task_id": task.id,
                    "root_id": task.root_id,
                    "parent_id": task.parent_id or "",
                    "tenant_id": task.tenant_id,
                    "site_id": task.site_id,
                    "replay_generation_id": task.generation_id,
                    "episode_id": task.episode_id or "",
                    "snapshot_id": task.snapshot_id,
                    "role": task.role,
                    "mode": task.mode,
                    "attempt_id": self._attempt_id,
                    "linked_trace_id": linked.get("trace_id", ""),
                    "linked_span_id": linked.get("span_id", ""),
                    **(
                        {"langfuse.trace.name": f"Subsea check {task.root_id[:8]} / {task.mode}"}
                        if parent_trace is None else {}
                    ),
                },
                root=parent_trace is None,
                parent=parent_trace,
            ) as agent_span:
                trace_metadata: dict[str, Any] = getattr(
                    self.telemetry, "trace_metadata", lambda: {}
                )()
                if unified:
                    trace_metadata["trace_layout"] = "investigation-v1"
                self._agent_trace = trace_metadata
                self._event(
                    task,
                    "task.started",
                    {
                        "role": task.role,
                        "mode": task.mode,
                        "attempt_id": self._attempt_id,
                        **trace_metadata,
                    },
                )
                snapshot = self.store.get_window(task.snapshot_id)
                if snapshot is None:
                    raise ValidationError("snapshot", "Pinned snapshot unavailable.")
                if task.decision_policy == "llm-diagnosis-v1":
                    snapshot = measurement_snapshot(snapshot)
                if task.deadline <= utc_now():
                    raise ValidationError("deadline", "Root workflow deadline exhausted.")
                agent_span.set_attribute(
                    "langfuse.observation.input",
                    json.dumps(
                        {
                            "question": task.question,
                            "role": task.role,
                            "task_id": task.id,
                            "root_id": task.root_id,
                            "parent_id": task.parent_id,
                            "snapshot_id": snapshot.id,
                            "mode": task.mode,
                            "model_calls_before_attempt": task.model_calls,
                            "tool_calls_before_attempt": task.tool_calls,
                        }
                    ),
                )
                if task.role == "operator_response":
                    agent_span.set_attribute(
                        "langfuse.trace.input",
                        json.dumps(
                            {
                                "question": task.question,
                                "snapshot_id": snapshot.id,
                                "root_task_id": task.root_id,
                                "mode": task.mode,
                            }
                        ),
                    )
                if task.role == "operator_response":
                    coordinator_id = task.id
                    task = self._orchestrate(task, snapshot)
                    if task is None:
                        coordinator = self.store.get_task(coordinator_id)
                        agent_span.set_attribute("outcome", coordinator.state)
                        agent_span.set_attribute(
                            "langfuse.observation.output",
                            json.dumps(
                                {
                                    "state": coordinator.state,
                                    "plan": coordinator.plan,
                                    "handoffs": [
                                        {
                                            "task_id": child.id,
                                            "role": child.role,
                                            "state": child.state,
                                        }
                                        for child in self.store.list_tasks(
                                            coordinator.generation_id
                                        )
                                        if child.parent_id == coordinator.id
                                    ],
                                }
                            ),
                        )
                        return True
                parsed, task = self._graph(task, snapshot, "answer")
                result = AgentResult.model_validate(parsed)
                if task.role == "operator_response" and task.response_protocol == "engineer-v2":
                    try:
                        result, task = self._review_interpretation(task, snapshot, result)
                    except ValidationError as exc:
                        if exc.code == "grounding_rejected" and exc.details:
                            failure_output = json.dumps({
                                "state": "FAILED", "error_code": exc.code,
                                "failed_role": "grounding_reviewer", **exc.details,
                                "accepted_result": None,
                            })
                            agent_span.set_attribute("failure.phase", str(exc.details["phase"]))
                            agent_span.set_attribute(
                                "langfuse.observation.output", failure_output,
                            )
                            agent_span.set_attribute("langfuse.trace.output", failure_output)
                        raise
                task.result = result
                task.answer = render_result(result, task, snapshot)
                if result.investigation is not None:
                    from subsea_copilot.investigation import render_investigation

                    sources = [task]
                    if task.role == "operator_response":
                        sources = [
                            child
                            for child in self._gateway(task, snapshot).dependencies()
                            if child.role == "event_diagnosis"
                        ]
                    history_receipts = [
                        receipt
                        for source in sources
                        for receipt in self.store.tool_receipts(source.id)
                    ]
                    task.answer += "\n" + render_investigation(
                        result.investigation, history_receipts
                    )
                if result.interpretation is not None:
                    from subsea_copilot.interpretation import render_interpretation

                    task.answer = (
                        render_interpretation(result.interpretation, task)
                        + "\n\nCHECKED EVIDENCE\n"
                        + task.answer
                    )
                task.state = "SUCCEEDED" if result.outcome == "supported" else "ABSTAINED"
                if task.deadline <= utc_now():
                    raise ValidationError("deadline", "Report completion exceeded root deadline.")
                if task.response_protocol == "engineer-v2":
                    # Recheck the accepted review against the final result before publication.
                    self._accept(
                        result.model_dump_json(), task, snapshot, self._gateway(task, snapshot)
                    )
                task = self._save(task)
                recipient = "engineer"
                if task.parent_id:
                    parent = self.store.get_task(task.parent_id)
                    recipient = (
                        "event_diagnosis"
                        if task.role == "sensor_quality" and "diagnosis" in parent.plan
                        else parent.role
                    )
                self._event(
                    task,
                    "answer.checked",
                    {
                        "state": task.state,
                        "mode": task.mode,
                        "claim_refs": result.claim_refs,
                        "agent": ROLE_NAMES[task.role],
                        "role": task.role,
                        "public_output": task.answer,
                        "to_role": recipient,
                    },
                )
                agent_span.set_attribute("outcome", task.state)
                agent_span.set_attribute(
                    "langfuse.observation.output",
                    json.dumps(
                        {
                            "state": task.state,
                            "accepted_result": result.model_dump(mode="json"),
                            "public_output": task.answer,
                            "to_role": recipient,
                            "model_calls": task.model_calls,
                            "tool_calls": task.tool_calls,
                        }
                    ),
                )
                if task.role == "operator_response":
                    agent_span.set_attribute(
                        "langfuse.trace.output",
                        json.dumps(
                            {
                                "state": task.state,
                                "accepted_result": result.model_dump(mode="json"),
                                "public_output": task.answer,
                            }
                        ),
                    )
                self.completed_task = task
        except Exception as exc:
            code = getattr(exc, "code", "runtime_failed")
            if isinstance(exc, psycopg.errors.UndefinedTable):
                code = "checkpoint_uninitialized"
            elif isinstance(exc, psycopg.Error):
                code = "database_error"
            frames = traceback.extract_tb(exc.__traceback__)
            origin = frames[-1] if frames else None
            diagnostic = {
                "error_code": code,
                "error_type": type(exc).__name__,
                "sqlstate": getattr(exc, "sqlstate", None),
                "origin": f"{Path(origin.filename).name}:{origin.lineno}" if origin else None,
                "attempt_id": self._attempt_id,
            }
            if code in {"grounding_rejected", "child_failed"} and (
                isinstance(exc, ValidationError) and exc.details
            ):
                diagnostic.update(exc.details)
            self._last_error = diagnostic
            LOGGER.error(
                "Agent execution failed task_id=%s diagnostic=%s",
                task.id if task else None,
                diagnostic,
            )
            # Never publish under an expired/replaced worker lease.
            if task is not None:
                current = self._optional_task(task.id)
                if (
                    current is not None
                    and current.state
                    not in {
                        "SUCCEEDED",
                        "ABSTAINED",
                        "FAILED",
                        "CANCELLED",
                    }
                    and current.lease_token == task.lease_token
                ):
                    current.state = "FAILED"
                    current.error_code = code
                    current.error_message = (
                        f"{type(exc).__name__}: {code}; no agent result accepted."
                    )
                    if code == "child_failed" and isinstance(exc, ValidationError) and exc.details:
                        current.error_message = f"{exc} Report withheld."
                    if code == "grounding_rejected" and isinstance(exc, ValidationError):
                        checks = (exc.details or {}).get("rejected_checks", [])
                        if isinstance(checks, list):
                            reasons = [
                                str(check["reason"]) for check in checks
                                if isinstance(check, dict) and "reason" in check
                            ]
                            current.error_message = (
                                f"Grounding Reviewer rejected round "
                                f"{(exc.details or {}).get('review_round', 'unknown')}: "
                                f"{'; '.join(reasons) or str(exc)} Report withheld."
                            )
                    try:
                        current = self._save(current)
                    except Exception as save_error:
                        reason = getattr(save_error, "reason", getattr(save_error, "code", None))
                        if reason not in {"stale_lease", "version_conflict", "stale_version"}:
                            LOGGER.error(
                                "Failure finalization rejected task_id=%s error_type=%s",
                                task.id,
                                type(save_error).__name__,
                            )
                            raise
                        LOGGER.warning(
                            "Failure finalization fenced task_id=%s reason=%s", task.id, reason
                        )
                    else:
                        self._event(current, "agent.failed", diagnostic)
        return True

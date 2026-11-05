"""Durable serial business orchestration around the shared checkpointed graph."""

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
from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command

from subsea_copilot.contracts import (
    AgentResult,
    AgentRole,
    AgentTask,
    Mode,
    ReplaySession,
    WindowSnapshot,
    utc_now,
)
from subsea_copilot.runtime.agent import WorkPlan, build_graph, tool_messages
from subsea_copilot.runtime.gateway import ToolGateway
from subsea_copilot.runtime.registry import REGISTRY, tool_schemas
from subsea_copilot.validation import (
    ValidationError,
    compatible,
    question_requires_location,
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
    def __init__(
        self,
        store: Store,
        model_factory: Callable[[AgentRole, Mode], BaseChatModel],
        checkpointer: BaseCheckpointSaver[Any] | None,
        telemetry: Telemetry,
    ) -> None:
        self.store, self.model_factory = store, model_factory
        self.checkpointer, self.telemetry = checkpointer, telemetry
        self.owner = "agent-worker-" + uuid4().hex
        self._provider_error: str | None = None
        self._attempt_id = ""
        self._agent_trace: dict[str, Any] = {}
        self._last_error: dict[str, Any] | None = None

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
        from datetime import timedelta

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
        if existing is None:
            self._check_provider(session.id, session.mode)
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
            deadline=utc_now() + timedelta(seconds=300),
            automatic=automatic,
            idempotency_key=idempotency_key,
        )
        return self.store.create_task(task)

    def _event(self, task: AgentTask, name: str, payload: dict[str, Any]) -> None:
        self.store.publish_event(
            task.generation_id, name, payload, snapshot_id=task.snapshot_id, task_id=task.id
        )

    def _save(self, task: AgentTask) -> AgentTask:
        return self.store.save_task(
            task, expected_version=task.version, lease_token=task.lease_token
        )

    def _claim_task(self) -> AgentTask | None:
        return self.store.claim_task(self.owner, ttl_seconds=360)

    def _gateway(self, task: AgentTask, snapshot: WindowSnapshot) -> ToolGateway:
        return ToolGateway(self.store, task, snapshot, self.telemetry)

    def _schemas(self, task: AgentTask) -> list[dict[str, Any]]:
        return tool_schemas(task.role)

    def _prompt_name(self, task: AgentTask) -> str:
        return PROMPT_NAMES[task.role]

    def _accept(
        self,
        value: str,
        task: AgentTask,
        snapshot: WindowSnapshot,
        gateway: ToolGateway,
    ) -> AgentResult:
        return validate_result(
            value,
            task,
            snapshot,
            self.store.tool_receipts(task.id),
            gateway.dependencies(),
        )

    def _required_intake(
        self,
        task: AgentTask,
        snapshot: WindowSnapshot,
        context: dict[str, Any],
        gateway: ToolGateway,
    ) -> tuple[list[dict[str, Any]], AgentTask]:
        """Application-owned reads, not invented model requests or model generations."""
        names = set(context["required_tools"])
        if task.role == "event_diagnosis" or context.get("baseline"):
            if snapshot.event.eligible_location:
                names.add("location.fit")
        outputs = []
        for name in sorted(names):
            targets = context["compatible_tasks"] if name == "task.result" else [None]
            if task.role == "event_diagnosis" and name == "task.result":
                targets = [t for t in targets if t is not None and t["role"] == "sensor_quality"]
            for target in targets:
                arguments = dict(context["scope"])
                if target is not None:
                    arguments["task_id"] = target["id"]
                if name == "evidence.get":
                    arguments["ids"] = sorted(
                        {ref for t in context["compatible_tasks"] for ref in t["evidence_ids"]}
                    )
                identity = json.dumps(
                    [task.id, snapshot.id, name, arguments, "required-intake-v1"], sort_keys=True
                )
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
        return outputs, gateway.task

    def _context(self, task: AgentTask, snapshot: WindowSnapshot, phase: str) -> dict[str, Any]:
        scope = {
            "site_id": snapshot.site_id,
            "snapshot_id": snapshot.id,
            "pack_version": snapshot.pack_version,
            "baseline_version": snapshot.baseline_version,
            "parameter_version": snapshot.parameter_version,
        }
        candidates = [
            t
            for t in self.store.list_tasks(task.generation_id)
            if t.role != "operator_response" and compatible(task, t, snapshot)
        ]
        checked_candidates = []
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
        if phase != "plan":
            result_schema["properties"]["summary"] = {"type": "string", "const": ""}
            if task.role == "sensor_quality":
                result_schema["properties"]["hypothesis"] = {"type": "null"}
                result_schema["properties"]["recommendation_ids"] = {
                    "type": "array",
                    "maxItems": 0,
                }
        return {
            "phase": phase,
            "role": task.role,
            "mode": task.mode,
            "scope": scope,
            "question": task.question,
            "task_id": task.id,
            "plan": task.plan,
            "compatible_tasks": [
                {
                    "id": t.id,
                    "role": t.role,
                    "state": t.state,
                    "claim_refs": t.result.claim_refs,
                    "evidence_ids": t.result.evidence_ids,
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
            "required_tools": sorted(REGISTRY[task.role].required),
            "result_schema": result_schema,
            "batch_instruction": (
                "Planning uses no tools. Answer: batch independent required reads in one reply. "
                "Then submit final; health pagination is not an exhaustive-review obligation."
            ),
        }

    def _graph(
        self, task: AgentTask, snapshot: WindowSnapshot, phase: str
    ) -> tuple[dict[str, Any], AgentTask]:
        gateway = self._gateway(task, snapshot)

        def validate(value: str) -> AgentResult:
            current = self.store.get_task(task.id)
            with self.telemetry.span("guardrail", {"task_id": task.id, "role": task.role}):
                return self._accept(value, current, snapshot, gateway)

        graph = build_graph(self.checkpointer, validate)
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
        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 50}
        prompt_path = Path(__file__).resolve().parents[3] / "prompts" / self._prompt_name(task)
        prompt = prompt_path.read_text(encoding="utf-8")
        context = self._context(task, snapshot, phase)
        messages: list[AnyMessage] = [
            SystemMessage(
                content=prompt + "\nBOUND_CONTEXT\n" + json.dumps(context, allow_nan=False)
            )
        ]
        prior = graph.get_state(config) if self.checkpointer is not None else None
        if prior and prior.values:
            if not prior.next:
                if prior.values.get("failure"):
                    raise ValidationError(prior.values["failure"], "Previously rejected output.")
                return dict(prior.values["parsed"]), task
            output = graph.invoke(None, config)
        else:
            if phase != "plan":
                intake, task = self._required_intake(task, snapshot, context, gateway)
                messages.append(
                    HumanMessage(
                        content=json.dumps(
                            {
                                "application_intake": intake,
                                "instruction": (
                                    "Required reads are complete and audited. "
                                    "Interpret this evidence and return the exact final schema; "
                                    "do not exhaust health pagination."
                                ),
                            },
                            allow_nan=False,
                        )
                    )
                )
            output = graph.invoke({"messages": messages, "phase": phase, "repairs": 0}, config)
        # Instantiate a distinct model for this independently persisted role task.
        model = self.model_factory(task.role, task.mode).bind_tools(
            [] if phase == "plan" else self._schemas(task)
        )
        resumed: Any
        while output.get("__interrupt__"):
            request = output["__interrupt__"][0].value
            remaining = (task.deadline - utc_now()).total_seconds()
            if remaining <= 0:
                raise ValidationError("deadline", "Root workflow elapsed-time bound exhausted.")
            if request["kind"] == "model":
                self._check_provider(task.generation_id, task.mode)
                assert task.lease_token is not None
                task = self.store.reserve_model_call(
                    task.id, task.lease_token, REGISTRY[task.role].model_limit
                )
                gateway.task = task
                receipts = self.store.tool_receipts(task.id)
                seen = {r["name"] for r in receipts if not r.get("error")}
                missing_reads = sorted(set(context["required_tools"]) - seen)
                remaining_turns = REGISTRY[task.role].model_limit - task.model_calls
                call_policy = {
                    "model_turns_after_this_reply": remaining_turns,
                    "new_tool_calls_available": REGISTRY[task.role].tool_limit - task.tool_calls,
                    "mandatory_reads_outstanding": missing_reads,
                    "required_final_schema": context["result_schema"],
                    "final_only": remaining_turns == 0 or phase == "plan",
                    "preferred_action": "final"
                    if not missing_reads or phase == "plan"
                    else "one_batch_of_all_independent_required_reads",
                    "review_scope": "Bounded health claims, not exhaustive pagination.",
                }
                invocation_messages = [
                    *request["messages"],
                    SystemMessage(
                        content="RUNTIME_REPLY_CONSTRAINTS\n"
                        + json.dumps(call_policy, allow_nan=False)
                    ),
                ]
                call_id = str(uuid4())
                started = time.monotonic()
                metadata: dict[str, Any] = {
                    "call_id": call_id,
                    "attempt_id": self._attempt_id,
                    "role": task.role,
                    "mode": task.mode,
                    "lease_token_hash": hashlib.sha256(
                        (task.lease_token or "").encode()
                    ).hexdigest(),
                    "prompt_hash": hashlib.sha256(prompt.encode()).hexdigest(),
                    "agent_trace_id": self._agent_trace.get("trace_id"),
                    "agent_span_id": self._agent_trace.get("span_id"),
                }
                self._event(task, "model.started", metadata)
                try:
                    with self.telemetry.span(
                        "generation",
                        {
                            "task_id": task.id,
                            "role": task.role,
                            "mode": task.mode,
                            "call_id": call_id,
                            "prompt_hash": metadata["prompt_hash"],
                        },
                    ) as span:
                        remaining = (task.deadline - utc_now()).total_seconds()
                        if remaining <= 0:
                            raise ValidationError("deadline", "Root elapsed-time bound exhausted.")
                        response = model.invoke(invocation_messages, timeout=min(60.0, remaining))
                        metadata.update(response.response_metadata)
                        if (
                            task.mode == "live"
                            and response.response_metadata.get("mode") == "scripted"
                        ):
                            raise ValidationError("mode_mismatch", "Scripted output is not live.")
                        if response.tool_calls and (remaining_turns == 0 or phase == "plan"):
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
            raise ValidationError(output["failure"], "Structured output rejected after one repair.")
        return output["parsed"], task

    def _orchestrate(self, task: AgentTask, snapshot: WindowSnapshot) -> AgentTask | None:
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
            selected_ids = set(parsed["reuse_task_ids"])
            selected = [
                t
                for t in self._context(task, snapshot, "plan")["compatible_tasks"]
                if t["id"] in selected_ids
            ]
            if len(selected) != len(selected_ids):
                raise ValidationError("reuse", "Reuse proposal cites incompatible source tasks.")
            if not any(t["role"] == "sensor_quality" for t in selected):
                raise ValidationError("reuse", "No compatible accepted quality result to reuse.")
            assert task.lease_token is not None
            self.store.authorize_reuse(task.id, [t["id"] for t in selected], task.lease_token)
            return task
        for index, step in enumerate(task.plan):
            if step == "answer":
                return task
            role: AgentRole = "sensor_quality" if step == "quality" else "event_diagnosis"
            identifier = str(uuid5(NAMESPACE_URL, f"{task.id}:plan:1:step:{index}"))
            existing = self._optional_task(identifier)
            if existing is not None:
                if (
                    existing.parent_id != task.id
                    or existing.role != role
                    or existing.snapshot_id != snapshot.id
                ):
                    raise ValidationError("child_conflict", "Durable child identity changed scope.")
                if existing.state in {"FAILED", "CANCELLED"}:
                    raise ValidationError("child_failed", "Specialist failure blocks synthesis.")
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
            linked = (
                latest_trace(task.id)
                or (latest_trace(task.parent_id) if task.parent_id else None)
                or {}
            )
            with self.telemetry.span(
                "agent",
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
                },
                root=True,
            ):
                trace_metadata: dict[str, Any] = getattr(
                    self.telemetry, "trace_metadata", lambda: {}
                )()
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
                if task.deadline <= utc_now():
                    raise ValidationError("deadline", "Root workflow deadline exhausted.")
                if task.role == "operator_response":
                    task = self._orchestrate(task, snapshot)
                    if task is None:
                        return True
                parsed, task = self._graph(task, snapshot, "answer")
                result = AgentResult.model_validate(parsed)
                task.result = result
                task.answer = render_result(result, task, snapshot)
                task.state = "SUCCEEDED" if result.outcome == "supported" else "ABSTAINED"
                task = self._save(task)
                self._event(
                    task,
                    "answer.checked",
                    {"state": task.state, "mode": task.mode, "claim_refs": result.claim_refs},
                )
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

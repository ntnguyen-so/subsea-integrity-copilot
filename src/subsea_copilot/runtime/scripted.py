"""Offline contract transport, not evidence of live reasoning or model quality."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field


class ScriptedChatModel(BaseChatModel):
    role: str
    bound_schemas: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted-offline-contract"

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedChatModel:
        return self.model_copy(update={"bound_schemas": list(tools)})

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        context = json.loads(
            next(
                m.content.split("\nBOUND_CONTEXT\n", 1)[1]
                for m in messages
                if isinstance(m, SystemMessage) and isinstance(m.content, str)
            )
        )
        scope = context["scope"]
        tool_outputs = [
            json.loads(m.content)
            for m in messages
            if isinstance(m, ToolMessage) and isinstance(m.content, str)
        ]
        for message in messages:
            if isinstance(message, HumanMessage) and isinstance(message.content, str):
                try:
                    data = json.loads(message.content)
                except ValueError:
                    continue
                if isinstance(data, dict) and "application_intake" in data:
                    tool_outputs.extend(entry["output"] for entry in data["application_intake"])
        if context["phase"] == "plan":
            question = context["question"].lower()
            needs_diagnosis = (
                any(
                    word in question
                    for word in (
                        "cause",
                        "leak",
                        "where",
                        "location",
                        "happen",
                        "diagnos",
                        "event",
                    )
                )
                or context["requires_location"]
            )
            compatible_tasks = context["compatible_tasks"]
            has_diagnosis = any(t["role"] == "event_diagnosis" for t in compatible_tasks)
            if any(word in question for word in ("summary", "summarize", "saved", "reuse")):
                needs_diagnosis = has_diagnosis
            reuse_ids = []
            if compatible_tasks and (not needs_diagnosis or has_diagnosis):
                steps = ["reuse", "answer"]
                reuse_ids = [
                    t["id"]
                    for t in compatible_tasks
                    if needs_diagnosis or t["role"] == "sensor_quality"
                ]
            elif needs_diagnosis:
                steps = ["quality", "diagnosis", "answer"]
            else:
                steps = ["quality", "answer"]
            message = AIMessage(content=json.dumps({"steps": steps, "reuse_task_ids": reuse_ids}))
        elif not tool_outputs:
            requests = []
            names = list(context["required_tools"])
            if (self.role == "event_diagnosis" or context.get("baseline")) and (
                context["eligible_location"]
            ):
                names.append("location.fit")
            for name in names:
                if name == "task.result":
                    candidates = context["compatible_tasks"]
                    if self.role == "event_diagnosis":
                        candidates = [t for t in candidates if t["role"] == "sensor_quality"]
                    for candidate in candidates:
                        requests.append(
                            {
                                "id": uuid4().hex,
                                "name": name,
                                "args": {**scope, "task_id": candidate["id"]},
                            }
                        )
                else:
                    arguments = dict(scope)
                    if name == "evidence.get":
                        arguments["ids"] = sorted(
                            {
                                e
                                for candidate in context["compatible_tasks"]
                                for e in candidate["evidence_ids"]
                            }
                        )
                    requests.append({"id": uuid4().hex, "name": name, "args": arguments})
            message = AIMessage(content="", tool_calls=requests)
        else:
            ledger = {}
            child_claims = set()
            child_abstained = False
            inherited_limits = set()
            for output in tool_outputs:
                data = output.get("result") or {}
                ledger.update(data.get("claims", {}))
                inherited_limits.update(data.get("limitations", []))
                if "result" in data:
                    child_claims.update(data["result"]["claim_refs"])
                    child_abstained |= data["state"] == "ABSTAINED"
                    inherited_limits.update(data["result"]["limitations"])
            if self.role == "operator_response" and not context.get("baseline"):
                ledger = {k: c for k, c in ledger.items() if k in child_claims}
            if child_abstained:
                ledger = {
                    k: c for k, c in ledger.items() if c["kind"] not in {"hypothesis", "location"}
                }
            claims = list(ledger)
            evidence = sorted({i for c in ledger.values() for i in c["evidence_ids"]})
            limitations = [
                str(c["value"].get("code")) if isinstance(c["value"], dict) else str(c["value"])
                for c in ledger.values()
                if c["kind"] == "limitation"
            ]
            limitations = sorted(set(limitations) | inherited_limits)
            hypothesis = None
            if self.role != "sensor_quality":
                for claim in ledger.values():
                    if claim["kind"] == "hypothesis":
                        value = claim["value"]
                        hypothesis = value.get("hypothesis") if isinstance(value, dict) else value
                        break
            if child_abstained:
                limitations.append("child_abstained")
            if context["requires_location"] and (
                not context["usable_location"]
                or child_abstained
                or hypothesis == "insufficient_evidence"
            ):
                limitations.append("location_withheld")
            result = {
                "outcome": "insufficient_evidence"
                if (child_abstained or hypothesis == "insufficient_evidence")
                else "supported",
                "claim_refs": claims,
                "evidence_ids": evidence,
                "limitations": limitations,
                "hypothesis": hypothesis,
                "summary": "",
                "recommendation_ids": ["review_sensor_evidence"]
                if self.role == "operator_response"
                else [],
            }
            message = AIMessage(content=json.dumps(result))
        message.response_metadata = {
            "requested_model": None,
            "observed_model": None,
            "model_identity_source": "scripted",
            "usage": None,
            "mode": "scripted",
        }
        return ChatResult(generations=[ChatGeneration(message=message)])

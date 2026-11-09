"""Offline contract transport, not evidence of live reasoning or model quality.

Bound context and scoped tool outputs drive deterministic plan/read/result
fixtures through the real graph contracts. Scripted critiques deliberately
recognize fixture language; neither these verdicts nor heuristic history labels
measure semantic reasoning, provider availability or production reliability.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import uuid4

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from subsea_copilot.profiles import comparison_documents, comparison_sensors, expanded_evidence
from subsea_copilot.runtime.provenance import RUNTIME_ENVELOPE


def decoded_output(content: str) -> dict[str, Any]:
    """Expand supported lossless model-view encodings for the offline fixture transport."""
    output: dict[str, Any] = json.loads(content)
    value = output.get("result")
    if isinstance(value, dict) and value.get("encoding") in {
        "columnar-comparison-v1", "columnar-shared-comparison-v2",
    }:
        output = {**output, "result": {**value, "sensors": comparison_sensors(value)}}
    elif isinstance(value, dict) and value.get("encoding") == "columnar-documents-v1":
        output = {**output, "result": {**value, "documents": comparison_documents(value)}}
    elif isinstance(value, dict) and value.get("encoding") in {
        "referenced-evidence-v1", "columnar-referenced-evidence-v2",
        "columnar-shared-referenced-evidence-v3",
    }:
        output = {**output, "result": expanded_evidence(value)}
    elif isinstance(value, dict) and "evidence_groups" in value:
        evidence = {
            identifier: item
            for group in value["evidence_groups"].values()
            for identifier, item in expanded_evidence(group)["evidence"].items()
        }
        output = {
            **output,
            "result": expanded_evidence({"evidence": evidence, "claims": value["claims"]}),
        }
    return output


class ScriptedChatModel(BaseChatModel):
    """Exercise orchestration and acceptance contracts without provider inference."""
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
        if context["phase"].startswith("critic-"):
            sources = context["source_texts"]
            checks = []
            for identifier, paragraph in context["candidate_paragraphs"].items():
                supported = paragraph["text"].startswith("Offline contract example:") or paragraph[
                    "text"
                ] in {
                    "Are the operating records complete for the incident?",
                    "Could the affected instruments share a communication or power failure?",
                }
                reference = (
                    next(iter(sources))
                    if identifier.startswith("question:")
                    else paragraph["references"][0]
                )
                anchors = list(
                    dict.fromkeys(
                        [
                            reference,
                            *(ref for ref in paragraph["references"] if ref.startswith("KN-")),
                        ]
                    )
                )
                checks.append(
                    {
                        "paragraph_id": identifier,
                        "verdict": "supported" if supported else "unsupported",
                        "reason": "Offline contract example only; not semantic qualification.",
                        "support": [
                            {"reference": ref, "quote": sources[ref][:120]} for ref in anchors
                        ]
                        if supported
                        else [],
                    }
                )
            critic_message = AIMessage(
                content=json.dumps(
                    {
                        "decision": "accept"
                        if all(c["verdict"] == "supported" for c in checks)
                        else "revise",
                        "checks": checks,
                    }
                ),
                response_metadata={"mode": "scripted", "model_identity_source": "scripted"},
            )
            return ChatResult(generations=[ChatGeneration(message=critic_message)])
        if context["phase"] == "reflection":
            revised_interpretation = {"revisions": [
                {
                    "paragraph_id": identifier,
                    "text": (
                        "Offline contract example: review the cited measurements and records; "
                        "physical causes remain unconfirmed."
                    ) if not identifier.startswith("question:") else paragraph["text"],
                    "references": paragraph["references"],
                }
                for identifier, paragraph in context["revision_targets"].items()
            ]}
            return ChatResult(
                generations=[
                    ChatGeneration(
                        message=AIMessage(
                            content=json.dumps(revised_interpretation),
                            response_metadata={
                                "mode": "scripted",
                                "model_identity_source": "scripted",
                            },
                        )
                    )
                ]
            )
        scope = context["scope"]
        tool_outputs = [
            decoded_output(m.content)
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
                    tool_outputs.extend(
                        decoded_output(json.dumps(entry["output"]))
                        for entry in data["application_intake"]
                    )
        history_action, history_review = self._history_action(messages, tool_outputs, context)
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
                        "evidence",
                        "unknown",
                    )
                )
                or context.get("requires_location", False)
            )
            compatible_tasks = context["compatible_tasks"]
            needs_diagnosis |= bool(context.get("history_version"))
            has_diagnosis = any(t["role"] == "event_diagnosis" for t in compatible_tasks)
            if any(word in question for word in ("summary", "summarize", "saved", "reuse")):
                needs_diagnosis = has_diagnosis
            needs_diagnosis |= bool(context.get("history_version"))
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
        elif history_action is not None:
            message = history_action
        elif not tool_outputs:
            requests = []
            names = list(context["required_tools"])
            if (self.role == "event_diagnosis" or context.get("baseline")) and (
                context.get("eligible_location", False)
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
            inherited_review = None
            for output in tool_outputs:
                data = output.get("result") or {}
                ledger.update(data.get("claims", {}))
                inherited_limits.update(data.get("limitations", []))
                if "result" in data:
                    child_claims.update(data["result"]["claim_refs"])
                    child_abstained |= data["state"] == "ABSTAINED"
                    inherited_limits.update(data["result"]["limitations"])
                    if data["result"].get("investigation") is not None:
                        inherited_review = data["result"]["investigation"]
            if self.role == "operator_response" and not context.get("baseline"):
                ledger = {k: c for k, c in ledger.items() if k in child_claims}
            must_abstain = child_abstained or (
                context["result_schema"]["properties"]["outcome"].get("const")
                == "insufficient_evidence"
            )
            if must_abstain:
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
            if context.get("requires_location", False) and (
                not context.get("usable_location", False)
                or must_abstain
                or hypothesis == "insufficient_evidence"
            ):
                limitations.append("location_withheld")
            result = {
                "outcome": "insufficient_evidence"
                if (must_abstain or hypothesis == "insufficient_evidence")
                else "supported",
                "claim_refs": claims,
                "evidence_ids": evidence,
                "limitations": limitations,
                "hypothesis": hypothesis,
                "summary": "",
                "recommendation_ids": ["review_sensor_evidence"]
                if self.role == "operator_response"
                else [],
                "investigation": history_review
                if self.role == "event_diagnosis"
                else inherited_review,
            }
            if (
                context.get("decision_policy") == "llm-diagnosis-v1"
                and self.role != "sensor_quality"
            ):
                result["outcome"] = "supported"
                result["hypothesis"] = "insufficient_evidence"
                if isinstance(result["investigation"], dict):
                    result["investigation"]["assessment"] = "unresolved"
                    result["investigation"]["next_action"] = "human_review"
            if context.get("response_protocol") in {"engineer-v1", "engineer-v2"}:
                review_value = result["investigation"]
                review = review_value if isinstance(review_value, dict) else {}
                references = [
                    *claims[:1],
                    *review.get("document_ids", [])[:1],
                    *review.get("comparison_call_ids", [])[:1],
                ]
                knowledge = context.get("domain_knowledge") or {}
                if knowledge.get("cards"):
                    references.append(knowledge["cards"][0]["id"])
                question = context["question"].lower()
                focus = (
                    "operating_context"
                    if "valve" in question or "operating" in question
                    else "inspection_rationale"
                    if context.get("requires_location", False)
                    else "sensor_quality"
                    if "sensor" in question or "drift" in question
                    else "evidence_gaps"
                    if "unknown" in question
                    else "root_cause"
                )
                interpretation: dict[str, Any] = {
                    "focus": focus,
                    "answer": {
                        "text": (
                            "Offline contract example: review the cited measurements and history "
                            "for this question. A plausible explanation is not a confirmed cause; "
                            "the checked evidence below retains the physical uncertainty."
                            + (
                                " Research guidance is applied to those observations, not proof "
                                "of a leak or approved operating authority."
                                if knowledge
                                else ""
                            )
                        ),
                        "references": references,
                    },
                    "competing_causes": [
                        {
                            "cause": "operating_change",
                            "stance": "not_established",
                            "text": (
                                "Offline contract example: operating activity remains a competing "
                                "explanation to verify against current records and pressure timing."
                            ),
                            "references": references,
                        }
                    ],
                    "follow_up_questions": [
                        "Are the operating records complete for the incident?",
                        "Could the affected instruments share a communication or power failure?",
                    ],
                }
                comparisons = [
                    comparison
                    for output in tool_outputs
                    for comparison in (
                        (output.get("result") or {}).get("reviewed_context") or {}
                    ).get("comparisons", [])
                ]
                if knowledge and comparisons:
                    comparison = comparisons[0]
                    interpretation["regional_assessments"] = [
                        {
                            "sensor_ids": [
                                sensor["sensor_id"] for sensor in comparison_sensors(comparison)
                            ],
                            "hypothesis": "unresolved",
                            "text": (
                                "Offline contract example: the cited joint pressure comparison "
                                "requires expert review of spatial and temporal alternatives. "
                                "This fixture does not establish a physical cause."
                            ),
                            "references": [comparison["call_id"], knowledge["cards"][0]["id"]],
                        }
                    ]
                result["interpretation"] = interpretation
            message = AIMessage(content=json.dumps(result))
        message.response_metadata = {
            "requested_model": None,
            "observed_model": None,
            "model_identity_source": "scripted",
            "usage": None,
            "mode": "scripted",
        }
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _history_action(
        self,
        messages: list[BaseMessage],
        outputs: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> tuple[AIMessage | None, dict[str, Any] | None]:
        """Script bounded search/read/compare follow-ups for history-enabled fixture tasks."""
        if (
            self.role != "event_diagnosis"
            or context["phase"] == "plan"
            or not context.get("history_version")
        ):
            return None, None
        runtime = next((
            json.loads(message.content.removeprefix(RUNTIME_ENVELOPE))
            for message in messages
            if isinstance(message, SystemMessage) and isinstance(message.content, str)
            and message.content.startswith(RUNTIME_ENVELOPE)
        ), {})
        references = runtime.get("history_reference_ids") or {}
        archives = [
            reference for message in messages
            if isinstance(message, HumanMessage) and isinstance(message.content, str)
            and '"archived_receipts":' in message.content
            for reference in json.loads(message.content)["archived_receipts"]
        ]
        data = [output.get("result") or {} for output in outputs]
        dependency = next((entry for entry in archives if entry["tool"] == "task.result"), None)
        if (
            context.get("decision_policy") == "llm-diagnosis-v1" and dependency
            and not any("task_id" in row and "result" in row for row in data)
        ):
            return AIMessage(content="", tool_calls=[{
                "id": uuid4().hex, "name": "evidence.get",
                "args": {
                    **context["scope"], "ids": [], "receipt_id": dependency["receipt_id"],
                },
            }]), None
        if (
            context.get("decision_policy") == "llm-diagnosis-v1" and archives
            and references.get("document_ids") and references.get("comparison_call_ids")
        ):
            # Compaction retains read identities, not enough content for causal fixture rules.
            return None, {
                "assessment": "unresolved", **references, "next_action": "human_review",
            }
        assessment: dict[str, Any] = next(
            (row["assessment"] for row in data if "assessment" in row), {}
        )
        hypothesis = assessment.get("hypothesis")
        intent = (
            "test_instrumentation"
            if hypothesis == "sensor_or_telemetry_issue"
            else "test_operating_change"
            if "COMMON_MODE_PRESSURE_CHANGE" in assessment.get("counterevidence", [])
            else "seek_counterevidence"
        )

        def action(name: str, arguments: dict[str, Any]) -> AIMessage:
            knowledge = context.get("domain_knowledge") or {}
            if knowledge.get("cards"):
                arguments = {
                    **arguments,
                    "knowledge_ids": [knowledge["cards"][0]["id"]],
                    "check_question": "Which observed alternatives need expert verification?",
                }
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": uuid4().hex,
                        "name": name,
                        "args": {**context["scope"], "intent": intent, **arguments},
                    }
                ],
            )

        search = next((row for row in data if "search_method" in row), None)
        if search is None:
            query = (
                "calibration OR gateway OR spike"
                if intent == "test_instrumentation"
                else "valve OR operating OR transient"
                if intent == "test_operating_change"
                else "pressure OR telemetry OR inspection"
            )
            return action("history.search", {"query": query, "asset_ids": ["northsea"]}), None
        read_docs = [
            doc
            for row in data
            if "documents" in row and "search_method" not in row
            for doc in row["documents"]
        ]
        hits = search["documents"]
        if not read_docs and hits:
            approved = sorted(
                [doc for doc in hits if doc["admissible"]],
                key=lambda doc: (doc["type"] not in {"operation", "maintenance"}, doc["id"]),
            )
            rejected = [doc for doc in hits if not doc["admissible"]]
            selected = (approved[:2] + rejected[:1]) if rejected else approved[:3]
            if not selected:
                selected = hits[:1]
            return action("history.read", {"document_ids": [doc["id"] for doc in selected]}), None
        comparisons = [
            (message.tool_call_id, decoded_output(message.content).get("result") or {})
            for message in messages
            if isinstance(message, ToolMessage) and isinstance(message.content, str)
            if "sensors" in (decoded_output(message.content).get("result") or {})
        ]
        for message in messages:
            if not isinstance(message, HumanMessage) or not isinstance(message.content, str):
                continue
            try:
                intake = json.loads(message.content).get("application_intake", [])
            except (ValueError, AttributeError):
                continue
            for entry in intake:
                result = decoded_output(json.dumps(entry["output"])).get("result") or {}
                if "sensors" in result:
                    comparisons.append((entry["call_id"], result))
        if read_docs and not comparisons and context["history_bounds"]["end_seconds"] >= 20:
            sensors = context["history_sensors"]
            if not sensors and context.get("network_pressure_table"):
                table = context["network_pressure_table"]
                mapped = [dict(zip(table["columns"], row, strict=True)) for row in table["rows"]]
                sensors = [
                    {
                        **row,
                        "id": row["sensor_id"],
                        "segment_id": row["sensor_id"].split("-")[0],
                        "event_support": False,
                    }
                    for row in mapped
                ]
            selected_sensors: list[str] = []
            used: set[str] = set()
            operation = next(
                (doc for doc in read_docs if doc["type"] == "operation" and doc["admissible"]), None
            )
            for sensor in sensors:
                if operation:
                    key = sensor["segment_id"]
                elif intent == "test_instrumentation":
                    if not sensor.get("quality_concern", False):
                        continue
                    key = sensor["id"].rsplit("-", 1)[0]
                else:
                    support = next(
                        (item for item in sensors if item.get("event_support", False)), None,
                    )
                    if support and sensor["segment_id"] != support["segment_id"]:
                        continue
                    key = sensor["id"].rsplit("-", 1)[0]
                if key not in used:
                    selected_sensors.append(sensor["id"])
                    used.add(key)
                if len(selected_sensors) == 4:
                    break
            if len(selected_sensors) < 2:
                selected_sensors = [s["id"] for s in sensors[:2]]
            end = context["history_bounds"]["end_seconds"]
            split = (
                int(
                    datetime.fromisoformat(operation["effective_from"]).timestamp()
                    - context["history_bounds"]["epoch_unix"]
                )
                if operation
                else end // 2
            )
            split = max(10, min(split, end - 10))
            return action(
                "history.compare",
                {
                    "sensor_ids": selected_sensors,
                    "start_seconds": max(0, split - 60),
                    "split_seconds": split,
                    "end_seconds": end,
                },
            ), None
        approved = [doc for doc in read_docs if doc["admissible"]]
        # These 0.2-bar/60%-coverage rules mirror legacy fixture checks, not live LLM policy.
        operating = any(
            len({
                sensor["segment_id"]
                for sensor in comparison["sensors"]
                if sensor["change_bar"] is not None
                and abs(sensor["change_bar"]) >= 0.2
                and sensor["before_usable"] >= sensor["before_expected"] * 0.6
                and sensor["after_usable"] >= sensor["after_expected"] * 0.6
            }) >= 2
            and any(
                doc["type"] == "operation"
                and comparison["start_seconds"]
                <= datetime.fromisoformat(doc["effective_from"]).timestamp()
                - context["history_bounds"]["epoch_unix"]
                < comparison["end_seconds"]
                for doc in approved
            )
            for _, comparison in comparisons
        )
        instrumentation = intent == "test_instrumentation" and any(
            doc["type"] == "maintenance" for doc in approved
        )
        review = {
            "assessment": "operating_change_plausible"
            if operating
            else "instrumentation_context"
            if instrumentation
            else "unresolved",
            "document_ids": [doc["id"] for doc in approved],
            "rejected_document_ids": [doc["id"] for doc in read_docs if not doc["admissible"]],
            "comparison_call_ids": [identifier for identifier, _ in comparisons],
            "next_action": "restore_telemetry"
            if context["history_bounds"]["coverage"] < 0.6
            else "check_operating_records"
            if operating
            else "review_instrumentation"
            if instrumentation
            else "inspect_supported_interval"
            if context.get("inspection_interval_available", False)
            else "human_review",
        }
        return None, review

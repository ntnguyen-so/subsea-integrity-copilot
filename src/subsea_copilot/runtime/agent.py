"""One LangGraph loop for every role; external effects happen at interrupts.

Messages enter a model -> tools -> model or model -> parse loop; only validated
structured output leaves it. The service, not graph nodes or provider tools,
performs external calls and resumes checkpointed interrupts. Schema repair is
bounded and does not relax the validator or reset persisted execution budgets.
"""

import json
from collections.abc import Callable
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from subsea_copilot.budgets import SCHEMA_REPAIR_LIMIT
from subsea_copilot.contracts import AgentResult
from subsea_copilot.runtime.diagnostics import REPAIR_INSTRUCTION, validation_diagnostic
from subsea_copilot.validation import ValidationError, parse_json


class WorkPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    steps: list[str] = Field(min_length=2, max_length=3)
    reuse_task_ids: list[str] = Field(default_factory=list, max_length=2)

    def checked(self) -> list[str]:
        """Allow only serial prerequisite-complete plans, with explicit reuse identities."""
        if self.steps not in [
            ["quality", "answer"],
            ["quality", "diagnosis", "answer"],
            ["reuse", "answer"],
        ]:
            raise ValidationError(
                "plan", "Plan must be bounded, serial, and prerequisite-complete.",
                details={"path": ["steps"]},
            )
        if (
            self.steps[0] == "reuse"
            and not self.reuse_task_ids
            or self.steps[0] != "reuse"
            and self.reuse_task_ids
        ):
            raise ValidationError(
                "plan", "Reuse requires explicit compatible source task IDs.",
                details={"path": ["reuse_task_ids"]},
            )
        if len(set(self.reuse_task_ids)) != len(self.reuse_task_ids):
            raise ValidationError(
                "plan", "Reuse source identities must be unique.",
                details={"path": ["reuse_task_ids"]},
            )
        return self.steps


class GraphState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    phase: str
    parsed: dict[str, Any]
    repairs: int
    failure: str
    harness_id: str
    harness: dict[str, Any]


def checked_plan_sources(
    plan: WorkPlan, history_required: bool, compatible_tasks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Resolve proposed reuse against already checked quality/diagnosis candidates."""
    plan.checked()
    if history_required and "diagnosis" not in plan.steps and "reuse" not in plan.steps:
        raise ValidationError(
            "history_plan", "Current investigations require a diagnosis review.",
            details={"path": ["steps"]},
        )
    if "reuse" not in plan.steps:
        return []
    identifiers = set(plan.reuse_task_ids)
    selected = [task for task in compatible_tasks if task["id"] in identifiers]
    if len(selected) != len(identifiers):
        raise ValidationError(
            "reuse", "Reuse proposal cites incompatible source tasks.",
            details={"path": ["reuse_task_ids"]},
        )
    if not any(task["role"] == "sensor_quality" for task in selected):
        raise ValidationError(
            "reuse", "No compatible accepted quality result to reuse.",
            details={"path": ["reuse_task_ids"]},
        )
    if history_required and not any(task["role"] == "event_diagnosis" for task in selected):
        raise ValidationError(
            "history_reuse", "Reuse must include the checked history diagnosis.",
            details={"path": ["reuse_task_ids"]},
        )
    return selected


def build_graph(
    checkpointer: Any = None,
    validator: Any = None,
    result_schema: Any = None,
    on_rejection: Callable[[Exception, int, bool, str | None], dict[str, Any]] | None = None,
) -> Any:
    """Compile the shared loop; the service fulfils effects outside checkpointed nodes."""

    def model(state: GraphState) -> dict[str, Any]:
        response = interrupt({"kind": "model", "messages": state["messages"]})
        return {"messages": [response]}

    def tools(state: GraphState) -> dict[str, Any]:
        message = state["messages"][-1]
        assert isinstance(message, AIMessage)
        response = interrupt({"kind": "tools", "calls": message.tool_calls})
        return {"messages": response}

    def parse(state: GraphState) -> dict[str, Any]:
        try:
            message = state["messages"][-1]
            if not isinstance(message, AIMessage) or not isinstance(message.content, str):
                raise ValidationError("structure", "Final output must be a JSON string.")
            if state["phase"] == "plan" and validator is None:
                parsed = WorkPlan.model_validate(parse_json(message.content))
                parsed.checked()
                return {"parsed": parsed.model_dump()}
            accepted = validator(message.content)
            return {"parsed": accepted.model_dump(mode="json")}
        except (ValueError, TypeError) as exc:
            # Repair changes the reply, never the evidence contract; every retry is revalidated.
            repairs = state.get("repairs", 0)
            retry = repairs < SCHEMA_REPAIR_LIMIT
            candidate = message.content if isinstance(message.content, str) else None
            diagnostic = (
                on_rejection(exc, repairs, retry, candidate)
                if on_rejection else {**validation_diagnostic(exc), "repair_requested": retry}
            )
            if not diagnostic["repair_requested"]:
                return {"failure": diagnostic["code"]}
            return {
                "repairs": state.get("repairs", 0) + 1,
                "messages": [
                    HumanMessage(
                        content=json.dumps(
                            {
                                "repair": diagnostic["code"],
                                "validator_feedback": diagnostic["validator_feedback"],
                                "validator_issues": diagnostic["issues"],
                                "repair_hint": diagnostic["repair_instruction"],
                                **(
                                    {"rejection_id": diagnostic["rejection_id"]}
                                    if "rejection_id" in diagnostic else {}
                                ),
                                **(
                                    {"validator_details": diagnostic["issues"][0]["details"]}
                                    if diagnostic["issues"]
                                    and diagnostic["issues"][0].get("details")
                                    else {}
                                ),
                                "instruction": REPAIR_INSTRUCTION,
                                **(
                                    {"expected_schema_source": "BOUND_CONTEXT.result_schema"}
                                    if result_schema is not None and state["phase"] != "plan"
                                    else {
                                        "expected_schema": WorkPlan.model_json_schema()
                                        if state["phase"] == "plan"
                                        else AgentResult.model_json_schema()
                                    }
                                ),
                            }
                        ),
                        additional_kwargs={"validation_repair": True},
                    )
                ],
            }

    def after_model(state: GraphState) -> str:
        message = state["messages"][-1]
        return "tools" if isinstance(message, AIMessage) and message.tool_calls else "parse"

    def after_parse(state: GraphState) -> str:
        return END if state.get("parsed") or state.get("failure") else "model"

    builder = StateGraph(GraphState)
    builder.add_node("model", model)
    builder.add_node("tools", tools)
    builder.add_node("parse", parse)
    builder.add_edge(START, "model")
    builder.add_conditional_edges("model", after_model)
    builder.add_edge("tools", "model")
    builder.add_conditional_edges("parse", after_parse)
    # An explicit None permits offline unit execution only, without durable graph recovery.
    return builder.compile(checkpointer=checkpointer or InMemorySaver())


def model_tool_result(result: JsonValue) -> dict[str, Any]:
    """Losslessly project large tool bodies for the model without changing receipts."""
    from subsea_copilot.profiles import compact_comparison, compact_documents, compact_evidence

    if not isinstance(result, dict):
        raise ValueError("A model tool result must be a scoped JSON object.")
    value = result.get("result")
    if isinstance(value, dict) and "joint_pattern" in value and "sensors" in value:
        return {**result, "result": compact_comparison(value)}
    if isinstance(value, dict) and value.get("documents"):
        return {**result, "result": compact_documents(value)}
    if isinstance(value, dict) and "evidence" in value and "claims" in value:
        return {**result, "result": compact_evidence(value)}
    return result


def repair_model_messages(messages: list[AnyMessage]) -> list[AnyMessage]:
    """Hide rejected final drafts from retries, retaining evidence and validator feedback."""
    invalid_drafts = set()
    for index, message in enumerate(messages):
        if not (
            isinstance(message, HumanMessage)
            and message.additional_kwargs.get("validation_repair") is True
        ):
            continue
        draft = messages[index - 1] if index else None
        if not isinstance(draft, AIMessage) or draft.tool_calls:
            raise ValidationError("repair_context", "Repair must follow an invalid final draft.")
        invalid_drafts.add(index - 1)
    return [message for index, message in enumerate(messages) if index not in invalid_drafts]


def tool_messages(
    calls: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> list[ToolMessage]:
    """Pair each scoped result with its originating request identity, preserving order."""
    return [
        ToolMessage(
            content=json.dumps(model_tool_result(result), allow_nan=False, separators=(",", ":")),
            tool_call_id=call["id"],
        )
        for call, result in zip(calls, results, strict=True)
    ]

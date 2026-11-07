"""One LangGraph loop for every role; external effects happen at interrupts."""

import json
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from subsea_copilot.budgets import SCHEMA_REPAIR_LIMIT
from subsea_copilot.contracts import AgentResult
from subsea_copilot.validation import ValidationError, parse_json


class WorkPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    steps: list[str] = Field(min_length=2, max_length=3)
    reuse_task_ids: list[str] = Field(default_factory=list, max_length=2)

    def checked(self) -> list[str]:
        if self.steps not in [
            ["quality", "answer"],
            ["quality", "diagnosis", "answer"],
            ["reuse", "answer"],
        ]:
            raise ValidationError(
                "plan", "Plan must be bounded, serial, and prerequisite-complete."
            )
        if (
            self.steps[0] == "reuse"
            and not self.reuse_task_ids
            or self.steps[0] != "reuse"
            and self.reuse_task_ids
        ):
            raise ValidationError("plan", "Reuse requires explicit compatible source task IDs.")
        if len(set(self.reuse_task_ids)) != len(self.reuse_task_ids):
            raise ValidationError("plan", "Reuse source identities must be unique.")
        return self.steps


class GraphState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    phase: str
    parsed: dict[str, Any]
    repairs: int
    failure: str


def build_graph(checkpointer: Any = None, validator: Any = None, result_schema: Any = None) -> Any:
    """The service fulfils model/tool requests outside graph nodes and checkpoints them."""

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
            if state["phase"] == "plan":
                parsed = WorkPlan.model_validate(parse_json(message.content))
                parsed.checked()
                return {"parsed": parsed.model_dump()}
            accepted = validator(message.content)
            return {"parsed": accepted.model_dump(mode="json")}
        except (ValueError, TypeError) as exc:
            if state.get("repairs", 0) >= SCHEMA_REPAIR_LIMIT:
                return {"failure": getattr(exc, "code", "structure")}
            return {
                "repairs": state.get("repairs", 0) + 1,
                "messages": [
                    HumanMessage(
                        content=json.dumps(
                            {
                                "repair": getattr(exc, "code", "structure"),
                                "validator_feedback": str(exc)[:1000],
                                "instruction": (
                                    "Regenerate a complete valid result from the supplied source "
                                    "evidence and validator feedback; no prose. "
                                    "The invalid draft is retained in the audit, not this request."
                                ),
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
    if (
        len(messages) >= 2
        and isinstance(messages[-1], HumanMessage)
        and messages[-1].additional_kwargs.get("validation_repair") is True
    ):
        draft = messages[-2]
        if not isinstance(draft, AIMessage) or draft.tool_calls:
            raise ValidationError("repair_context", "Repair must follow an invalid final draft.")
        return [*messages[:-2], messages[-1]]
    return list(messages)


def tool_messages(
    calls: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> list[ToolMessage]:
    return [
        ToolMessage(
            content=json.dumps(model_tool_result(result), allow_nan=False, separators=(",", ":")),
            tool_call_id=call["id"],
        )
        for call, result in zip(calls, results, strict=True)
    ]

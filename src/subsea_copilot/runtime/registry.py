"""Static read-only authority. Prompts and providers cannot extend this registry."""

from dataclasses import dataclass
from typing import Any

from subsea_copilot.budgets import (
    BUDGET_MULTIPLIER,
    COMPARISON_SENSOR_LIMIT,
    HISTORY_DOCUMENT_LIMIT,
)
from subsea_copilot.contracts import AgentRole


@dataclass(frozen=True)
class RolePolicy:
    purpose: str
    tools: frozenset[str]
    required: frozenset[str]
    model_limit: int
    tool_limit: int
    claim_kinds: frozenset[str]


REGISTRY: dict[AgentRole, RolePolicy] = {
    "sensor_quality": RolePolicy(
        "assess_sensor_health",
        frozenset(
            {
                "evidence.get",
                "quality.coverage",
                "quality.conflicts",
                "quality.sensor_patterns",
                "ontology.neighbors",
            }
        ),
        frozenset(
            {
                "quality.coverage",
                "quality.conflicts",
                "quality.sensor_patterns",
                "ontology.neighbors",
            }
        ),
        3 * BUDGET_MULTIPLIER,
        5 * BUDGET_MULTIPLIER,
        frozenset({"coverage", "sensor_health", "limitation"}),
    ),
    "event_diagnosis": RolePolicy(
        "assess_event_and_location",
        frozenset(
            {
                "evidence.get",
                "task.result",
                "event.assess",
                "event.counterevidence",
                "location.fit",
                "ontology.neighbors",
                "history.search",
                "history.read",
                "history.compare",
            }
        ),
        frozenset({"task.result", "event.assess", "event.counterevidence"}),
        4 * BUDGET_MULTIPLIER,
        8 * BUDGET_MULTIPLIER,
        frozenset({"coverage", "sensor_health", "hypothesis", "location", "limitation"}),
    ),
    "operator_response": RolePolicy(
        "answer_incident_question",
        frozenset({"task.result", "evidence.get", "criteria.explain"}),
        frozenset({"task.result", "evidence.get", "criteria.explain"}),
        3 * BUDGET_MULTIPLIER,
        5 * BUDGET_MULTIPLIER,
        frozenset({"coverage", "sensor_health", "hypothesis", "location", "limitation"}),
    ),
}

LLM_REGISTRY: dict[AgentRole, RolePolicy] = {
    role: RolePolicy(
        policy.purpose,
        (
            policy.tools - {"event.assess", "event.counterevidence", "location.fit"}
            | {"pressure.measurements"}
            if role == "event_diagnosis" else policy.tools - {"criteria.explain"}
        ),
        (
            frozenset({"task.result", "pressure.measurements"})
            if role == "event_diagnosis" else policy.required - {"criteria.explain"}
        ),
        policy.model_limit,
        policy.tool_limit,
        frozenset({"coverage", "sensor_health", "limitation"}),
    )
    for role, policy in REGISTRY.items()
}


def role_policy(role: AgentRole, decision_policy: str = "legacy-v1") -> RolePolicy:
    return (LLM_REGISTRY if decision_policy == "llm-diagnosis-v1" else REGISTRY)[role]

RECOMMENDATIONS = {
    "review_sensor_evidence": "Review the cited sensor evidence.",
    "review_coverage": "Review observation coverage and data gaps.",
    "review_competing_hypotheses": "Review the computed competing hypotheses.",
    "review_location_fit": "Review the supported inspection interval and its assumptions.",
}
LIMITATIONS = frozenset(
    {
        "insufficient_evidence",
        "coverage_lost",
        "degraded_coverage",
        "warming_up",
        "location_withheld",
        "location_ambiguous",
        "synthetic_data",
        "read_only",
        "metadata_unavailable",
        "child_abstained",
        "uncalibrated_model",
        "missing_data",
        "partial_health_review",
        "context_budget_exceeded",
    }
)


def tool_schemas(role: AgentRole, decision_policy: str = "legacy-v1") -> list[dict[str, Any]]:
    properties: dict[str, Any] = {
        "site_id": {"type": "string"},
        "snapshot_id": {"type": "string"},
        "pack_version": {"type": "string"},
        "baseline_version": {"type": "string"},
        "parameter_version": {"type": "string"},
    }
    schemas = []
    for name in sorted(role_policy(role, decision_policy).tools):
        fields = dict(properties)
        required = list(properties)
        if name == "task.result":
            fields["task_id"] = {"type": "string"}
            required.append("task_id")
            if decision_policy == "llm-diagnosis-v1" and role == "operator_response":
                fields["comparison_offset"] = {
                    "type": "integer", "minimum": 0,
                    "description": "Read one cited comparison per bounded handoff page.",
                }
        if name == "evidence.get":
            fields["ids"] = {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 100 * BUDGET_MULTIPLIER,
                "description": (
                    "Immutable evidence item IDs from supplied evidence keys, never claim IDs. "
                    "Claim references belong in claim_refs, not this read's ids."
                ),
            }
            fields["receipt_id"] = {
                "type": "string",
                "description": (
                    "Optional successful receipt ID from this task's archived model view. "
                    "Set ids=[] to retrieve its original result without executing its tool again."
                ),
            }
        if name == "quality.sensor_patterns":
            fields["offset"] = {"type": "integer", "minimum": 0}
        if name.startswith("history."):
            fields["knowledge_ids"] = {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": HISTORY_DOCUMENT_LIMIT,
                "description": "Pinned KN cards motivating this check.",
            }
            fields["check_question"] = {
                "type": "string",
                "maxLength": 240,
                "description": "What competing explanation will this read help distinguish?",
            }
            fields["intent"] = {
                "type": "string",
                "enum": [
                    "test_operating_change",
                    "test_instrumentation",
                    "check_prior_incident",
                    "seek_counterevidence",
                ],
            }
            required.append("intent")
        if name == "history.search":
            fields["query"] = {
                "type": "string",
                "minLength": 1,
                "maxLength": 160,
                "description": (
                    "Use 2-8 topical keywords, not a long question. "
                    "Ranked ANY-keyword matching; asset filters are separate."
                ),
            }
            fields["asset_ids"] = {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 4 * BUDGET_MULTIPLIER,
                "description": "Segment scopes include their instruments and gateways.",
            }
            required.extend(["query", "asset_ids"])
        if name == "history.read":
            fields["document_ids"] = {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": HISTORY_DOCUMENT_LIMIT,
            }
            required.append("document_ids")
        if name == "history.compare":
            fields["paired_only"] = {
                "type": "boolean",
                "description": (
                    "Return every selected sensor's profile and within-station paired "
                    "measurements only. Cross-station matrices remain available with false."
                ),
            }
            fields["sensor_ids"] = {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "maxItems": COMPARISON_SENSOR_LIMIT,
                "description": (
                    "Joint pressure profiles, graph distances, paired-complete correlations, "
                    "coverage and before/after changes. Select groups and contrasting observers."
                ),
            }
            for field in ("start_seconds", "split_seconds", "end_seconds"):
                fields[field] = {"type": "integer", "minimum": 0}
                required.append(field)
            required.append("sensor_ids")
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": f"Read pinned {name}; never writes or controls assets.",
                    "parameters": {
                        "type": "object",
                        "properties": fields,
                        "required": required,
                        "additionalProperties": False,
                    },
                },
            }
        )
    return schemas

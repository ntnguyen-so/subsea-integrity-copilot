"""Static read-only authority. Prompts and providers cannot extend this registry."""

from dataclasses import dataclass
from typing import Any

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
        3,
        5,
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
        4,
        8,
        frozenset({"coverage", "sensor_health", "hypothesis", "location", "limitation"}),
    ),
    "operator_response": RolePolicy(
        "answer_incident_question",
        frozenset({"task.result", "evidence.get", "criteria.explain"}),
        frozenset({"task.result", "evidence.get", "criteria.explain"}),
        3,
        5,
        frozenset({"coverage", "sensor_health", "hypothesis", "location", "limitation"}),
    ),
}

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


def tool_schemas(role: AgentRole) -> list[dict[str, Any]]:
    properties: dict[str, Any] = {
        "site_id": {"type": "string"},
        "snapshot_id": {"type": "string"},
        "pack_version": {"type": "string"},
        "baseline_version": {"type": "string"},
        "parameter_version": {"type": "string"},
    }
    schemas = []
    for name in sorted(REGISTRY[role].tools):
        fields = dict(properties)
        required = list(properties)
        if name == "task.result":
            fields["task_id"] = {"type": "string"}
            required.append("task_id")
        if name == "evidence.get":
            fields["ids"] = {"type": "array", "items": {"type": "string"}, "maxItems": 100}
        if name == "quality.sensor_patterns":
            fields["offset"] = {"type": "integer", "minimum": 0}
        if name.startswith("history."):
            fields["knowledge_ids"] = {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 3,
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
                "maxItems": 4,
                "description": "Segment scopes include their instruments and gateways.",
            }
            required.extend(["query", "asset_ids"])
        if name == "history.read":
            fields["document_ids"] = {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 3,
            }
            required.append("document_ids")
        if name == "history.compare":
            fields["sensor_ids"] = {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "maxItems": 8,
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

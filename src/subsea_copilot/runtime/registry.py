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
    "review_location_fit": "Review the compatible numerical location candidates.",
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

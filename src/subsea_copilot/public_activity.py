"""Bounded explanations of executed work, never provider-private reasoning.

Gateway request/result metadata becomes a small public activity payload with
application-authored purpose labels and observed status. Questions describe
intended checks; only successful completed reads expose findings/citation IDs.
This is neither the raw evidence ledger nor an assurance that a cause is proven.
"""

from __future__ import annotations

from typing import Any

ROLE_NAMES = {
    "sensor_quality": "Sensor Quality Agent",
    "event_diagnosis": "Event Diagnosis Agent",
    "operator_response": "Response Coordinator",
}
TOOL_PURPOSES = {
    "pressure.measurements": (
        "Read the measured pressure pattern",
        "Compare usable pressure measurements without treating a screening alert as a diagnosis.",
    ),
    "quality.coverage": ("Check available readings", "Missing readings stay unknown, not zero."),
    "quality.conflicts": (
        "Check unusable or conflicting readings",
        "A bad reading is not proof of a broken sensor.",
    ),
    "quality.sensor_patterns": (
        "Review individual sensor histories",
        "Separate reading concerns from possible physical changes.",
    ),
    "ontology.neighbors": (
        "Check sensor positions and shared connections",
        "Nearby sensors may share a data connection, so agreement alone is not independent proof.",
    ),
    "event.assess": (
        "Read pressure screening evidence",
        "A pressure alert is a starting point, not a leak diagnosis.",
    ),
    "event.counterevidence": (
        "Look for evidence against a leak",
        "Check alternative explanations instead of forcing a leak conclusion.",
    ),
    "location.fit": (
        "Check a possible inspection area",
        "Numerical tools bound the area; they do not establish an exact leak point.",
    ),
    "history.search": (
        "Find operating and maintenance records",
        "An operating change or shared sensor problem may explain the alerts.",
    ),
    "history.read": ("Read the actual source records", "Search titles alone are not evidence."),
    "history.compare": (
        "Compare sensors together",
        "Check whether changes happen together and weaken farther along the pipe.",
    ),
    "task.result": (
        "Read a specialist's handoff",
        "Use checked findings and carry forward their limitations.",
    ),
    "criteria.explain": (
        "Check the decision limits",
        "Unsupported causes or locations must remain unresolved.",
    ),
    "evidence.get": (
        "Read the cited measurements",
        "Verify the evidence before writing a recommendation.",
    ),
}


def tool_selection(role: str, call: dict[str, Any]) -> dict[str, Any]:
    """Keep application policy, model-public explanations and missing explanations distinct."""
    origin = call.get("origin", "model_request")
    title, purpose = TOOL_PURPOSES.get(
        call["name"], ("Read scoped evidence", "Check only authorized evidence.")
    )
    summary = call.get("decision_summary")
    summary = summary.strip() if isinstance(summary, str) else ""
    arguments = call["args"] if isinstance(call["args"], dict) else {}
    required = origin == "application_required_intake"
    return {
        "origin": origin,
        "title": title,
        "purpose": purpose,
        "decision_summary": (
            f"Application-required intake for {ROLE_NAMES[role]}. {purpose}"
            if required else summary or None
        ),
        "decision_provenance": (
            "application_required_intake" if required else "model_public" if summary
            else "not_recorded"
        ),
        "selection_rule": "required-intake-v1" if required else "observed_model_tool_request",
        "model_call_id": None if required else call.get("model_call_id"),
        "model_span_id": None if required else call.get("model_span_id"),
        "model_turn_index": None if required else call.get("model_turn_index"),
        "check_question": arguments.get("check_question"),
        "declared_intent": arguments.get("intent"),
        "knowledge_ids": arguments.get("knowledge_ids", []),
        "authority": "A selection is a request, not authorization or evidence of correctness.",
    }


def public_check(
    role: str,
    call_id: str,
    tool: str,
    arguments: dict[str, Any],
    result: dict[str, Any] | None = None,
    error: str | None = None,
    *,
    completed: bool = False,
) -> dict[str, Any]:
    """Separate requested intent, successful observations and failures in UI-safe summaries."""
    title, purpose = TOOL_PURPOSES.get(
        tool, ("Read scoped evidence", "Check only the evidence authorized for this agent.")
    )
    payload: dict[str, Any] = {
        "schema": "agent-public-v1",
        "role": role,
        "agent": ROLE_NAMES[role],
        "call_id": call_id,
        "tool": tool,
        "title": title,
        "purpose": purpose,
        "status": "failed" if error else "completed" if completed else "requested",
    }
    if isinstance(arguments.get("check_question"), str):
        payload["agent_question"] = arguments["check_question"][:240]
    if isinstance(arguments.get("knowledge_ids"), list):
        # Public previews are shorter than tool allowances; original receipts retain full scope.
        payload["knowledge_ids"] = arguments["knowledge_ids"][:3]
    if error:
        payload["observation"] = f"Check failed: {error}. No successful finding is inferred."
    elif completed and result is not None:
        claims = result.get("claims", {})
        payload["claim_refs"] = list(claims)[:32] if isinstance(claims, dict) else []
        findings = result.get("findings")
        if isinstance(findings, list):
            payload["observation"] = (
                f"Read {len(findings)} sensor histories. "
                "Missing or excluded readings remain separate from usable pressure anomalies."
            )
            payload["sensor_ids"] = [
                row["sensor_id"]
                for row in findings
                if isinstance(row, dict) and isinstance(row.get("sensor_id"), str)
            ][:8]
        elif isinstance(result.get("quality"), dict):
            quality = result["quality"]
            payload["observation"] = (
                f"{quality.get('usable_samples')} usable readings out of "
                f"{quality.get('expected_samples')} expected. "
                "Coverage limits what the next agent can conclude."
            )
        elif tool == "history.compare":
            payload["observation"] = (
                "Joint pressure measurements returned. The next interpretation must still "
                "check operating changes and shared sensor connections."
            )
        elif tool == "history.read":
            payload["observation"] = (
                "Source records returned. Their dates, validity and relationship "
                "to the alerted sensors must be checked."
            )
        elif tool == "task.result":
            payload["observation"] = (
                "Specialist findings and limitations returned to the receiving agent."
            )
        else:
            payload["observation"] = (
                "Scoped evidence returned; this check alone does not establish a physical cause."
            )
    return payload

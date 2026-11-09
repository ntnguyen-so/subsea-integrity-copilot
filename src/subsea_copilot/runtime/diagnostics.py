"""Bounded public validation issues, independent of trace content capture.

Typed failures become redacted repair guidance for the model and durable events.
Schema inputs and raw provider output are excluded: diagnostics explain rejection
without treating untrusted response text as authority or exposing private content.
"""

import json
from typing import Any

from pydantic import ValidationError as SchemaError

from subsea_copilot.prompts import load_prompt
from subsea_copilot.redaction import redact_content
from subsea_copilot.validation import ValidationError

REPAIR_INSTRUCTION = load_prompt("schema-repair").content.removesuffix("\n")
REPAIR_HINTS = {
    "structure": "Correct the listed schema fields; retain necessary evidence and uncertainty.",
    "plan": "Use a bounded serial plan and only explicitly authorized reusable task identities.",
    "reuse": "Use only accepted source IDs from BOUND_CONTEXT.compatible_tasks, including quality.",
    "history_plan": (
        "Include diagnosis after quality and before answering this history-backed check."
    ),
    "history_reuse": "Reuse both accepted quality and history diagnosis from the compatible tasks.",
    "limitations": "Retain required computed limitations and remove unknown limitation codes.",
    "citations": "Cite only claim identities present in the pinned immutable snapshot.",
    "evidence_receipts": "Read cited evidence through authorized evidence.get before answering.",
    "grounding_corrections": (
        "Keep all rejected checks and supply their complete corrections lists: exact candidate "
        "excerpts, precise changes, and original source_texts keys. "
        "Supported units need no changes."
    ),
    "tool_arguments": "Correct the registered argument fields; do not change the pinned scope.",
    "tool_scope": "The attempted scope is unauthorized; this investigation is withheld.",
    "tool_authority": "The tool is not authorized for this role; this investigation is withheld.",
}

TRANSPORT_REPAIR_HINTS = {
    "outer_json": (
        "Return exactly one valid JSON object, without Markdown, prose, duplicate keys "
        "or non-finite numbers."
    ),
    "envelope_shape": (
        "The outer object must contain exactly kind and value. Put the schema-matching "
        "result inside value, not at the top level or under a separate FINAL key."
    ),
    "final_value_type": (
        "For kind=final, value must be the native result JSON object, not a quoted "
        "JSON string or an array. Do not serialize the result twice."
    ),
    "envelope_kind": (
        "Use kind=final for the result object or kind=tool_calls for a list of "
        "registered application tool requests. Do not execute CLI tools."
    ),
}


def transport_diagnostic(stage: object) -> dict[str, str]:
    """Map only known envelope-failure stages to application-authored repair instructions."""
    known_stage = stage if isinstance(stage, str) and stage in TRANSPORT_REPAIR_HINTS else "unknown"
    return {
        "code": "invalid_structured_output",
        "stage": known_stage,
        "repair_instruction": TRANSPORT_REPAIR_HINTS.get(
            known_stage, "Follow the declared outer transport envelope exactly."
        ),
        "scope": (
            "Correct transport formatting only. Preserve the pinned source evidence, "
            "uncertainty and required limitations; do not invent facts to satisfy the schema."
        ),
    }


def validation_diagnostic(error: Exception) -> dict[str, Any]:
    """Expose at most 32 schema issues and bound/redact the serialized public payload."""
    code = error.code if isinstance(error, ValidationError) else "structure"
    feedback = (
        str(error)
        if isinstance(error, ValidationError)
        else "The model reply did not match the required structured schema."
    )
    issues: list[dict[str, Any]]
    schema_error = error if isinstance(error, SchemaError) else error.__cause__
    if isinstance(schema_error, SchemaError):
        issues = [
            {"code": entry["type"], "path": list(entry["loc"]), "message": entry["msg"]}
            for entry in schema_error.errors(
                include_input=False, include_context=False, include_url=False
            )
        ][:32]
    else:
        details = error.details if isinstance(error, ValidationError) else None
        issues = [
            {
                "code": code,
                "path": details.get("path", []) if details else [],
                "message": feedback,
                "details": details,
            }
        ]
    payload = {
        "code": code,
        "validator_feedback": feedback[:1000],
        "issues": issues,
        "repair_instruction": REPAIR_HINTS.get(
            code, "Use only pinned source evidence; correct or remove unsupported assertions."
        ),
    }
    encoded = redact_content(json.dumps(payload, ensure_ascii=True, allow_nan=False))
    # Oversized details are replaced, not blindly sliced into invalid JSON.
    if len(encoded) > 16000:
        payload["issues"] = [
            {
                "code": code,
                "path": [],
                "message": "Detailed diagnostics exceed the public limit.",
                "details_truncated": True,
            }
        ]
        encoded = redact_content(json.dumps(payload, ensure_ascii=True, allow_nan=False))
    decoded: dict[str, Any] = json.loads(encoded)
    return decoded

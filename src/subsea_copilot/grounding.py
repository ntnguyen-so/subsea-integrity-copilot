"""Independent language review with exact-source anchors and fail-closed acceptance."""

import json
from typing import Any

from .contracts import (
    AgentResult,
    AgentTask,
    GroundingAssessment,
    WindowSnapshot,
    content_hash,
)
from .validation import ValidationError, parse_json


def candidate_hash(result: AgentResult) -> str:
    return content_hash(result.model_dump(mode="json"))


def validate_revision(candidate: AgentResult, revised: AgentResult) -> None:
    if revised.model_dump(exclude={"interpretation"}) != candidate.model_dump(
        exclude={"interpretation"}
    ):
        raise ValidationError("reflection_scope", "Revision may change interpretation only.")


def paragraphs(result: AgentResult) -> dict[str, dict[str, Any]]:
    value = result.interpretation
    if value is None:
        raise ValidationError("grounding_missing", "A review needs a candidate interpretation.")
    return {
        "answer": value.answer.model_dump(mode="json"),
        **{
            f"cause:{cause.cause}": cause.model_dump(mode="json")
            for cause in value.competing_causes
        },
        **{
            f"question:{index}": {"text": question, "references": []}
            for index, question in enumerate(value.follow_up_questions)
        },
    }


def critic_context(
    task: AgentTask,
    result: AgentResult,
    sources: dict[str, str],
    phase: str,
) -> dict[str, Any]:
    return {
        "phase": phase,
        "role": "evidence_grounding_critic",
        "mode": task.mode,
        "scope": {"snapshot_id": task.snapshot_id, "site_id": task.site_id},
        "question": task.question,
        "required_tools": [],
        "candidate_paragraphs": paragraphs(result),
        "source_texts": sources,
        "checked_outcome": result.outcome,
        "limitations": result.limitations,
        "result_schema": GroundingAssessment.model_json_schema(),
    }


def source_texts(
    result: AgentResult,
    snapshot: WindowSnapshot,
    receipts: list[dict[str, Any]],
) -> dict[str, str]:
    sources = {
        ref: json.dumps(snapshot.claims[ref].model_dump(mode="json"), sort_keys=True)
        for ref in result.claim_refs
    }
    review = result.investigation
    if review is None:
        return sources
    for receipt in receipts:
        if receipt["name"] != "task.result" or receipt.get("error"):
            continue
        context = (receipt.get("result") or {}).get("reviewed_context") or {}
        for document in context.get("documents", []):
            if document["id"] in review.document_ids and document.get("admissible") is True:
                sources[document["id"]] = json.dumps(document, sort_keys=True)
        for comparison in context.get("comparisons", []):
            if comparison["call_id"] in review.comparison_call_ids:
                sources[comparison["call_id"]] = json.dumps(comparison, sort_keys=True)
    expected = {*review.document_ids, *review.comparison_call_ids}
    if not expected <= sources.keys():
        raise ValidationError("grounding_sources", "Reviewed source bodies are missing.")
    return sources


def validate_assessment(
    value: str | dict[str, Any] | GroundingAssessment,
    candidate: AgentResult,
    sources: dict[str, str],
) -> GroundingAssessment:
    assessment = (
        value
        if isinstance(value, GroundingAssessment)
        else GroundingAssessment.model_validate(
            parse_json(value) if isinstance(value, str) else value
        )
    )
    expected = paragraphs(candidate)
    identifiers = [check.paragraph_id for check in assessment.checks]
    if len(set(identifiers)) != len(identifiers) or set(identifiers) != expected.keys():
        raise ValidationError("grounding_coverage", "Review every answer, cause and question once.")
    for check in assessment.checks:
        allowed = set(expected[check.paragraph_id]["references"])
        if check.paragraph_id.startswith("question:"):
            allowed = set(sources)
        if check.verdict == "supported" and not check.support:
            raise ValidationError(
                "grounding_quotes", "Accepted paragraphs need exact source anchors."
            )
        for support in check.support:
            if (
                support.reference not in allowed
                or support.reference not in sources
                or support.quote not in sources[support.reference]
            ):
                raise ValidationError(
                    "grounding_quotes", "Quote is not in the cited original source."
                )
    all_supported = all(check.verdict == "supported" for check in assessment.checks)
    if (assessment.decision == "accept") != all_supported:
        raise ValidationError("grounding_decision", "Acceptance requires every paragraph to pass.")
    return assessment


def validate_review(
    result: AgentResult,
    task: AgentTask,
    snapshot: WindowSnapshot,
    receipts: list[dict[str, Any]],
) -> None:
    record = task.interpretation_review
    if record is None:
        raise ValidationError("grounding_required", "Independent grounding review is missing.")
    final = record.rounds[-1]
    if final.candidate_hash != candidate_hash(result):
        raise ValidationError("grounding_identity", "Review does not bind this exact result.")
    sources = source_texts(result, snapshot, receipts)
    if record.source_hash != content_hash({key: value for key, value in sources.items()}):
        raise ValidationError("grounding_identity", "Reviewed evidence packet changed.")
    assessment = validate_assessment(final.assessment, result, sources)
    if assessment.decision != "accept":
        raise ValidationError("grounding_rejected", "Unsupported interpretation must be withheld.")

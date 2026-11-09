"""Citation-linked advisory language, separate from the checked numerical ledger.

Structured results and read receipts authorize references in engineer-facing
prose, then render that prose apart from application-owned factual output.
Only the response role may supply it; guidance must accompany case evidence.
Citation membership is checked here, while grounding.py reviews actual support.
"""

from typing import Any

from subsea_copilot.contracts import AgentResult, AgentTask, EngineerInterpretation
from subsea_copilot.profiles import comparison_sensors
from subsea_copilot.validation import (
    ValidationError,
    read_evidence_reference,
    read_pinned_evidence,
)


def validate_interpretation(
    result: AgentResult, task: AgentTask, receipts: list[dict[str, Any]] | None = None
) -> None:
    """Check protocol, citation/read scope, guidance application and bounded follow-up questions."""
    interpretation = result.interpretation
    required = task.role == "operator_response" and task.response_protocol in {
        "engineer-v1",
        "engineer-v2",
    }
    if interpretation is None:
        if required:
            raise ValidationError("interpretation_required", "Answer the engineer's question.")
        return
    if not required:
        raise ValidationError("interpretation_authority", "Only the response role interprets RCA.")
    review = result.investigation
    allowed = set(result.claim_refs)
    read_evidence = read_pinned_evidence(receipts or [])
    allowed.update(set(result.evidence_ids) & read_evidence)
    bundle = read_evidence_reference(task.snapshot_id, receipts or [])
    if bundle:
        allowed.add(bundle)
    if review:
        allowed.update(review.document_ids)
        allowed.update(review.comparison_call_ids)
    evidence = set(allowed)
    # Keep case evidence separate before adding KN guidance: a card alone proves no case fact.
    guidance = (
        {card.id for card in task.knowledge_packet.cards if task.role in card.roles}
        if task.knowledge_packet
        else set()
    )
    allowed.update(guidance)
    paragraphs = interpretation.cited_paragraphs()
    for paragraph in paragraphs:
        invalid = set(paragraph.references) - allowed
        duplicates = {
            ref for ref in paragraph.references if paragraph.references.count(ref) > 1
        }
        if invalid or duplicates:
            raise ValidationError(
                "interpretation_citations",
                "Use accepted claims, reviewed history and pinned applicable guidance. "
                f"Invalid references: {sorted(invalid)}. "
                f"Duplicate references: {sorted(duplicates)}.",
            )
        if set(paragraph.references) & guidance and not set(paragraph.references) & evidence:
            raise ValidationError(
                "knowledge_not_evidence", "Domain guidance must be applied to cited case evidence."
            )
    if guidance and not any(set(paragraph.references) & guidance for paragraph in paragraphs):
        raise ValidationError(
            "knowledge_not_applied",
            "Explain the application of at least one pinned knowledge card.",
        )
    if task.knowledge_packet and review and review.comparison_call_ids:
        if task.decision_policy == "legacy-v1" and not interpretation.regional_assessments:
            raise ValidationError(
                "regional_analysis_required",
                "Explain the joint sensor patterns, not only the numerical screening label.",
            )
        for region in interpretation.regional_assessments:
            if (
                len(set(region.sensor_ids)) != len(region.sensor_ids)
                or not set(region.references).intersection(review.comparison_call_ids)
                or not set(region.references).intersection(guidance)
            ):
                raise ValidationError(
                    "regional_evidence",
                    "Each sensor group needs an executed comparison and applicable knowledge.",
                )
            if receipts is not None:
                comparisons = {
                    item["call_id"]: item
                    for receipt in receipts
                    if receipt.get("name") == "task.result" and not receipt.get("error")
                    for item in ((receipt.get("result") or {}).get("reviewed_context") or {}).get(
                        "comparisons", []
                    )
                }
                observed = {
                    sensor["sensor_id"]
                    for reference in region.references
                    if reference in comparisons
                    for sensor in comparison_sensors(comparisons[reference])
                }
                if not set(region.sensor_ids) <= observed:
                    raise ValidationError(
                        "regional_sensor_scope",
                        "Regional sensor IDs must appear in their cited executed comparisons.",
                    )
    if len({c.cause for c in interpretation.competing_causes}) != len(
        interpretation.competing_causes
    ):
        raise ValidationError("interpretation_causes", "Discuss each competing cause once.")
    if any(
        not q.strip() or len(q) > 200 or not q.rstrip().endswith("?")
        for q in interpretation.follow_up_questions
    ):
        raise ValidationError("interpretation_questions", "Use bounded verification questions.")


def render_interpretation(value: EngineerInterpretation, task: AgentTask) -> str:
    """Format already-validated advisory text and its source IDs without recomputing numbers."""
    lines = [
        "ENGINEER QUESTION",
        task.question,
        "ENGINEERING ASSESSMENT",
        value.answer.text,
        "Sources: " + ", ".join(value.answer.references),
        "COMPETING EXPLANATIONS",
    ]
    for cause in value.competing_causes:
        lines.extend(
            [
                f"{cause.cause.replace('_', ' ')} ({cause.stance.replace('_', ' ')}): {cause.text}",
                "Sources: " + ", ".join(cause.references),
            ]
        )
    for region in value.regional_assessments:
        lines.extend(
            [
                f"Joint sensor assessment ({region.hypothesis.replace('_', ' ')}): "
                + ", ".join(region.sensor_ids),
                region.text,
                "Sources: " + ", ".join(region.references),
            ]
        )
    lines.append("QUESTIONS TO RESOLVE WITH THE ENGINEER")
    lines.extend(value.follow_up_questions)
    return "\n".join(lines)

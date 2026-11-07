"""Citation-linked advisory language, separate from the checked numerical ledger."""

from typing import Any

from subsea_copilot.contracts import AgentResult, AgentTask, EngineerInterpretation
from subsea_copilot.profiles import comparison_sensors
from subsea_copilot.validation import ValidationError


def validate_interpretation(
    result: AgentResult, task: AgentTask, receipts: list[dict[str, Any]] | None = None
) -> None:
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
    if review:
        allowed.update(review.document_ids)
        allowed.update(review.comparison_call_ids)
    evidence = set(allowed)
    guidance = (
        {card.id for card in task.knowledge_packet.cards if task.role in card.roles}
        if task.knowledge_packet
        else set()
    )
    allowed.update(guidance)
    paragraphs = interpretation.cited_paragraphs()
    for paragraph in paragraphs:
        if (
            len(set(paragraph.references)) != len(paragraph.references)
            or not set(paragraph.references) <= allowed
        ):
            raise ValidationError(
                "interpretation_citations",
                "Use accepted claims, reviewed history and pinned applicable guidance.",
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
        if not interpretation.regional_assessments:
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

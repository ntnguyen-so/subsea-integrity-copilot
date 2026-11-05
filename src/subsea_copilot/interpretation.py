"""Citation-linked advisory language, separate from the checked numerical ledger."""

from subsea_copilot.contracts import AgentResult, AgentTask, EngineerInterpretation
from subsea_copilot.validation import ValidationError


def validate_interpretation(result: AgentResult, task: AgentTask) -> None:
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
    paragraphs = [interpretation.answer, *interpretation.competing_causes]
    for paragraph in paragraphs:
        if (
            len(set(paragraph.references)) != len(paragraph.references)
            or not set(paragraph.references) <= allowed
        ):
            raise ValidationError(
                "interpretation_citations", "Use accepted claims and reviewed history only."
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
        "ENGINEERING INTERPRETATION - MODEL-WRITTEN, FOR HUMAN REVIEW",
        "Citation membership is checked; wording is not independently verified RCA. "
        "The checked evidence and safety limits below remain authoritative.",
        value.answer.text,
        "Sources: " + ", ".join(value.answer.references),
        "COMPETING CAUSES - NOT CONFIRMED ROOT CAUSES",
    ]
    for cause in value.competing_causes:
        lines.extend(
            [
                f"{cause.cause.replace('_', ' ')} ({cause.stance.replace('_', ' ')}): {cause.text}",
                "Sources: " + ", ".join(cause.references),
            ]
        )
    lines.append("QUESTIONS TO RESOLVE WITH THE ENGINEER")
    lines.extend(value.follow_up_questions)
    return "\n".join(lines)

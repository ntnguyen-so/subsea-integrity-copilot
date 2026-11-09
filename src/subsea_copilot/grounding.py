"""Independent language review with exact-source anchors and fail-closed acceptance."""

import json
from typing import Any

from pydantic import Field

from .contracts import (
    AgentResult,
    AgentTask,
    Contract,
    EngineerInterpretation,
    GroundingAssessment,
    GroundingCheck,
    WindowSnapshot,
    content_hash,
)
from .knowledge import KnowledgePacket
from .profiles import compact_evidence
from .validation import ValidationError, parse_json, read_evidence_reference


class ParagraphRevision(Contract):
    paragraph_id: str
    text: str = Field(min_length=1, max_length=6000)
    references: list[str] = Field(default_factory=list, max_length=18)


class InterpretationRevision(Contract):
    revisions: list[ParagraphRevision] = Field(min_length=1, max_length=10)


class GroundingCheckBatch(GroundingAssessment):
    checks: list[GroundingCheck] = Field(min_length=1, max_length=10)


def apply_revision(
    value: str, candidate: AgentResult, criticism: GroundingAssessment
) -> AgentResult:
    patch = InterpretationRevision.model_validate(parse_json(value))
    expected = {c.paragraph_id for c in criticism.checks if c.verdict != "supported"}
    identifiers = [revision.paragraph_id for revision in patch.revisions]
    if len(set(identifiers)) != len(identifiers) or set(identifiers) != expected:
        raise ValidationError(
            "reflection_scope", "Revise each rejected unit exactly once and no supported units.",
        )
    assert candidate.interpretation is not None
    updated = candidate.interpretation.model_dump(mode="json")
    for revision in patch.revisions:
        replacement = {"text": revision.text, "references": revision.references}
        identifier = revision.paragraph_id
        if identifier == "answer":
            updated["answer"] = replacement
        elif identifier.startswith("cause:"):
            cause = next(
                cause for cause in updated["competing_causes"]
                if cause["cause"] == identifier.removeprefix("cause:")
            )
            cause.update(replacement)
        elif identifier.startswith("region:"):
            updated["regional_assessments"][int(identifier.removeprefix("region:"))].update(
                replacement
            )
        elif identifier.startswith("question:"):
            if revision.references:
                raise ValidationError("reflection_scope", "Questions do not carry references.")
            index = int(identifier.removeprefix("question:"))
            updated["follow_up_questions"][index] = revision.text
        else:
            raise ValidationError("reflection_scope", "Unknown revision unit.")
    revised = candidate.model_copy(update={
        "interpretation": EngineerInterpretation.model_validate(updated),
    })
    validate_revision(candidate, revised)
    return revised


def reusable_checks(
    previous: AgentResult,
    current: AgentResult,
    assessment: GroundingAssessment,
    previous_sources: dict[str, str],
    current_sources: dict[str, str],
    *,
    require_quotes: bool = True,
) -> list[GroundingCheck]:
    validate_assessment(assessment, previous, previous_sources, require_quotes=require_quotes)
    if not require_quotes and (
        candidate_hash(previous) != candidate_hash(current) or previous_sources != current_sources
    ):
        return []
    before, after = paragraphs(previous), paragraphs(current)
    retained = []
    for check in assessment.checks:
        identifier = check.paragraph_id
        if check.verdict != "supported" or before[identifier] != after.get(identifier):
            continue
        references = (
            set(previous_sources) if identifier.startswith("question:")
            else set(before[identifier]["references"])
        )
        references.update(support.reference for support in check.support)
        if all(
            ref in previous_sources and ref in current_sources
            and previous_sources[ref] == current_sources[ref]
            for ref in references
        ):
            retained.append(check)
    return retained


def candidate_hash(result: AgentResult) -> str:
    value = result.model_dump(mode="json")
    if value["interpretation"] and not value["interpretation"].get("regional_assessments"):
        value["interpretation"].pop("regional_assessments", None)
    return content_hash(value)


def review_material_hash(task: AgentTask, result: AgentResult, sources: dict[str, str]) -> str:
    return content_hash({
        "protocol": "semantic-grounding-v2",
        "tenant_id": task.tenant_id, "site_id": task.site_id,
        "generation_id": task.generation_id, "snapshot_id": task.snapshot_id,
        "task_id": task.id, "question": task.question,
        "candidate_hash": candidate_hash(result),
        "sources": {key: value for key, value in sources.items()},
    })


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
            f"region:{index}": region.model_dump(mode="json")
            for index, region in enumerate(value.regional_assessments)
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
    context: dict[str, Any] = {
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
        "knowledge_review": (
            "KN sources are research-curated guidance, not incident observations "
            "or expert approval. "
            "Check that cited guidance actually applies to the cited case evidence, that its "
            "prerequisites and counterexamples are respected, and that neither measurements nor "
            "causal certainty are invented. A knowledge quote alone cannot support a case fact."
            " For each supported paragraph citing KN guidance, anchor both a KN source and "
            "a non-KN case-evidence source with exact quotes."
        ),
        "result_schema": GroundingCheckBatch.model_json_schema(),
    }
    if task.decision_policy == "llm-diagnosis-v1":
        context["review_protocol"] = "semantic-grounding-v2"
        context["review_material_hash"] = review_material_hash(task, result, sources)
        context["knowledge_review"] = (
            "KN sources are guidance, not incident observations or expert approval. Check "
            "applicability, prerequisites and counterexamples against actual original case "
            "evidence. Reject invented measurements or causal certainty. A guidance statement "
            "alone cannot support a case fact. Return compact semantic decisions, "
            "not copied quotes."
        )
        context["result_schema"]["$defs"]["GroundingCheck"]["properties"]["support"] = {
            "type": "array", "maxItems": 0, "default": [],
            "description": "Compact semantic verdict: do not recopy original-source quotes.",
        }
    return context


def source_texts(
    result: AgentResult,
    snapshot: WindowSnapshot,
    receipts: list[dict[str, Any]],
    knowledge: KnowledgePacket | None = None,
) -> dict[str, str]:
    sources = {
        ref: json.dumps(snapshot.claims[ref].model_dump(mode="json"), sort_keys=True)
        for ref in result.claim_refs
    }
    cited = (
        {
            reference
            for paragraph in result.interpretation.cited_paragraphs()
            for reference in paragraph.references
        }
        if result.interpretation
        else set()
    )
    read_evidence = {
        reference
        for receipt in receipts
        if receipt["name"] == "evidence.get" and not receipt.get("error")
        for reference in (receipt.get("result") or {}).get("evidence", {})
    }
    for reference in cited & set(result.evidence_ids):
        if reference not in read_evidence or reference not in snapshot.evidence:
            raise ValidationError("grounding_sources", "Cited pressure source was not read.")
        sources[reference] = json.dumps(
            snapshot.evidence[reference].model_dump(mode="json"), sort_keys=True
        )
    pressure = {
        reference: snapshot.evidence[reference].model_dump(mode="json")
        for reference in set(result.evidence_ids) & read_evidence
        if reference in snapshot.evidence
        and snapshot.evidence[reference].kind == "channel_summary"
    }
    bundle = read_evidence_reference(snapshot.id, receipts)
    if bundle and bundle in cited:
        if not read_evidence <= snapshot.evidence.keys():
            raise ValidationError(
                "grounding_sources", "Read evidence must resolve in the snapshot.",
            )
        groups: dict[str, dict[str, Any]] = {}
        for ref in sorted(read_evidence):
            item = snapshot.evidence[ref]
            groups.setdefault(item.kind, {})[ref] = item.model_dump(mode="json")
        sources[bundle] = json.dumps({
            "evidence_groups": {
                kind: compact_evidence({"evidence": items, "claims": {}})
                for kind, items in groups.items()
            },
        }, sort_keys=True)
    elif pressure:
        sources["audited_pressure_summaries"] = json.dumps(
            compact_evidence({"evidence": pressure, "claims": {}}),
            sort_keys=True, separators=(",", ":"),
        )
    if knowledge and result.interpretation:
        sources.update(
            {
                card.id: json.dumps(
                    card.model_dump(
                        mode="json",
                        include={
                            "id",
                            "title",
                            "status",
                            "applies_when",
                            "guidance",
                            "verification_steps",
                            "counterexamples",
                            "limitations",
                            "review_basis",
                        },
                    ),
                    sort_keys=True,
                )
                for card in knowledge.cards
                if card.id in cited
            }
        )
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
    *,
    require_quotes: bool = True,
    require_corrections: bool = False,
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
        if require_corrections and check.verdict != "supported" and not check.corrections:
            raise ValidationError(
                "grounding_corrections",
                "Each rejected unit needs a complete actionable correction checklist.",
            )
        if check.verdict == "supported" and check.corrections:
            raise ValidationError(
                "grounding_corrections", "Supported units must not request changes.",
            )
        for correction in check.corrections:
            if correction.excerpt not in expected[check.paragraph_id]["text"]:
                raise ValidationError(
                    "grounding_corrections", "Correction excerpt is not in the rejected unit.",
                )
            if not set(correction.source_references) <= sources.keys():
                raise ValidationError(
                    "grounding_corrections", "Correction cites an unavailable original source.",
                )
        if require_quotes and check.verdict == "supported" and not check.support:
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
        if require_quotes and check.verdict == "supported" and any(
            ref.startswith("KN-") for ref in expected[check.paragraph_id]["references"]
        ):
            anchored = {support.reference for support in check.support}
            if not any(ref.startswith("KN-") for ref in anchored) or not any(
                not ref.startswith("KN-") for ref in anchored
            ):
                raise ValidationError(
                    "grounding_knowledge",
                    "Applied guidance requires exact anchors to both knowledge and case evidence.",
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
    if task.decision_policy == "llm-diagnosis-v1":
        from .agent_evidence import measurement_snapshot

        snapshot = measurement_snapshot(snapshot)
    record = task.interpretation_review
    if record is None:
        raise ValidationError("grounding_required", "Independent grounding review is missing.")
    final = record.rounds[-1]
    if final.candidate_hash != candidate_hash(result):
        raise ValidationError("grounding_identity", "Review does not bind this exact result.")
    sources = source_texts(result, snapshot, receipts, task.knowledge_packet)
    if record.source_hash != content_hash({key: value for key, value in sources.items()}):
        raise ValidationError("grounding_identity", "Reviewed evidence packet changed.")
    compact = record.protocol == "semantic-grounding-v2"
    if compact and (
        task.decision_policy != "llm-diagnosis-v1"
        or final.material_hash != review_material_hash(task, result, sources)
    ):
        raise ValidationError("grounding_identity", "Semantic review material or scope changed.")
    assessment = validate_assessment(final.assessment, result, sources, require_quotes=not compact)
    if assessment.decision != "accept":
        raise ValidationError("grounding_rejected", "Unsupported interpretation must be withheld.")

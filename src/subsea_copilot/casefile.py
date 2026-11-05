"""Review handoff derived from validated results, never a new diagnosis or approval."""

from typing import Literal

from pydantic import JsonValue

from .contracts import (
    AgentTask,
    Claim,
    Contract,
    EngineerInterpretation,
    InterpretationReview,
    Mode,
    WindowSnapshot,
)
from .investigation import ACTION_LABELS
from .validation import ValidationError


class InspectionInterval(Contract):
    segment_id: str
    start_m: float
    end_m: float


class CaseSource(Contract):
    document: dict[str, JsonValue]
    use: Literal["cited", "rejected", "read_not_cited"]


class InvestigationStep(Contract):
    task_id: str
    call_id: str
    tool: str
    intent: str
    arguments: dict[str, JsonValue]
    error: str | None
    sequence: int


class InvestigationCase(Contract):
    schema_version: Literal["investigation-v1"] = "investigation-v1"
    task_id: str
    generation_id: str
    snapshot_id: str
    question: str
    mode: Mode
    state: Literal["SUCCEEDED", "ABSTAINED"]
    window_start: str
    window_end: str
    input_hash: str
    pack_version: str
    baseline_version: str
    parameter_version: str
    history_version: str | None
    disposition: str
    hypothesis: str | None
    inspection: InspectionInterval | None
    next_action: str
    interpretation: EngineerInterpretation | None
    checked_claims: list[Claim]
    limitations: list[str]
    sources: list[CaseSource]
    comparisons: list[dict[str, JsonValue]]
    steps: list[InvestigationStep]
    reused_task_ids: list[str]
    fresh_model_calls: int
    fresh_tool_calls: int
    recorded_elapsed_seconds: float
    report_target_seconds: int = 300
    report_target_met: bool
    interpretation_review: InterpretationReview | None = None
    provider_cost_usd: None = None
    authority: str = (
        "For engineer review, not engineer-approved. No leak clearance, dispatch or control. "
        "Model-written explanations require source review; citations do not prove entailment."
    )


def build_casefile(
    task: AgentTask,
    snapshot: WindowSnapshot,
    dependencies: list[AgentTask],
    receipts: list[dict[str, JsonValue]],
) -> InvestigationCase:
    if (
        task.role != "operator_response"
        or task.response_protocol not in {"engineer-v1", "engineer-v2"}
        or task.state not in {"SUCCEEDED", "ABSTAINED"}
        or task.result is None
        or task.snapshot_id != snapshot.id
        or task.generation_id != snapshot.generation_id
    ):
        raise ValidationError(
            "casefile_unavailable", "A completed scoped operator answer is required."
        )
    result = task.result
    if task.response_protocol == "engineer-v2":
        from .grounding import candidate_hash

        review_record = task.interpretation_review
        if (
            review_record is None
            or review_record.rounds[-1].candidate_hash != candidate_hash(result)
            or review_record.rounds[-1].assessment.decision != "accept"
        ):
            raise ValidationError(
                "grounding_required", "No accepted review for this exact interpretation."
            )
    inspection = None
    claims = [snapshot.claims[ref] for ref in result.claim_refs]
    if (
        task.state == "SUCCEEDED"
        and any(claim.kind == "location" for claim in claims)
        and snapshot.location is not None
        and snapshot.location.best is not None
        and snapshot.location.inspection_start_m is not None
        and snapshot.location.inspection_end_m is not None
    ):
        inspection = InspectionInterval(
            segment_id=snapshot.location.best.segment_id,
            start_m=snapshot.location.inspection_start_m,
            end_m=snapshot.location.inspection_end_m,
        )
    disposition = (
        "Resolve evidence gaps; location withheld"
        if result.outcome == "insufficient_evidence"
        else "Review supported inspection interval"
        if inspection
        else "Review sensor/telemetry evidence and competing explanations"
        if result.hypothesis == "sensor_or_telemetry_issue"
        else "Review the cited evidence; no safety clearance"
    )
    review = result.investigation
    cited = set(review.document_ids) if review else set()
    rejected = set(review.rejected_document_ids) if review else set()
    compared = set(review.comparison_call_ids) if review else set()
    sources: dict[str, CaseSource] = {}
    comparisons = []
    steps = []
    dependency_ids = {dependency.id for dependency in dependencies}
    for receipt in receipts:
        source_id = receipt.get("task_id")
        payload = receipt.get("result")
        args = receipt.get("arguments")
        if (
            not isinstance(source_id, str)
            or source_id not in dependency_ids
            or not isinstance(args, dict)
        ):
            raise ValidationError("casefile_scope", "Investigation receipt is not a linked source.")
        name, call_id, error = receipt.get("name"), receipt.get("call_id"), receipt.get("error")
        if not isinstance(name, str) or not isinstance(call_id, str):
            raise ValidationError("casefile_receipt", "Missing recorded tool identity.")
        sequence = payload.get("investigation_step") if isinstance(payload, dict) else None
        intent = args.get("intent")
        steps.append(
            InvestigationStep(
                task_id=source_id,
                call_id=call_id,
                tool=name,
                arguments=args,
                intent=str(intent or "not recorded"),
                error=str(error) if error else None,
                sequence=int(sequence) if isinstance(sequence, (int, float)) else 0,
            )
        )
        if error or not isinstance(payload, dict):
            continue
        if name == "history.read":
            documents = payload.get("documents")
            if not isinstance(documents, list):
                raise ValidationError("casefile_receipt", "Missing read documents.")
            for document in documents:
                if not isinstance(document, dict):
                    raise ValidationError("casefile_receipt", "Invalid reviewed document.")
                identifier = document.get("id")
                if not isinstance(identifier, str):
                    raise ValidationError("casefile_receipt", "Invalid reviewed document ID.")
                sources[identifier] = CaseSource(
                    document=document,
                    use="cited"
                    if identifier in cited
                    else ("rejected" if identifier in rejected else "read_not_cited"),
                )
        if name == "history.compare" and call_id in compared:
            comparisons.append({**payload, "call_id": call_id})
    if not (cited | rejected) <= sources.keys() or not compared <= {
        comparison["call_id"] for comparison in comparisons
    }:
        raise ValidationError("casefile_sources", "Accepted citations lack executed source reads.")
    fresh = [task, *[dep for dep in dependencies if dep.parent_id == task.id]]
    elapsed = max(0, (task.updated_at - task.created_at).total_seconds())
    return InvestigationCase(
        task_id=task.id,
        generation_id=task.generation_id,
        snapshot_id=snapshot.id,
        question=task.question,
        mode=task.mode,
        state=task.state,
        window_start=snapshot.window_start.isoformat(),
        window_end=snapshot.window_end.isoformat(),
        input_hash=snapshot.input_hash,
        pack_version=snapshot.pack_version,
        baseline_version=snapshot.baseline_version,
        parameter_version=snapshot.parameter_version,
        history_version=task.history_version,
        disposition=disposition,
        hypothesis=result.hypothesis,
        inspection=inspection,
        next_action=ACTION_LABELS[review.next_action]
        if review
        else ("Review the cited measurements with the integrity engineer."),
        interpretation=result.interpretation,
        checked_claims=claims,
        limitations=result.limitations,
        sources=list(sources.values()),
        comparisons=comparisons,
        steps=sorted(steps, key=lambda step: step.sequence),
        reused_task_ids=[dep.id for dep in dependencies if dep.parent_id != task.id],
        fresh_model_calls=sum(item.model_calls for item in fresh),
        fresh_tool_calls=sum(item.tool_calls for item in fresh),
        recorded_elapsed_seconds=elapsed,
        report_target_met=elapsed <= 300,
        interpretation_review=task.interpretation_review,
    )

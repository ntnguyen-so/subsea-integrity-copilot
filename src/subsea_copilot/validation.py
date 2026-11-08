"""Fail-closed claim gates and application-owned factual rendering."""

import json
import re
from typing import Any, NoReturn

from subsea_copilot.contracts import AgentResult, AgentTask, Claim, WindowSnapshot
from subsea_copilot.runtime.registry import LIMITATIONS, RECOMMENDATIONS, REGISTRY, RolePolicy


class ValidationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def parse_json(value: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        parsed: dict[str, Any] = {}
        for key, item in items:
            if key in parsed:
                raise ValidationError("structure", "Duplicate structured fields.")
            parsed[key] = item
        return parsed

    def constant(value: str) -> NoReturn:
        raise ValidationError("structure", "Nonfinite structured values are not accepted.")

    return json.loads(value, object_pairs_hook=pairs, parse_constant=constant)


def read_pinned_evidence(receipts: list[dict[str, Any]]) -> set[str]:
    return {
        ref
        for receipt in receipts
        if receipt["name"] == "evidence.get" and not receipt.get("error")
        for ref in (receipt.get("result") or {}).get("evidence", {})
    }


def bind_read_claim_evidence(
    result: AgentResult, snapshot: WindowSnapshot, receipts: list[dict[str, Any]]
) -> AgentResult:
    """Bind existing claim sources without authorizing unread or foreign evidence."""
    required: set[str] = set()
    for ref in result.claim_refs:
        claim = snapshot.claims.get(ref)
        if claim is None or claim.id != ref:
            raise ValidationError("citations", "Claim not in the immutable snapshot.")
        required.update(claim.evidence_ids)
    if not required <= snapshot.evidence.keys():
        raise ValidationError("evidence", "Claim evidence does not resolve in the snapshot.")
    if not required <= read_pinned_evidence(receipts):
        raise ValidationError("evidence_receipts", "Claim evidence must have been read.")
    missing = required - set(result.evidence_ids)
    return result.model_copy(
        update={"evidence_ids": [*result.evidence_ids, *sorted(missing)]}
    )


def question_requires_location(question: str) -> bool:
    """Conservative request gate; the model still proposes the semantic work plan."""
    return bool(
        re.search(
            r"\b(?:where|locat(?:e|ed|ion|ions|ing)|localization|chainage|segments?|sections?)\b",
            question,
            flags=re.IGNORECASE,
        )
    )


def abstention_claim_allowed(claim: Claim) -> bool:
    return claim.kind in {"coverage", "sensor_health", "limitation"}


def quality_facts_available(snapshot: WindowSnapshot) -> bool:
    return any(
        claim.kind in {"coverage", "sensor_health"}
        and claim.value is not None
        and claim.evidence_ids
        and all(ref in snapshot.evidence for ref in claim.evidence_ids)
        for claim in snapshot.claims.values()
    )


def compatible(task: AgentTask, other: AgentTask, snapshot: WindowSnapshot) -> bool:
    return (
        other.tenant_id == task.tenant_id
        and other.site_id == task.site_id
        and other.generation_id == task.generation_id
        and other.snapshot_id == snapshot.id
        and other.mode == task.mode
        and other.history_version == task.history_version
        and (other.knowledge_packet.identity() if other.knowledge_packet else None)
        == (task.knowledge_packet.identity() if task.knowledge_packet else None)
        and other.purpose == REGISTRY[other.role].purpose
        and other.state in {"SUCCEEDED", "ABSTAINED"}
        and other.result is not None
    )


def validate_result(
    value: str | dict[str, Any] | AgentResult,
    task: AgentTask,
    snapshot: WindowSnapshot,
    receipts: list[dict[str, Any]],
    dependencies: list[AgentTask] | None = None,
) -> AgentResult:
    return _validate_with_policy(
        value,
        task,
        snapshot,
        receipts,
        dependencies,
        policy=REGISTRY[task.role],
        specialist_contract=True,
    )


def validate_grounded_result(
    value: str | dict[str, Any] | AgentResult,
    task: AgentTask,
    snapshot: WindowSnapshot,
    receipts: list[dict[str, Any]],
    *,
    claim_kinds: frozenset[str],
) -> AgentResult:
    """Pure factual gates; callers separately authorize execution and evidence procedures."""
    policy = RolePolicy(task.purpose, frozenset(), frozenset(), 0, 0, claim_kinds)
    return _validate_with_policy(
        value,
        task,
        snapshot,
        receipts,
        None,
        policy=policy,
        specialist_contract=False,
    )


def _validate_with_policy(
    value: str | dict[str, Any] | AgentResult,
    task: AgentTask,
    snapshot: WindowSnapshot,
    receipts: list[dict[str, Any]],
    dependencies: list[AgentTask] | None,
    *,
    policy: RolePolicy,
    specialist_contract: bool,
) -> AgentResult:
    def reject(code: str, message: str) -> NoReturn:
        raise ValidationError(code, message)

    try:
        result = (
            value
            if isinstance(value, AgentResult)
            else AgentResult.model_validate(parse_json(value) if isinstance(value, str) else value)
        )
    except (ValueError, TypeError) as exc:
        raise ValidationError(
            "structure", "Result must match the frozen structured schema."
        ) from exc
    if (
        task.snapshot_id != snapshot.id
        or task.site_id != snapshot.site_id
        or task.tenant_id != snapshot.tenant_id
        or task.generation_id != snapshot.generation_id
    ):
        reject("scope", "Result scope differs from pinned evidence.")
    if task.knowledge_packet and (
        task.knowledge_packet.site_id != snapshot.site_id
        or task.knowledge_packet.pack_version != snapshot.pack_version
    ):
        reject("knowledge_scope", "Domain guidance differs from the pinned site or geometry.")
    if result.summary not in {"", "Evidence references only."}:
        reject("certainty", "Unrestricted prose is not an accepted factual channel.")
    if task.purpose != policy.purpose:
        reject("role", "Task purpose does not match its frozen role.")
    received = {r["name"] for r in receipts if not r.get("error")}
    if not policy.required <= received:
        reject("required_receipts", "Required read-only checks are missing.")
    if task.role == "sensor_quality" and not any(
        r["name"] == "ontology.neighbors"
        and not r.get("error")
        and r.get("result", {}).get("metadata")
        for r in receipts
    ):
        reject("required_metadata", "Quality needs pinned sensor/failure-domain metadata.")
    if task.role == "sensor_quality":
        if quality_facts_available(snapshot) and result.outcome != "supported":
            reject(
                "quality_outcome",
                "Grounded quality findings are supported even if physical evidence is absent.",
            )
        if (
            result.outcome == "supported"
            and all(ref in snapshot.claims for ref in result.claim_refs)
            and not any(
                snapshot.claims.get(ref) is not None
                and snapshot.claims[ref].kind in {"coverage", "sensor_health"}
                for ref in result.claim_refs
            )
        ):
            reject(
                "quality_scope", "Quality must cite a grounded coverage or sensor-health finding."
            )
        reviewed = {
            (finding["sensor_id"], finding["channel"])
            for r in receipts
            if r["name"] == "quality.sensor_patterns" and not r.get("error")
            for finding in (r.get("result") or {}).get("findings", [])
        }
        if len(reviewed) < len(snapshot.quality.findings) and (
            "partial_health_review" not in result.limitations
        ):
            reject("review_scope", "Bounded health review must disclose unreviewed findings.")
    dependencies = dependencies or []
    for dependency in dependencies:
        if not compatible(task, dependency, snapshot):
            reject("dependency_scope", "Dependency is not a compatible accepted result.")
    if task.role == "event_diagnosis":
        quality = [
            d
            for d in dependencies
            if d.role == "sensor_quality"
            and d.parent_id == task.parent_id
            and d.root_id == task.root_id
        ]
        if len(quality) != 1:
            reject("quality_dependency", "Diagnosis needs one accepted linked quality child.")
        if not any(
            r["name"] == "task.result"
            and not r.get("error")
            and r.get("arguments", {}).get("task_id") == quality[0].id
            for r in receipts
        ):
            reject("quality_receipt", "Diagnosis must consume the linked quality child.")
    if specialist_contract and task.role == "operator_response" and not dependencies:
        reject("dependencies", "Response requires an accepted scoped specialist.")
    if (
        specialist_contract
        and task.role == "operator_response"
        and any(
            not any(
                r["name"] == "task.result"
                and not r.get("error")
                and r.get("arguments", {}).get("task_id") == d.id
                for r in receipts
            )
            for d in dependencies
        )
    ):
        reject("dependency_receipts", "Response must consume every authorized specialist.")
    if specialist_contract and task.role in {"operator_response", "event_diagnosis"}:
        required_limits = {code for d in dependencies if d.result for code in d.result.limitations}
        if not required_limits <= set(result.limitations):
            reject("dependency_limitations", "Dependent task must retain specialist limitations.")
    if any(d.state == "ABSTAINED" for d in dependencies):
        if result.outcome != "insufficient_evidence" or "child_abstained" not in result.limitations:
            reject(
                "abstention", "Abstained specialist permits only explicit insufficient evidence."
            )
    disallowed_abstention_claims = [
        c
        for r, c in snapshot.claims.items()
        if r in result.claim_refs and not abstention_claim_allowed(c)
    ]
    if result.outcome == "insufficient_evidence" and (
        result.hypothesis not in {None, "insufficient_evidence"} or disallowed_abstention_claims
    ):
        reject("abstention", "Insufficient evidence cannot assert a physical event or location.")
    if len(set(result.claim_refs)) != len(result.claim_refs):
        reject("citations", "Duplicate claims.")
    for ref in result.claim_refs:
        claim = snapshot.claims.get(ref)
        if claim is None or claim.id != ref or claim.kind not in policy.claim_kinds:
            reject("citations", "Claim not in the pinned role ledger.")
        if not set(claim.evidence_ids) <= set(result.evidence_ids):
            reject("evidence", "Every claim's source evidence must be cited.")
        if claim.kind == "location":
            if "location.fit" not in received and (
                task.role == "event_diagnosis" or not specialist_contract
            ):
                reject("location_receipt", "Location requires a numerical fit receipt.")
            if not snapshot.event.eligible_location or not snapshot.location:
                reject("location", "Computed location is ineligible.")
            if snapshot.location.status not in {"located", "ambiguous"}:
                reject("location", "Withheld location is not a location claim.")
    if any(ref not in snapshot.evidence for ref in result.evidence_ids):
        reject("evidence", "Evidence does not resolve in the immutable snapshot.")
    if specialist_contract and task.role == "operator_response":
        read_evidence = read_pinned_evidence(receipts)
        if not set(result.evidence_ids) <= read_evidence:
            reject("evidence_receipts", "Response must read the cited pinned evidence.")
    ledger_codes = {
        str(c.value.get("code")) if isinstance(c.value, dict) else str(c.value)
        for c in snapshot.claims.values()
        if c.kind == "limitation"
    }
    if not set(result.limitations) <= LIMITATIONS | ledger_codes:
        reject("limitations", "Unknown uncertainty vocabulary.")
    mandatory = set(ledger_codes)
    if any(receipt.get("error") == "context_budget_exceeded" for receipt in receipts):
        mandatory.add("context_budget_exceeded")
    if snapshot.quality.status == "WARMING_UP" and "WARMING_UP" not in ledger_codes:
        mandatory.add("warming_up")
    if snapshot.quality.status == "COVERAGE_LOST" and "COVERAGE_LOST" not in ledger_codes:
        mandatory.add("coverage_lost")
    if (
        snapshot.location
        and snapshot.location.status == "ambiguous"
        and "LOCATION_AMBIGUOUS" not in ledger_codes
    ):
        mandatory.add("location_ambiguous")
    if not mandatory <= set(result.limitations):
        reject("limitations", "Material computed limitations cannot be omitted.")
    if task.role != "sensor_quality" and question_requires_location(task.question):
        has_location = any(snapshot.claims[r].kind == "location" for r in result.claim_refs)
        eligible_fit = (
            snapshot.event.eligible_location
            and snapshot.location is not None
            and snapshot.location.status in {"located", "ambiguous"}
        )
        if result.outcome == "supported" and eligible_fit and not has_location:
            reject(
                "location_required", "Section/location answer must cite the eligible computed fit."
            )
        if (result.outcome == "insufficient_evidence" or not eligible_fit) and not (
            {"location_withheld", "LOCATION_WITHHELD"} & set(result.limitations)
        ):
            reject("location_withheld_required", "Unavailable localization must be explicit.")
    if task.role == "sensor_quality" and result.hypothesis is not None:
        reject("hypothesis", "Quality cannot make event-hypothesis assertions.")
    if result.hypothesis is not None:
        if task.role == "sensor_quality" or result.hypothesis not in (
            snapshot.event.eligible_hypotheses + ["insufficient_evidence"]
        ):
            reject("hypothesis", "Hypothesis is not eligible for this role and snapshot.")
        hypothesis_claims = [
            snapshot.claims[r].value
            for r in result.claim_refs
            if snapshot.claims[r].kind == "hypothesis"
        ]
        if not any(
            v == result.hypothesis
            or isinstance(v, dict)
            and v.get("hypothesis") == result.hypothesis
            for v in hypothesis_claims
        ):
            reject("hypothesis_claim", "Hypothesis must reference its ledger claim.")
    if result.outcome == "supported" and not result.claim_refs:
        reject("claims", "Supported findings require ledger claims.")
    if (
        (task.role == "event_diagnosis" or not specialist_contract)
        and result.outcome == "supported"
        and result.hypothesis is None
    ):
        reject("hypothesis", "Diagnosis must select a structured eligible hypothesis.")
    if task.role != "operator_response" and result.recommendation_ids:
        reject("role", "Only response selects read-only recommendation IDs.")
    if not set(result.recommendation_ids) <= set(RECOMMENDATIONS):
        reject("recommendations", "Unknown or operational recommendation.")
    if "review_location_fit" in result.recommendation_ids and not snapshot.event.eligible_location:
        reject("location", "Location recommendation requires eligible numerical fit.")
    if specialist_contract and task.role == "operator_response":
        supported = {r for d in dependencies if d.result is not None for r in d.result.claim_refs}
        if not set(result.claim_refs) <= supported:
            reject("specialist_claims", "Response cannot introduce unreviewed specialist claims.")
        diagnoses = [d for d in dependencies if d.role == "event_diagnosis"]
        if diagnoses and result.outcome == "supported":
            if not any(
                d.result is not None and d.result.hypothesis == result.hypothesis for d in diagnoses
            ):
                reject("diagnosis_consistency", "Response must retain the accepted diagnosis.")
        if diagnoses:
            assert diagnoses[0].result is not None
            if result.investigation != diagnoses[0].result.investigation:
                reject("history_inheritance", "Response must retain the checked investigation.")
        elif result.investigation is not None:
            reject("history_inheritance", "A response cannot introduce unreviewed history.")
    if task.role == "event_diagnosis" and task.history_version:
        from subsea_copilot.investigation import validate_investigation

        validate_investigation(result, task, snapshot, receipts)
    elif result.investigation is not None and task.role != "operator_response":
        reject("history_authority", "Only a history-enabled diagnosis can introduce context.")
    from subsea_copilot.interpretation import validate_interpretation

    validate_interpretation(result, task, receipts)
    if task.response_protocol == "engineer-v2" and task.state in {"SUCCEEDED", "ABSTAINED"}:
        from subsea_copilot.grounding import validate_review

        validate_review(result, task, snapshot, receipts)
    return result


def render_result(result: AgentResult, task: AgentTask, snapshot: WindowSnapshot) -> str:
    """Never render model summary, raw JSON, or agent-reconstructed arithmetic."""
    lines = [
        f"{task.mode.upper()} · READ ONLY · analysis as of {snapshot.window_end.isoformat()}",
        "Insufficient evidence."
        if result.outcome == "insufficient_evidence"
        else "Supported snapshot evidence:",
    ]
    for ref in result.claim_refs:
        claim = snapshot.claims[ref]
        if claim.kind == "coverage":
            q = snapshot.quality
            lines.append(
                f"Usable coverage: {q.coverage * 100:.1f}% "
                f"({q.usable_samples}/{q.expected_samples} observations)."
            )
        elif claim.kind == "sensor_health":
            value: Any = claim.value
            sensor = value.get("sensor_id") if isinstance(value, dict) else None
            channel = value.get("channel") if isinstance(value, dict) else None
            for finding in snapshot.quality.findings:
                if sensor == finding.sensor_id and (channel is None or channel == finding.channel):
                    lines.append(
                        f"{finding.sensor_id} {finding.channel}: "
                        f"{finding.usable}/{finding.expected} usable; "
                        f"{finding.missing} unavailable values (missing or invalid); "
                        f"{finding.hard_excluded} invalid received observations; "
                        f"{finding.spike_count} spike-screening flags; "
                        f"drift suspicion: {finding.drift_suspected}; "
                        f"paired-instrument disagreement: {finding.peer_disagreement}."
                    )
        elif claim.kind == "hypothesis":
            labels = {
                "suspected_leak": "Suspected leak; not a confirmed diagnosis.",
                "sensor_or_telemetry_issue": (
                    "Sensor or telemetry issues warrant review; not a proven hardware diagnosis."
                ),
                "environmental_disturbance": "Environmental disturbance is supported.",
                "no_event": "No event supported in this window; not a safety conclusion.",
                "insufficient_evidence": "Insufficient evidence for an event conclusion.",
            }
            hypothesis = (
                claim.value.get("hypothesis") if isinstance(claim.value, dict) else claim.value
            )
            if hypothesis in labels:
                lines.append(labels[hypothesis])
                if hypothesis == "suspected_leak":
                    event = snapshot.event
                    lines.append(
                        f"Why: {len(event.supporting_sensor_ids)} pressure instruments across "
                        f"{event.failure_domain_count} failure domains show overlapping drops "
                        f"for {event.persistence_seconds:g}s. Review the cited sensor histories."
                    )
        elif claim.kind == "location" and snapshot.location:
            location = snapshot.location
            if location.inspection_start_m is not None and location.inspection_end_m is not None:
                segment = location.best.segment_id if location.best else "unresolved segment"
                lines.append(
                    f"Priority inspection interval: {segment} "
                    f"{location.inspection_start_m:.0f}-{location.inspection_end_m:.0f} m. "
                    "This is an inspection bracket, not an exact leak position."
                )
                if len(location.station_bracket_m) == 4:
                    before, first, last, after = location.station_bracket_m
                    boundary = (
                        "weaker neighboring" if location.method == "pressure-peak-focus-v1"
                        else "unaffected"
                    )
                    lines.append(
                        f"Why: affected stations at {first:g}/{last:g} m are bracketed by "
                        f"{boundary} stations at {before:g}/{after:g} m. "
                        "Inspection boundaries are the intervening station midpoints."
                    )
            else:
                lines.append(f"Location: {location.status}. {location.reason}")
    if result.limitations:
        explanations = {
            "GRID_NOT_ACCURACY": "The numerical grid spacing is not localization accuracy.",
            "COMPATIBLE_NOT_CONFIDENCE": "Compatible candidates are not a confidence interval.",
            "LOCATION_MODEL_SIMPLIFIED": "Location uses a simplified numerical propagation model.",
            "INSPECTION_INTERVAL_NOT_LEAK_POINT": (
                "Station spacing bounds an inspection priority, not the physical leak coordinate."
            ),
            "PRESSURE_PATTERNS_NOT_PROOF": (
                "Correlated pressure anomalies support investigation, not a confirmed leak."
            ),
            "OPERATING_CONTEXT_REQUIRED": (
                "Verify valve/compressor changes and shared instrumentation with the operator."
            ),
            "COMMON_MODE_PRESSURE_CHANGE": (
                "A broad pressure change can reflect operating changes or a shared failure; "
                "no localized leak is asserted."
            ),
            "CORRELATED_PRESSURE_TRANSIENT": (
                "Several instruments changed together, but the pressure pattern was too brief "
                "for leak criteria; check operating changes before attributing sensor faults."
            ),
            "NO_EVENT_NOT_SAFETY": "No-event evidence is not an operational safety determination.",
            "partial_health_review": (
                "Health claim review is bounded, not exhaustive; "
                "the full quality report is retained."
            ),
        }
        material = list(
            dict.fromkeys(explanations[c] for c in result.limitations if c in explanations)
        )
        if material:
            lines.append("Checks and uncertainties:")
            lines.extend(material)
    if {"location_withheld", "LOCATION_WITHHELD"} & set(result.limitations):
        lines.append("Location withheld; no supported section or chainage is asserted.")
    reviewed = sum(snapshot.claims[r].kind == "sensor_health" for r in result.claim_refs)
    if reviewed < len(snapshot.quality.findings):
        lines.append(
            f"Reviewed channel-health claims: {reviewed}/{len(snapshot.quality.findings)}; "
            "additional findings remain in the pinned quality report."
        )
    lines.extend(RECOMMENDATIONS[r] for r in result.recommendation_ids)
    return "\n".join(lines)

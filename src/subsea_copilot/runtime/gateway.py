"""Scoped immutable reads with persisted, idempotent dispatch receipts.

Untrusted model requests and application intake use the same role/snapshot/version
checks. Authorized reads return existing measurements, history or revalidated
specialist results; durable receipts bind request identity, arguments and outcome.
No provider request can write assets, choose a new scope or expand tool authority.
"""

import json
from typing import Any

from subsea_copilot.agent_evidence import measurement_snapshot
from subsea_copilot.budgets import (
    BUDGET_MULTIPLIER,
    CONTEXT_SENSOR_LIMIT,
    HEALTH_PAGE_SIZE,
    HISTORY_DOCUMENT_LIMIT,
)
from subsea_copilot.contracts import (
    TOOL_RESULT_MAX_BYTES,
    AgentTask,
    QualityFinding,
    Sensor,
    WindowSnapshot,
    content_hash,
)
from subsea_copilot.history import HistoryRangeCache, read_history
from subsea_copilot.profiles import compact_comparison
from subsea_copilot.public_activity import public_check, tool_selection
from subsea_copilot.runtime.diagnostics import validation_diagnostic
from subsea_copilot.runtime.registry import role_policy, tool_schemas
from subsea_copilot.store import BudgetExceeded
from subsea_copilot.synthetic import generate_pack
from subsea_copilot.validation import ValidationError, compatible


def ranked_findings(snapshot: WindowSnapshot) -> list[QualityFinding]:
    """Order a bounded health page by concerns, prioritizing exclusions on larger layouts."""
    support = set(snapshot.event.supporting_sensor_ids)
    return sorted(
        snapshot.quality.findings,
        key=lambda f: (
            not bool(f.hard_excluded or f.missing > f.expected * 0.1)
            if len(snapshot.quality.findings) > 32 * BUDGET_MULTIPLIER
            else False,
            f.sensor_id not in support
            if len(snapshot.quality.findings) > 32 * BUDGET_MULTIPLIER
            else False,
            not bool(
                f.hard_excluded
                or f.spike_count
                or f.drift_suspected
                or f.peer_disagreement
                or f.missing > f.expected * 0.1
            ),
            f.sensor_id,
            f.channel,
        ),
    )


def context_sensors(snapshot: WindowSnapshot) -> list[Sensor]:
    """Select a bounded legacy overview; measurement-only diagnosis sees the full layout."""
    sensors = generate_pack(snapshot.site_id, version=snapshot.pack_version).sensors
    if snapshot.event.criteria_id == "measurement-only-no-domain-decision":
        return sensors
    if len(sensors) <= 32 * BUDGET_MULTIPLIER:
        return sensors
    findings = {finding.sensor_id: finding for finding in ranked_findings(snapshot)}
    by_id = {sensor.id: sensor for sensor in sensors}
    ordered = [by_id[identifier] for identifier in findings]
    selected = {
        sensor.id: sensor for sensor in sensors if sensor.id in snapshot.event.supporting_sensor_ids
    }
    for segment in dict.fromkeys(sensor.segment_id for sensor in sensors):
        on_branch = [sensor for sensor in ordered if sensor.segment_id == segment]
        for flagged in (True, False):
            candidate = next(
                (
                    sensor
                    for sensor in on_branch
                    if bool(
                        findings[sensor.id].anomaly_count
                        or findings[sensor.id].missing
                        or findings[sensor.id].hard_excluded
                    )
                    == flagged
                ),
                None,
            )
            if candidate is not None:
                selected[candidate.id] = candidate
    for sensor in ordered:
        if len(selected) >= CONTEXT_SENSOR_LIMIT:
            break
        selected[sensor.id] = sensor
    return list(selected.values())[:CONTEXT_SENSOR_LIMIT]


def pressure_regions(snapshot: WindowSnapshot) -> list[dict[str, Any]]:
    """Summarize measured run extrema by branch, not simultaneous onset or physical cause."""
    if len(snapshot.quality.findings) <= 32 * BUDGET_MULTIPLIER:
        return []
    pack = generate_pack(snapshot.site_id, version=snapshot.pack_version)
    summaries = {
        evidence.sensor_id: evidence.value
        for evidence in snapshot.evidence.values()
        if evidence.kind == "channel_summary" and isinstance(evidence.value, dict)
    }
    regions = []
    for segment in pack.segments:
        region: dict[str, Any] = {"segment_id": segment.id}
        for direction in ("drop", "rise"):
            observed = [
                (sensor, summaries.get(sensor.id, {}).get(f"pressure_{direction}_period_seconds"))
                for sensor in pack.sensors
                if sensor.segment_id == segment.id
            ]
            periods: list[tuple[Sensor, tuple[float, float]]] = []
            for sensor, period in observed:
                if period is None:
                    continue
                if (
                    not isinstance(period, list)
                    or len(period) != 2
                    or not isinstance(period[0], int | float)
                    or not isinstance(period[1], int | float)
                ):
                    raise ValidationError("pressure_timing", "Invalid measured excursion period.")
                periods.append((sensor, (float(period[0]), float(period[1]))))
            region[direction] = {
                "sensor_ids": [sensor.id for sensor, _ in periods],
                "failure_domain_ids": sorted({sensor.failure_domain_id for sensor, _ in periods}),
                "earliest_run_start_seconds": min(
                    (period[0] for _, period in periods), default=None
                ),
                "latest_run_end_seconds": max((period[1] for _, period in periods), default=None),
            }
        if region["drop"]["sensor_ids"] or region["rise"]["sensor_ids"]:
            regions.append(region)
    return regions


class ToolGateway:
    """Enforce reads against one leased task and its pinned immutable evidence view."""
    def __init__(self, store: Any, task: AgentTask, snapshot: WindowSnapshot, telemetry: Any):
        if task.decision_policy == "llm-diagnosis-v1":
            snapshot = measurement_snapshot(snapshot)
        self.store, self.task, self.snapshot, self.telemetry = store, task, snapshot, telemetry
        self._history_ranges: HistoryRangeCache = {}

    def dependencies(self) -> list[AgentTask]:
        """Return compatible accepted tasks constrained by sibling/child or authorized reuse."""
        candidates = self.store.list_tasks(self.task.generation_id)
        if self.task.role == "event_diagnosis":
            return [
                t
                for t in candidates
                if t.parent_id == self.task.parent_id
                and t.root_id == self.task.root_id
                and t.role == "sensor_quality"
                and compatible(self.task, t, self.snapshot)
            ]
        if self.task.role == "operator_response":
            if "reuse" in self.task.plan:
                ids = set(self.store.reuse_task_ids(self.task.id))
                return [
                    t
                    for t in candidates
                    if t.id in ids
                    and t.role != "operator_response"
                    and compatible(self.task, t, self.snapshot)
                ]
            return [
                t
                for t in candidates
                if t.parent_id == self.task.id and compatible(self.task, t, self.snapshot)
            ]
        return []

    def _authorize(self, name: str, arguments: dict[str, Any]) -> None:
        if name not in role_policy(self.task.role, self.task.decision_policy).tools:
            raise ValidationError("tool_authority", "Tool is not allowed for this role.")
        self._validate_scope(arguments)

    def _argument_schemas(self) -> dict[str, Any]:
        return {
            schema["function"]["name"]: schema["function"]["parameters"]
            for schema in tool_schemas(self.task.role, self.task.decision_policy)
        }

    def _validate_scope(self, arguments: dict[str, Any]) -> None:
        """Require exact site, window and all numerical version pins before any read."""
        bound = {
            "site_id": self.snapshot.site_id,
            "snapshot_id": self.snapshot.id,
            "pack_version": self.snapshot.pack_version,
            "baseline_version": self.snapshot.baseline_version,
            "parameter_version": self.snapshot.parameter_version,
        }
        if (
            not isinstance(arguments, dict)
            or not set(bound) <= set(arguments)
            or any(arguments.get(key) != value for key, value in bound.items())
        ):
            raise ValidationError(
                "tool_scope", "Tool scope or version differs from pinned evidence."
            )

    def _validate_knowledge_check(self, name: str, arguments: dict[str, Any]) -> None:
        if name.startswith("history.") and self.task.knowledge_packet:
            applicable = {
                card.id for card in self.task.knowledge_packet.cards if self.task.role in card.roles
            }
            selected = arguments.get("knowledge_ids")
            question = arguments.get("check_question")
            if (
                not isinstance(selected, list)
                or not 1 <= len(selected) <= HISTORY_DOCUMENT_LIMIT
                or any(not isinstance(ref, str) or ref not in applicable for ref in selected)
                or len(set(selected)) != len(selected)
                or not isinstance(question, str)
                or not 1 <= len(question.strip()) <= 240
            ):
                raise ValidationError(
                    "knowledge_check_plan",
                    "Declare applicable knowledge_ids and a discriminating check_question.",
                )

    def _validate_arguments(
        self,
        name: str,
        arguments: dict[str, Any],
        schemas: dict[str, Any],
    ) -> None:
        schema = schemas[name]
        if (
            not isinstance(arguments, dict)
            or set(arguments) - set(schema["properties"])
            or not set(schema["required"]) <= set(arguments)
        ):
            raise ValidationError("tool_arguments", "Tool argument fields do not match the schema.")
        if "ids" in arguments:
            ids = arguments["ids"]
            if (
                not isinstance(ids, list)
                or len(ids) > 100 * BUDGET_MULTIPLIER
                or any(not isinstance(i, str) or i not in self.snapshot.evidence for i in ids)
            ):
                raise ValidationError("tool_arguments", "Evidence IDs must resolve within scope.")
        if "task_id" in arguments and not isinstance(arguments["task_id"], str):
            raise ValidationError("tool_arguments", "Task identity must be a string.")
        if "receipt_id" in arguments and (
            not isinstance(arguments["receipt_id"], str)
            or arguments.get("ids")
            or name != "evidence.get"
        ):
            raise ValidationError(
                "tool_arguments", "Receipt retrieval requires a receipt_id string and ids=[]."
            )
        if "offset" in arguments and (
            type(arguments["offset"]) is not int or arguments["offset"] < 0
        ):
            raise ValidationError("tool_arguments", "Page offset must be a nonnegative integer.")

    def _read(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Resolve an authorized read; the surrounding dispatcher owns audit and budgets."""
        snapshot = self.snapshot
        if name.startswith("history."):
            return read_history(
                self.store, self.task, snapshot, name, arguments, range_cache=self._history_ranges,
            )
        ledger = {
            k: c.model_dump(mode="json")
            for k, c in snapshot.claims.items()
            if c.kind in role_policy(self.task.role, self.task.decision_policy).claim_kinds
        }
        basic = {k: c for k, c in ledger.items() if c["kind"] in {"coverage", "limitation"}}
        event = {k: c for k, c in ledger.items() if c["kind"] in {"hypothesis", "limitation"}}
        if name == "evidence.get":
            if "receipt_id" in arguments:
                # Retrieval reopens this task's original result; it never reruns that tool.
                receipt = next(
                    (
                        item for item in self.store.tool_receipts(self.task.id)
                        if item["call_id"] == arguments["receipt_id"]
                        and not item.get("error") and item.get("result") is not None
                    ),
                    None,
                )
                if receipt is None:
                    raise ValidationError(
                        "receipt_scope", "Successful receipt is not available in this task."
                    )
                return {
                    **receipt["result"],
                    "retrieved_from_receipt": {
                        "receipt_id": receipt["call_id"],
                        "tool": receipt["name"],
                        "result_sha256": content_hash(receipt["result"]),
                    },
                }
            ids = arguments.get("ids", [])
            selected = {k: c for k, c in ledger.items() if set(c["evidence_ids"]) <= set(ids)}
            return {
                "claims": selected,
                "evidence": {i: snapshot.evidence[i].model_dump(mode="json") for i in ids},
                "pagination": {
                    "explicit_ids_required": True,
                    "total_evidence": len(snapshot.evidence),
                },
            }
        if name == "quality.coverage":
            quality = snapshot.quality.model_dump(mode="json", exclude={"findings"})
            return {"quality": quality, "claims": basic}
        if name == "quality.conflicts":
            return {
                "conflicts": snapshot.quality.conflicts,
                "issues": snapshot.quality.issues,
                "hard_excluded": [
                    {"sensor_id": f.sensor_id, "channel": f.channel, "count": f.hard_excluded}
                    for f in snapshot.quality.findings
                ],
                "claims": basic,
            }
        if name == "quality.sensor_patterns":
            start = arguments.get("offset", 0)
            findings = ranked_findings(snapshot)
            page = findings[start : start + HEALTH_PAGE_SIZE]
            identities = {(f.sensor_id, f.channel) for f in page}
            selected = {
                k: c
                for k, c in ledger.items()
                if c["kind"] == "sensor_health"
                and isinstance(c["value"], dict)
                and (c["value"].get("sensor_id"), c["value"].get("channel")) in identities
            }
            return {
                "findings": [f.model_dump(
                    mode="json",
                    exclude={"drift_suspected", "peer_disagreement"}
                    if self.task.decision_policy == "llm-diagnosis-v1" else set(),
                ) for f in page],
                "pagination": {
                    "total": len(findings),
                    "offset": start,
                    "next_offset": start + HEALTH_PAGE_SIZE
                    if start + HEALTH_PAGE_SIZE < len(findings)
                    else None,
                },
                "policy": "Usable spikes/drift are not hard invalidity.",
                "claims": selected,
                "limitations": ["partial_health_review"] if len(page) < len(findings) else [],
                "review_contract": (
                    "This is a bounded claim review, not exhaustive attribution. "
                    "Do not exhaust pagination within this task; "
                    "full computed findings are retained."
                ),
            }
        if name == "ontology.neighbors":
            metadata = [
                e.model_dump(mode="json")
                for e in snapshot.evidence.values()
                if e.kind in {"sensor_metadata", "topology", "ontology"}
            ]
            if (
                self.task.decision_policy == "legacy-v1"
                and len(snapshot.quality.findings) > 32 * BUDGET_MULTIPLIER
            ):
                selected_ids = {sensor.id for sensor in context_sensors(snapshot)}
                for item in metadata:
                    value = item["value"]
                    if isinstance(value, dict) and isinstance(value.get("sensors"), list):
                        value["sensors"] = [
                            sensor for sensor in value["sensors"] if sensor["id"] in selected_ids
                        ]
                        value["scope"] = {
                            "total_instruments": len(snapshot.quality.findings),
                            "included_instruments": len(value["sensors"]),
                            "partial": True,
                        }
            return {
                "metadata": metadata,
                "failure_domain_count": snapshot.quality.failure_domains_available,
            }
        if name == "pressure.measurements":
            return {
                "evidence_ids": [
                    identifier
                    for identifier, item in snapshot.evidence.items()
                    if item.kind == "channel_summary"
                ],
                "claims": {
                    key: claim for key, claim in basic.items()
                    if claim["kind"] in {"coverage", "limitation"}
                },
                "policy": (
                    "Read these pressure measurements with evidence.get. "
                    "This catalog supplies no diagnosis, fault classification or location."
                ),
            }
        if name == "event.assess":
            return {"assessment": snapshot.event.model_dump(mode="json"), "claims": event}
        if name == "event.counterevidence":
            return {
                "counterevidence": snapshot.event.counterevidence,
                "eligible_hypotheses": snapshot.event.eligible_hypotheses,
                "claims": event,
            }
        if name == "location.fit":
            if not snapshot.event.eligible_location or snapshot.location is None:
                raise ValidationError("location_ineligible", "No eligible computed location fit.")
            return {
                "fit": snapshot.location.model_dump(mode="json"),
                "claims": {
                    k: c
                    for k, c in ledger.items()
                    if c["kind"] == "location"
                    and snapshot.location.status in {"located", "ambiguous"}
                },
            }
        if name == "criteria.explain":
            return {
                "criteria_id": snapshot.event.criteria_id,
                "pack_version": snapshot.pack_version,
                "baseline_version": snapshot.baseline_version,
                "parameter_version": snapshot.parameter_version,
                "policy": "Read-only; usable anomalies preserved; no confirmed or safe status.",
            }
        if name == "task.result":
            child = self.store.get_task(arguments["task_id"])
            if child is None or not compatible(self.task, child, snapshot):
                raise ValidationError(
                    "dependency_scope", "Task result is not accepted in this scope."
                )
            if self.task.role == "event_diagnosis" and (
                child.parent_id != self.task.parent_id
                or child.root_id != self.task.root_id
                or child.role != "sensor_quality"
            ):
                raise ValidationError(
                    "quality_dependency", "Diagnosis may read only linked quality."
                )
            if self.task.role == "operator_response" and (
                child.role == "operator_response"
                or (
                    "reuse" in self.task.plan
                    and child.id not in self.store.reuse_task_ids(self.task.id)
                )
                or ("reuse" not in self.task.plan and child.parent_id != self.task.id)
            ):
                raise ValidationError("dependency_lineage", "Unlinked specialist result.")
            # Recheck the original specialist result; cached acceptance is not authority.
            from subsea_copilot.validation import validate_result

            gateway = ToolGateway(self.store, child, snapshot, self.telemetry)
            validate_result(
                child.result,
                child,
                snapshot,
                self.store.tool_receipts(child.id),
                gateway.dependencies(),
            )
            reviewed_context: dict[str, Any] | None = None
            review = child.result.investigation
            if self.task.response_protocol in {"engineer-v1", "engineer-v2"} and review is not None:
                reads = self.store.tool_receipts(child.id)
                reviewed_context = {
                    "documents": [
                        document
                        for receipt in reads
                        if receipt["name"] == "history.read" and not receipt.get("error")
                        for document in (receipt.get("result") or {}).get("documents", [])
                        if document["id"] in review.document_ids
                    ],
                    "comparisons": [
                        compact_comparison({"call_id": receipt["call_id"], **receipt["result"]})
                        for receipt in reads
                        if receipt["call_id"] in review.comparison_call_ids
                        and not receipt.get("error")
                    ],
                }
                if self.task.decision_policy == "llm-diagnosis-v1":
                    comparisons = reviewed_context["comparisons"]
                    offset = arguments.get("comparison_offset", 0)
                    if offset and offset >= len(comparisons):
                        raise ValidationError("handoff_page", "Comparison page is out of range.")
                    reviewed_context["comparisons"] = comparisons[offset:offset + 1]
                    reviewed_context["pagination"] = {
                        "offset": offset, "total": len(comparisons),
                        "next_offset": offset + 1 if offset + 1 < len(comparisons) else None,
                    }
            return {
                "task_id": child.id,
                "role": child.role,
                "state": child.state,
                "result": child.result.model_dump(mode="json"),
                "reviewed_context": reviewed_context,
            }
        raise ValidationError("tool_authority", "Unknown read.")

    def _trace_attributes(self, call: dict[str, Any]) -> dict[str, Any]:
        selection = tool_selection(self.task.role, call)
        name = (
            call["name"] if call["name"] in role_policy(
                self.task.role, self.task.decision_policy
            ).tools else "unauthorized"
        )
        return {
            "task_id": self.task.id,
            "role": self.task.role,
            "tool": name,
            "call_id": call["id"],
            "dispatch_origin": selection["origin"],
            "selection.provenance": selection["decision_provenance"],
            "model_call_id": selection["model_call_id"] or "",
            "model_span_id": selection["model_span_id"] or "",
            "model.turn.index": selection["model_turn_index"] or 0,
            "tool.selection.input": json.dumps(selection, allow_nan=False),
            "langfuse.observation.input": json.dumps({
                "tool": name,
                "arguments": call["args"],
                "selection": selection,
                "scope": {
                    "snapshot_id": self.snapshot.id,
                    "input_hash": self.snapshot.input_hash,
                    "window_start_seconds": self.snapshot.end_seconds - (
                        self.snapshot.window_end - self.snapshot.window_start
                    ).total_seconds(),
                    "window_end_seconds": self.snapshot.end_seconds,
                    "source_clock_seconds": self.snapshot.clock_seconds,
                    "decision_policy": self.task.decision_policy,
                },
            }, allow_nan=False),
        }

    def _trace_outcome(
        self, span: Any, call: dict[str, Any], result: dict[str, Any] | None,
        error: str | None, diagnostic: dict[str, Any] | None, *,
        executed: bool, replayed: bool = False,
    ) -> None:
        update = public_check(
            self.task.role, call["id"], call["name"], call["args"],
            result, error, completed=True,
        )
        execution = {
            "executed": executed,
            "accepted": error is None,
            "replayed": replayed,
            "progress": error is None and not replayed,
            "execution_order": None if replayed else self.task.tool_calls,
        }
        for key, value in execution.items():
            span.set_attribute(f"tool.{key}", value)
        span.set_attribute(
            "outcome", "failed" if error else "replayed" if replayed else "completed",
        )
        span.set_attribute("evidence.claim_count", len(update.get("claim_refs", [])))
        span.set_attribute(
            "langfuse.observation.output",
            json.dumps({
                "public_update": update, "execution": execution,
                "result": result, "error": error, "rejection": diagnostic,
            }, allow_nan=False),
        )
        span.add_event("tool.activity", {
            "call_id": call["id"], "tool": call["name"], "role": self.task.role,
            "tool.accepted": error is None, "tool.executed": executed,
            "tool.replayed": replayed,
            "tool.selection.input": json.dumps(tool_selection(self.task.role, call)),
            "tool.result.output": json.dumps(update),
        })

    def dispatch(self, call: dict[str, Any]) -> dict[str, Any]:
        """Authorize, replay-or-reserve, execute and persist a bounded read outcome."""
        call_id, name, arguments = call["id"], call["name"], call["args"]
        diagnostic: dict[str, Any] | None = None
        try:
            self._authorize(name, arguments)
            # Scope is checked even on replay; the same call ID cannot acquire a new payload.
            for receipt in self.store.tool_receipts(self.task.id):
                if receipt["call_id"] == call_id:
                    if receipt["name"] != name or receipt["arguments"] != arguments:
                        raise ValidationError(
                            "receipt_conflict", "Replayed call changed its payload."
                        )
                    with self.telemetry.span(
                        f"tool.{name}", self._trace_attributes(call),
                    ) as span:
                        self._trace_outcome(
                            span, call, receipt.get("result"), receipt.get("error"),
                            receipt.get("diagnostic"), executed=False, replayed=True,
                        )
                    return {
                        "result": receipt.get("result"), "error": receipt.get("error"),
                        **(
                            {"rejection": receipt["diagnostic"]}
                            if receipt.get("diagnostic") else {}
                        ),
                    }
            self.task = self.store.reserve_tool_call(
                self.task.id, self.task.lease_token,
                role_policy(self.task.role, self.task.decision_policy).tool_limit
            )
        except (ValidationError, BudgetExceeded) as exc:
            assert self.task.lease_token is not None
            diagnostic = {
                **validation_diagnostic(
                    ValidationError(exc.code, "Persisted tool-call budget exhausted.")
                    if isinstance(exc, BudgetExceeded) else exc
                ),
                "call_id": call_id, "role": self.task.role,
                "tool": name if name in role_policy(
                    self.task.role, self.task.decision_policy
                ).tools else "unauthorized",
                "executed": False, "result_accepted": False, "repair_requested": False,
            }
            self.store.record_task_event(
                self.task.id, self.task.lease_token, "tool.rejected", diagnostic
            )
            with self.telemetry.span("tool.rejected", self._trace_attributes(call)) as span:
                span.set_attribute("error.code", exc.code)
                span.set_attribute("tool.executed", False)
                span.set_attribute("tool.accepted", False)
                span.set_attribute("langfuse.observation.output", json.dumps(diagnostic))
                span.record_exception(exc)
            raise
        update = public_check(self.task.role, call_id, name, arguments)
        update["origin"] = call.get("origin", "model_request")
        self.store.publish_event(
            self.task.generation_id,
            "agent.check_started",
            update,
            task_id=self.task.id,
            snapshot_id=self.task.snapshot_id,
        )
        result, error = None, None
        diagnostic = None
        executed = False
        with self.telemetry.span(
            f"tool.{name}",
            self._trace_attributes(call),
        ) as span:
            try:
                # Argument failures consume the reserved attempt but yield no accepted evidence.
                self._validate_arguments(
                    name, arguments, self._argument_schemas(),
                )
                self._validate_knowledge_check(name, arguments)
                executed = True
                result = self._read(name, arguments)
                if name.startswith("history."):
                    result["investigation_step"] = self.task.tool_calls
                    result["intent"] = arguments["intent"]
                if len(json.dumps(result, allow_nan=False).encode()) > TOOL_RESULT_MAX_BYTES:
                    result = None
                    raise ValidationError(
                        "payload_too_large", "Required evidence exceeds the tool payload allowance."
                    )
            except ValidationError as exc:
                error = exc.code
                span.set_attribute("error.code", error)
                span.record_exception(exc)
                assert self.task.lease_token is not None
                diagnostic = {
                    **validation_diagnostic(exc), "call_id": call_id, "tool": name,
                    "role": self.task.role, "executed": executed, "result_accepted": False,
                    "repair_requested": False,
                }
                self.store.record_task_event(
                    self.task.id, self.task.lease_token, "tool.rejected", diagnostic,
                )
            except Exception as exc:
                error = getattr(exc, "code", "tool_failed")
                span.set_attribute("error.code", error)
                self._trace_outcome(
                    span, call, None, error, {
                        "code": error,
                        "exception_type": type(exc).__name__,
                        "sqlstate": getattr(exc, "sqlstate", None),
                        "executed": executed,
                        "result_accepted": False,
                        "repair_requested": False,
                    }, executed=executed,
                )
                raise
            self.store.record_tool_call(
                self.task.id,
                call_id,
                name,
                arguments,
                result,
                error,
                lease_token=self.task.lease_token,
                diagnostic=diagnostic,
            )
            update = public_check(
                self.task.role, call_id, name, arguments, result, error, completed=True
            )
            update["origin"] = call.get("origin", "model_request")
            self.store.publish_event(
                self.task.generation_id,
                "agent.check_completed",
                update,
                task_id=self.task.id,
                snapshot_id=self.task.snapshot_id,
            )
            self._trace_outcome(span, call, result, error, diagnostic, executed=executed)
            span.add_event(
                "evidence.returned",
                {
                    "call_id": call_id,
                    "tool": name,
                    "role": self.task.role,
                    "outcome": "failed" if error else "completed",
                    "evidence.claim_count": len(update.get("claim_refs", [])),
                },
            )
        return {
            "result": result, "error": error,
            **({"rejection": diagnostic} if diagnostic is not None else {}),
        }

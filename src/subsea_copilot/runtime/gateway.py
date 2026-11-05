"""Scoped immutable reads with persisted, idempotent dispatch receipts."""

import json
from typing import Any

from subsea_copilot.contracts import AgentTask, WindowSnapshot
from subsea_copilot.runtime.registry import REGISTRY, tool_schemas
from subsea_copilot.validation import ValidationError, compatible


class ToolGateway:
    def __init__(self, store: Any, task: AgentTask, snapshot: WindowSnapshot, telemetry: Any):
        self.store, self.task, self.snapshot, self.telemetry = store, task, snapshot, telemetry

    def dependencies(self) -> list[AgentTask]:
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
        schemas = {
            s["function"]["name"]: s["function"]["parameters"] for s in tool_schemas(self.task.role)
        }
        if name not in REGISTRY[self.task.role].tools:
            raise ValidationError("tool_authority", "Tool is not allowed for this role.")
        self._validate_arguments(name, arguments, schemas)

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
        bound = {
            "site_id": self.snapshot.site_id,
            "snapshot_id": self.snapshot.id,
            "pack_version": self.snapshot.pack_version,
            "baseline_version": self.snapshot.baseline_version,
            "parameter_version": self.snapshot.parameter_version,
        }
        if any(arguments.get(k) != v for k, v in bound.items()):
            raise ValidationError(
                "tool_scope", "Tool scope or version differs from pinned evidence."
            )
        if "ids" in arguments:
            ids = arguments["ids"]
            if (
                not isinstance(ids, list)
                or len(ids) > 100
                or any(not isinstance(i, str) or i not in self.snapshot.evidence for i in ids)
            ):
                raise ValidationError("tool_arguments", "Evidence IDs must resolve within scope.")
        if "task_id" in arguments and not isinstance(arguments["task_id"], str):
            raise ValidationError("tool_arguments", "Task identity must be a string.")
        if "offset" in arguments and (
            type(arguments["offset"]) is not int or arguments["offset"] < 0
        ):
            raise ValidationError("tool_arguments", "Page offset must be a nonnegative integer.")

    def _read(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        snapshot = self.snapshot
        ledger = {
            k: c.model_dump(mode="json")
            for k, c in snapshot.claims.items()
            if c.kind in REGISTRY[self.task.role].claim_kinds
        }
        basic = {k: c for k, c in ledger.items() if c["kind"] in {"coverage", "limitation"}}
        event = {k: c for k, c in ledger.items() if c["kind"] in {"hypothesis", "limitation"}}
        if name == "evidence.get":
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
            findings = sorted(
                snapshot.quality.findings,
                key=lambda f: (
                    not bool(f.hard_excluded or f.spike_count or f.drift_suspected),
                    f.sensor_id,
                    f.channel,
                ),
            )
            page = findings[start : start + 8]
            identities = {(f.sensor_id, f.channel) for f in page}
            selected = {
                k: c
                for k, c in ledger.items()
                if c["kind"] == "sensor_health"
                and isinstance(c["value"], dict)
                and (c["value"].get("sensor_id"), c["value"].get("channel")) in identities
            }
            return {
                "findings": [f.model_dump(mode="json") for f in page],
                "pagination": {
                    "total": len(findings),
                    "offset": start,
                    "next_offset": start + 8 if start + 8 < len(findings) else None,
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
            return {
                "metadata": [
                    e.model_dump(mode="json")
                    for e in snapshot.evidence.values()
                    if e.kind in {"sensor_metadata", "topology", "ontology"}
                ],
                "failure_domain_count": snapshot.quality.failure_domains_available,
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
            return {
                "task_id": child.id,
                "role": child.role,
                "state": child.state,
                "result": child.result.model_dump(mode="json"),
            }
        raise ValidationError("tool_authority", "Unknown read.")

    def dispatch(self, call: dict[str, Any]) -> dict[str, Any]:
        call_id, name, arguments = call["id"], call["name"], call["args"]
        self._authorize(name, arguments)
        for receipt in self.store.tool_receipts(self.task.id):
            if receipt["call_id"] == call_id:
                if receipt["name"] != name or receipt["arguments"] != arguments:
                    raise ValidationError("receipt_conflict", "Replayed call changed its payload.")
                return {"result": receipt.get("result"), "error": receipt.get("error")}
        self.task = self.store.reserve_tool_call(
            self.task.id, self.task.lease_token, REGISTRY[self.task.role].tool_limit
        )
        result, error = None, None
        with self.telemetry.span(
            "tool",
            {
                "task_id": self.task.id,
                "tool": name,
                "call_id": call_id,
                "dispatch_origin": call.get("origin", "model_request"),
            },
        ):
            try:
                result = self._read(name, arguments)
                if len(json.dumps(result, allow_nan=False).encode()) > 12 * 1024:
                    raise ValidationError("payload_too_large", "Required evidence exceeds 12 KiB.")
            except ValidationError as exc:
                error = exc.code
            self.store.record_tool_call(
                self.task.id,
                call_id,
                name,
                arguments,
                result,
                error,
                lease_token=self.task.lease_token,
            )
        return {"result": result, "error": error}

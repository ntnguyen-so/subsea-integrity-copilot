"""Adaptive model views; durable transcripts and original tool evidence are never rewritten.

Messages, successful receipts and tool schemas become a bounded serialized prompt.
Lossless evidence consolidation precedes staged archival; archived bodies remain
retrievable by task-local receipt ID. Missing prompt detail is not missing data,
and compaction never manufactures a read or a new numerical claim.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AnyMessage, HumanMessage, ToolMessage

from subsea_copilot.contracts import content_hash
from subsea_copilot.llm.copilot_cli import render_prompt
from subsea_copilot.profiles import compact_evidence
from subsea_copilot.prompts import load_prompt
from subsea_copilot.validation import ValidationError

CONTEXT_POLICY_VERSION = "provenance-model-view-v2"
# Character allowances, not token estimates: leave room below the adapter's hard limit.
CONTEXT_HEADROOM_CHARS = 8000
# Progressively retain 4, 2, then 0 recent bodies; immutable receipts remain in storage.
COMPACTION_STAGES = (4, 2, 0)
CONTEXT_INSTRUCTION = load_prompt("context-view").content.removesuffix("\n")


@dataclass(frozen=True)
class ModelContext:
    messages: list[AnyMessage]
    prompt: str
    original_chars: int
    limit: int
    stage: int
    archived_receipts: list[dict[str, Any]]
    consolidated_receipts: list[dict[str, Any]] = field(default_factory=list)

    def metadata(self) -> dict[str, Any]:
        return {
            "policy_version": CONTEXT_POLICY_VERSION,
            "original_chars": self.original_chars,
            "prompt_chars": len(self.prompt),
            "limit_chars": self.limit,
            "stage": self.stage,
            "archived_receipts": self.archived_receipts,
            "consolidated_receipts": self.consolidated_receipts,
        }


def _consolidate_evidence(
    messages: Sequence[AnyMessage], receipts: Sequence[dict[str, Any]]
) -> tuple[list[AnyMessage], list[dict[str, Any]]]:
    """Deduplicate original evidence bodies by kind, rejecting conflicting repeated IDs."""
    by_id = {
        receipt["call_id"]: receipt
        for receipt in receipts
        if receipt["name"] == "evidence.get" and not receipt.get("error")
        and isinstance(receipt.get("result"), dict)
        and isinstance(receipt["result"].get("evidence"), dict)
        and isinstance(receipt["result"].get("claims"), dict)
        and not receipt["result"].get("retrieved_from_receipt")
    }
    present = set()
    for message in messages:
        if isinstance(message, ToolMessage):
            present.add(message.tool_call_id)
        elif (
            isinstance(message, HumanMessage) and isinstance(message.content, str)
            and message.content.startswith('{"application_intake":')
        ):
            present.update(
                entry.get("call_id")
                for entry in json.loads(message.content)["application_intake"]
            )
    selected = [receipt for identifier, receipt in by_id.items() if identifier in present]
    if len(selected) < 2:
        return list(messages), []
    evidence: dict[str, Any] = {}
    claims: dict[str, Any] = {}
    for receipt in selected:
        for key, destination in (("evidence", evidence), ("claims", claims)):
            for identifier, item in receipt["result"][key].items():
                if identifier in destination and destination[identifier] != item:
                    raise ValidationError(
                        "context_claim_conflict", "Scoped receipts disagree on retained evidence.",
                        details={"reference": identifier},
                    )
                destination[identifier] = item
    groups: dict[str, dict[str, Any]] = {}
    for identifier, item in evidence.items():
        groups.setdefault(item["kind"], {})[identifier] = item
    references = [
        {
            "receipt_id": receipt["call_id"],
            "tool": receipt["name"],
            "result_sha256": content_hash(receipt["result"]),
            "details_in_prompt": True,
        }
        for receipt in selected
    ]
    identifiers = {receipt["call_id"] for receipt in selected}

    def pointer(identifier: str) -> dict[str, Any]:
        return {
            "result": {
                "receipt_id": identifier,
                "details_in_prompt": True,
                "model_view": "context.read_evidence",
            },
            "error": None,
        }

    projected: list[AnyMessage] = []
    for message in messages:
        if isinstance(message, ToolMessage) and message.tool_call_id in identifiers:
            projected.append(message.model_copy(update={
                "content": json.dumps(pointer(message.tool_call_id), separators=(",", ":")),
            }))
        elif (
            isinstance(message, HumanMessage) and isinstance(message.content, str)
            and message.content.startswith('{"application_intake":')
        ):
            payload = json.loads(message.content)
            payload["application_intake"] = [
                {**entry, "output": pointer(entry["call_id"])}
                if entry.get("call_id") in identifiers else entry
                for entry in payload["application_intake"]
            ]
            projected.append(message.model_copy(update={
                "content": json.dumps(payload, allow_nan=False, separators=(",", ":")),
            }))
        else:
            projected.append(message)
    projected.append(HumanMessage(content=json.dumps({
        "application_intake": [{
            "name": "context.read_evidence",
            "origin": "model_view_not_a_tool_read",
            "output": {"result": {
                "claims": compact_evidence({"evidence": evidence, "claims": claims})["claims"],
                "evidence_groups": {
                    kind: compact_evidence(
                        {"evidence": items, "claims": {}}, columnar_all_kinds=True
                    )
                    for kind, items in groups.items()
                },
            }, "error": None},
        }],
        "receipt_sources": references,
        "instruction": (
            "These are the complete original measurements from the listed successful reads, "
            "consolidated losslessly by evidence kind. Decode each group's shared fields and "
            "value columns. Claim value_from_evidence_id resolves in these groups. "
            "Use actual ledger keys for claim_refs, not a model-view name. "
            "Only interpretation explanation references may use the supplied "
            "read_evidence_reference; never put that token in evidence_ids or claim_refs. "
            "No values were filled, rounded or classified by this projection."
        ),
    }, allow_nan=False, separators=(",", ":"))))
    return projected, references


def model_context(
    messages: Sequence[AnyMessage],
    receipts: Sequence[dict[str, Any]],
    tools: Sequence[dict[str, Any]],
    *,
    limit: int,
) -> ModelContext:
    """Choose a fitting model-only projection or fail closed without truncating claims."""
    original = render_prompt(messages, tools)
    messages, consolidated = _consolidate_evidence(messages, receipts)
    projected_prompt = render_prompt(messages, tools)
    target = max(0, limit - CONTEXT_HEADROOM_CHARS)
    if len(projected_prompt) <= target:
        return ModelContext(
            list(messages), projected_prompt, len(original), limit, 0, [], consolidated
        )
    consolidated_ids = {receipt["receipt_id"] for receipt in consolidated}
    by_id = {
        receipt["call_id"]: receipt for receipt in receipts
        if not receipt.get("error") and receipt["call_id"] not in consolidated_ids
    }
    ordered: list[str] = []
    for message in messages:
        if isinstance(message, ToolMessage) and message.tool_call_id in by_id:
            ordered.append(message.tool_call_id)
        elif isinstance(message, HumanMessage) and isinstance(message.content, str):
            if message.content.startswith('{"application_intake":'):
                for entry in json.loads(message.content)["application_intake"]:
                    if entry.get("call_id") in by_id:
                        ordered.append(entry["call_id"])
    ordered = list(dict.fromkeys(ordered))
    latest_by_tool = {by_id[identifier]["name"]: identifier for identifier in ordered}
    retrieved = [
        identifier for identifier in ordered
        if by_id[identifier]["name"] == "evidence.get"
        and by_id[identifier]["result"].get("retrieved_from_receipt")
    ]
    fallback = (
        ModelContext(
            list(messages), projected_prompt, len(original), limit, 0, [], consolidated
        )
        if len(projected_prompt) <= limit
        else None
    )
    for stage, recent in enumerate(COMPACTION_STAGES, start=1):
        # Early stages keep tool diversity; every stage preserves the latest retrieved body.
        keep = set(ordered[-recent:]) if recent else set()
        if retrieved:
            keep.add(retrieved[-1])
        if stage < 3:
            keep.update(latest_by_tool.values())
        archived = [identifier for identifier in ordered if identifier not in keep]
        if not archived:
            continue
        claims: dict[str, Any] = {}
        references: list[dict[str, Any]] = []
        for identifier in archived:
            receipt = by_id[identifier]
            result = receipt["result"]
            for ref, claim in result.get("claims", {}).items():
                if ref in claims and claims[ref] != claim:
                    raise ValidationError(
                        "context_claim_conflict",
                        "Scoped receipts disagree on a retained claim.",
                        details={"claim_ref": ref},
                    )
                claims[ref] = claim
            references.append(
                {
                    "receipt_id": identifier,
                    "tool": receipt["name"],
                    "result_sha256": content_hash(result),
                    "details_in_prompt": False,
                }
            )
        archive_ids = set(archived)

        def projected(identifier: str) -> dict[str, Any]:
            return {
                "result": {
                    "archived_receipt_id": identifier,
                    "details_in_prompt": False,
                    "retrieval_tool": "evidence.get",
                },
                "error": None,
            }

        selected: list[AnyMessage] = []
        for message in messages:
            if isinstance(message, ToolMessage) and message.tool_call_id in archive_ids:
                selected.append(
                    message.model_copy(
                        update={
                            "content": json.dumps(
                                projected(message.tool_call_id), separators=(",", ":")
                            ),
                        }
                    )
                )
            elif (
                isinstance(message, HumanMessage)
                and isinstance(message.content, str)
                and message.content.startswith('{"application_intake":')
            ):
                payload = json.loads(message.content)
                payload["application_intake"] = [
                    {**entry, "output": projected(entry["call_id"])}
                    if entry.get("call_id") in archive_ids
                    else entry
                    for entry in payload["application_intake"]
                ]
                selected.append(
                    message.model_copy(
                        update={
                            "content": json.dumps(payload, allow_nan=False, separators=(",", ":")),
                        }
                    )
                )
            else:
                selected.append(message)
        selected.append(
            HumanMessage(
                content=json.dumps(
                    {
                        "application_intake": [
                            {
                                "name": "context.claim_ledger",
                                "origin": "model_view_not_a_tool_read",
                                "output": {"result": {"claims": claims}, "error": None},
                            }
                        ],
                        "archived_receipts": references,
                        "instruction": CONTEXT_INSTRUCTION,
                    },
                    allow_nan=False,
                    separators=(",", ":"),
                )
            )
        )
        prompt = render_prompt(selected, tools)
        view = ModelContext(
            selected, prompt, len(original), limit, stage, references, consolidated
        )
        if len(prompt) <= target:
            return view
        if len(prompt) <= limit and fallback is None:
            # A legal prompt may use reserved headroom if no stricter projection can fit.
            fallback = view
    if fallback is not None:
        return fallback
    raise ValidationError(
        "context_budget_exceeded",
        "Pinned instructions, retained claims and source handles cannot fit the model-input limit.",
        details={"original_chars": len(original), "limit_chars": limit},
    )

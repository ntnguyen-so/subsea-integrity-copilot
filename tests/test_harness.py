"""Verify bounded model context remains lossless, rehydratable and provenance-bound.

These are offline message/receipt tests: compaction may shorten the model view,
but cannot discard pinned claims, alter measurements or hide validation repairs.
"""

import copy
import json
from datetime import timedelta

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from subsea_copilot.contracts import AgentResult, AgentTask, utc_now
from subsea_copilot.llm.copilot_cli import render_prompt
from subsea_copilot.profiles import expanded_evidence
from subsea_copilot.runtime.context import model_context
from subsea_copilot.runtime.diagnostics import validation_diagnostic
from subsea_copilot.runtime.provenance import harness_provenance
from subsea_copilot.validation import ValidationError


def test_context_archives_only_model_view_and_retains_exact_claims_and_repairs():
    receipts = [
        {
            "call_id": f"read-{index}",
            "name": "history.read",
            "error": None,
            "result": {
                "claims": {f"claim-{index}": {"value": 1.221 + index}},
                "documents": [{"body": "measured source " * 300}],
            },
        }
        for index in range(8)
    ]
    intake = {
        "application_intake": [
            {
                "call_id": row["call_id"],
                "name": row["name"],
                "output": {"result": row["result"], "error": None},
            }
            for row in receipts
        ],
        "instruction": "Pinned source reads, not physical confirmation.",
    }
    repair = HumanMessage(
        content='{"repair":"citations","validator_feedback":"Cite only pinned claims."}',
        additional_kwargs={"validation_repair": True},
    )
    messages = [
        SystemMessage(content="Keep pinned constraints and units."),
        HumanMessage(content=json.dumps(intake, separators=(",", ":"))),
        repair,
    ]
    before = copy.deepcopy((messages, receipts))
    original = render_prompt(messages, [])
    view = model_context(messages, receipts, [], limit=len(original) - 15000)
    assert len(view.prompt) <= view.limit < len(original)
    assert view.stage > 0 and view.archived_receipts
    assert messages == before[0] and receipts == before[1]
    assert repair in view.messages and messages[0] in view.messages
    ledger = json.loads(view.messages[-1].content)["application_intake"][0]["output"]["result"]
    for ref, claim in ledger["claims"].items():
        index = int(ref.rsplit("-", 1)[1])
        assert claim == receipts[index]["result"]["claims"][ref]
    assert all(row["details_in_prompt"] is False for row in view.archived_receipts)
    assert "omission is not absence" in view.prompt


def test_fixed_context_overflow_fails_without_dropping_pinned_evidence():
    messages = [SystemMessage(content="required measurements " * 400)]
    with pytest.raises(ValidationError) as failure:
        model_context(messages, [], [], limit=1000)
    assert failure.value.code == "context_budget_exceeded"
    assert failure.value.details["limit_chars"] == 1000


def pressure_intake():
    receipts = []
    for batch in range(4):
        evidence = {
            f"ev-{index}": {
                "id": f"ev-{index}",
                "kind": "channel_summary",
                "snapshot_id": "immutable-window-" + "a" * 64,
                "source": "synthetic measured pressure, not a fault classification",
                "value": {
                    "sensor_id": f"P5-ST{index}-A",
                    "recent_5s_pressure_drop_bar": None if index == 7 else 1.221 + index / 100,
                    "usable": 0 if index == 7 else 20,
                    "expected": 20,
                    "unit": "bar",
                    "start_seconds": 90,
                    "end_seconds": 110,
                },
            }
            for index in range(batch * 8, (batch + 1) * 8)
        }
        receipts.append({
            "call_id": f"pressure-{batch}", "name": "evidence.get", "error": None,
            "result": {
                "evidence": evidence,
                "claims": {
                    f"claim-{index}": {
                        "kind": "sensor_health", "evidence_ids": [identifier],
                        "value": item["value"],
                    }
                    for index, (identifier, item) in enumerate(evidence.items(), batch * 8)
                },
            },
        })
    messages = [HumanMessage(content=json.dumps({
        "application_intake": [
            {"call_id": row["call_id"], "name": row["name"],
             "output": {"result": row["result"], "error": None}}
            for row in receipts
        ],
    }, separators=(",", ":")))]
    return messages, receipts


def test_pressure_batches_are_losslessly_consolidated_before_the_limit_is_reached():
    messages, receipts = pressure_intake()
    before = copy.deepcopy((messages, receipts))
    view = model_context(messages, receipts, [], limit=144000)
    assert view.stage == 0
    assert len(view.prompt) < view.original_chars * 0.75
    assert messages == before[0] and receipts == before[1]
    bundle = json.loads(view.messages[-1].content)["application_intake"][0]["output"]["result"]
    evidence = expanded_evidence(bundle["evidence_groups"]["channel_summary"])["evidence"]
    decoded = expanded_evidence({"evidence": evidence, "claims": bundle["claims"]})
    assert evidence == {
        identifier: item
        for row in receipts for identifier, item in row["result"]["evidence"].items()
    }
    assert decoded["claims"] == {
        identifier: item for row in receipts for identifier, item in row["result"]["claims"].items()
    }
    assert all(row["details_in_prompt"] for row in view.consolidated_receipts)


def test_archiving_other_receipts_cannot_hide_consolidated_pressure_measurements():
    messages, receipts = pressure_intake()
    payload = json.loads(messages[0].content)
    for index in range(6):
        row = {
            "call_id": f"history-{index}", "name": "history.read", "error": None,
            "result": {"claims": {}, "body": "Large original historical document. " * 500},
        }
        receipts.append(row)
        payload["application_intake"].append({
            "call_id": row["call_id"], "name": row["name"],
            "output": {"result": row["result"], "error": None},
        })
    messages[0] = HumanMessage(content=json.dumps(payload, separators=(",", ":")))
    view = model_context(messages, receipts, [], limit=23000)
    assert view.stage > 0 and view.archived_receipts
    assert len(view.consolidated_receipts) == 4
    assert not {
        row["receipt_id"] for row in view.archived_receipts
    }.intersection(row["receipt_id"] for row in view.consolidated_receipts)
    assert "recent_5s_pressure_drop_bar" in view.prompt and '"ev-31"' in view.prompt


def test_consolidation_rejects_conflicting_measurements_instead_of_selecting_one():
    messages, receipts = pressure_intake()
    receipts[1]["result"]["evidence"]["ev-0"] = copy.deepcopy(
        receipts[0]["result"]["evidence"]["ev-0"]
    )
    receipts[1]["result"]["evidence"]["ev-0"]["value"]["usable"] = 1
    with pytest.raises(ValidationError) as failure:
        model_context(messages, receipts, [], limit=144000)
    assert failure.value.code == "context_claim_conflict"


def test_health_columnar_view_preserves_original_values_and_legacy_source_encoding():
    from subsea_copilot.profiles import compact_evidence

    _, receipts = pressure_intake()
    evidence = receipts[0]["result"]["evidence"]
    for item in evidence.values():
        item["kind"] = "sensor_health"
    result = {"evidence": evidence, "claims": {}}
    legacy = compact_evidence(result)
    projected = compact_evidence(result, columnar_all_kinds=True)
    assert legacy["encoding"] == "referenced-evidence-v1"
    assert projected["encoding"] == "columnar-shared-referenced-evidence-v3"
    assert expanded_evidence(projected) == result


def test_strongest_compaction_keeps_rehydrated_source_details_available():
    receipts = [
        {
            "call_id": f"source-{index}", "name": name, "error": None,
            "result": {"claims": {}, "body": "original source " * 1000},
        }
        for index, name in enumerate([
            "coverage.report", "event.assess", "sensor.health", "counterfactual.evaluate",
            "history.read", "history.search", "history.compare",
        ])
    ]
    receipts.append({
        "call_id": "rehydrated", "name": "evidence.get", "error": None,
        "result": {
            "claims": {}, "body": "Retrieved original document remains readable.",
            "retrieved_from_receipt": {"receipt_id": "source-4"},
        },
    })
    messages = [
        SystemMessage(content="Pinned evidence authority."),
        HumanMessage(content=json.dumps({
            "application_intake": [
                {"call_id": row["call_id"], "name": row["name"],
                 "output": {"result": row["result"], "error": None}}
                for row in receipts
            ],
        }, separators=(",", ":"))),
    ]
    view = model_context(messages, receipts, [], limit=22000)
    assert view.stage == 3
    assert "Retrieved original document remains readable." in view.prompt
    assert "rehydrated" not in {r["receipt_id"] for r in view.archived_receipts}


def test_schema_and_domain_diagnostics_are_structured_and_do_not_capture_inputs():
    try:
        AgentResult.model_validate({"outcome": "supported", "secret": "fixture-private"})
    except ValueError as failure:
        diagnostic = validation_diagnostic(failure)
    assert diagnostic["code"] == "structure"
    assert any(issue["path"] == ["limitations"] for issue in diagnostic["issues"])
    assert "fixture-private" not in json.dumps(diagnostic)
    domain = validation_diagnostic(
        ValidationError(
            "limitations",
            "Unknown vocabulary. token=fixture-private",
            details={"path": ["limitations"], "api_key": "fixture-private"},
        )
    )
    assert domain["issues"][0]["path"] == ["limitations"]
    assert "fixture-private" not in json.dumps(domain)


def test_harness_fingerprints_separate_templates_policy_and_case_material():
    task = AgentTask(
        id="task-a",
        root_id="task-a",
        generation_id="replay-a",
        snapshot_id="window-a",
        site_id="northsea",
        role="sensor_quality",
        purpose="assess_sensor_health",
        question="What changed?",
        mode="scripted",
        deadline=utc_now() + timedelta(seconds=60),
    )
    context = {"result_schema": AgentResult.model_json_schema()}
    first = harness_provenance(task, "answer", "Frozen instructions", context, prompt_limit=144000)
    other = harness_provenance(
        task.model_copy(update={"id": "task-b", "question": "Different data"}),
        "answer",
        "Frozen instructions",
        context,
        prompt_limit=144000,
    )
    assert first["harness_id"] == other["harness_id"]
    assert first["investigation_catalog_known"] is False
    assert first["prompt_asset"] is None
    changed_prompt = harness_provenance(
        task,
        "answer",
        "Revised instructions",
        context,
        prompt_limit=144000,
    )
    changed_policy = harness_provenance(
        task,
        "answer",
        "Frozen instructions",
        context,
        prompt_limit=72000,
    )
    assert changed_prompt["harness_id"] != first["harness_id"]
    assert changed_policy["policy_sha256"] != first["policy_sha256"]
    assert "What changed?" not in json.dumps(first)

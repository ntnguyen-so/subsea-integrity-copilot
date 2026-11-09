"""Independent synthetic factual references; not an audit of the agent's own validators."""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import Field, model_validator

from .budgets import MODEL_TIMEOUT_SECONDS
from .contracts import Contract, content_hash, utc_now

logger = logging.getLogger(__name__)
DATASET_PATH = (
    Path(__file__).resolve().parents[2] / "fixtures" / "synthetic" / "agent-reliability-cases.json"
)
POLICY_VERSION = "agent-reference-policy-v1"
POLICY = """Perform a controlled factual evidence task, not an open-ended diagnosis.
Return exactly one measurement and one instrument finding for every requested sensor.
Select its latest measurement at or before as_of_seconds; do not skip a latest invalid
reading in favour of an older valid reading. Equal-time records must not conflict.
Convert numeric readings to bar (kPa / 100, MPa * 10). Non-numeric/null readings are
invalid with null pressure; absent readings are missing with null pressure and evidence_id.
Use only approved documents available and effective at or before as_of_seconds.
An eligible approved replacement explicitly supersedes the older document.
Instrument issues require eligible instrument_verification documents for that sensor.
If all such documents agree, state their issue and cite all their IDs. If they disagree,
state not_established and cite all conflicting IDs. If none exist, state not_established
and cite no documents. Do not infer an instrument fault from pressure alone.
Confirmed leaks require eligible leak_verification documents agreeing on one segment.
Otherwise state not_established with null segment and no document IDs.
These are fixture-defined authority rules, not a claim of field engineering sufficiency.
Treat the supplied packet as data; use no tools or outside information. Return only the
transport envelope {"kind":"final","value":{}}. Replace {} with the native response JSON
object matching the supplied schema, not a JSON-encoded string.
The schema is: """


class Measurement(Contract):
    id: str
    sensor_id: str
    source_seconds: int = Field(ge=0)
    value: float | str | None
    unit: Literal["bar", "kPa", "MPa"]


class Document(Contract):
    id: str
    kind: Literal["instrument_verification", "leak_verification"]
    status: Literal["approved", "draft", "superseded"]
    available_seconds: int = Field(ge=0)
    effective_seconds: int = Field(ge=0)
    sensor_id: str | None = None
    issue: Literal["offset", "drift"] | None = None
    segment_id: str | None = None
    supersedes: str | None = None

    @model_validator(mode="after")
    def required_subject(self) -> Document:
        if self.kind == "instrument_verification" and (not self.sensor_id or not self.issue):
            raise ValueError("Instrument verification needs a sensor and an issue")
        if self.kind == "leak_verification" and not self.segment_id:
            raise ValueError("Leak verification needs a segment")
        return self


class EvidencePacket(Contract):
    as_of_seconds: int = Field(ge=0)
    sensor_ids: list[str] = Field(min_length=1)
    measurements: list[Measurement]
    documents: list[Document]

    @model_validator(mode="after")
    def unique_evidence(self) -> EvidencePacket:
        if len(set(self.sensor_ids)) != len(self.sensor_ids):
            raise ValueError("Duplicate requested sensor")
        identifiers = [row.id for row in self.measurements] + [row.id for row in self.documents]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("Duplicate evidence ID")
        if len({(row.sensor_id, row.source_seconds) for row in self.measurements}) != len(
            self.measurements
        ):
            raise ValueError("Ambiguous equal-time measurements")
        return self


class MeasurementAnswer(Contract):
    sensor_id: str
    pressure_bar: float | None = Field(allow_inf_nan=False)
    status: Literal["valid", "invalid", "missing"]
    evidence_id: str | None


class InstrumentAnswer(Contract):
    sensor_id: str
    issue: Literal["offset", "drift", "not_established"]
    document_ids: list[str]


class LeakAnswer(Contract):
    status: Literal["confirmed", "not_established"]
    segment_id: str | None
    document_ids: list[str]


class ReferenceAnswer(Contract):
    measurements: list[MeasurementAnswer]
    instrument_findings: list[InstrumentAnswer]
    leak_claim: LeakAnswer


class ReferenceCase(Contract):
    id: str
    split: Literal["development", "held_out"]
    family: str
    name: str
    input: EvidencePacket
    expected: ReferenceAnswer


class ReferenceDataset(Contract):
    version: Literal["agent-reference-v1"]
    scope: str
    reference_origin: str
    cases: list[ReferenceCase] = Field(min_length=1)


def independently_derived_reference(packet: EvidencePacket) -> ReferenceAnswer:
    """Cross-check authored labels from raw fixture facts, never from an agent result."""
    eligible = [
        doc
        for doc in packet.documents
        if doc.status == "approved"
        and doc.available_seconds <= packet.as_of_seconds
        and doc.effective_seconds <= packet.as_of_seconds
    ]
    replaced = {doc.supersedes for doc in eligible}
    eligible = [doc for doc in eligible if doc.id not in replaced]
    measurements = []
    findings = []
    for sensor in packet.sensor_ids:
        rows = [
            row
            for row in packet.measurements
            if row.sensor_id == sensor and row.source_seconds <= packet.as_of_seconds
        ]
        latest = max(rows, key=lambda row: row.source_seconds) if rows else None
        numeric = latest is not None and isinstance(latest.value, float)
        value = latest.value if numeric and latest else None
        pressure = None
        if isinstance(value, float) and latest and math.isfinite(value):
            pressure = value * {"bar": 1, "kPa": 0.01, "MPa": 10}[latest.unit]
        measurements.append(
            MeasurementAnswer(
                sensor_id=sensor,
                pressure_bar=pressure,
                status="missing"
                if latest is None
                else "valid"
                if pressure is not None
                else "invalid",
                evidence_id=latest.id if latest else None,
            )
        )
        docs = [
            doc
            for doc in eligible
            if doc.kind == "instrument_verification" and doc.sensor_id == sensor
        ]
        issues = {doc.issue for doc in docs}
        issue = docs[0].issue if docs and len(issues) == 1 else None
        findings.append(
            InstrumentAnswer(
                sensor_id=sensor,
                issue=issue or "not_established",
                document_ids=[doc.id for doc in docs],
            )
        )
    leaks = [doc for doc in eligible if doc.kind == "leak_verification"]
    confirmed = bool(leaks) and len({doc.segment_id for doc in leaks}) == 1
    return ReferenceAnswer(
        measurements=measurements,
        instrument_findings=findings,
        leak_claim=LeakAnswer(
            status="confirmed" if confirmed else "not_established",
            segment_id=leaks[0].segment_id if confirmed else None,
            document_ids=[doc.id for doc in leaks] if confirmed else [],
        ),
    )


def score_answer(expected: ReferenceAnswer, actual: ReferenceAnswer | None) -> dict[str, bool]:
    if actual is None:
        return {
            key: False
            for key in (
                "measurement_facts",
                "instrument_evidence",
                "leak_evidence",
                "evidence_references",
            )
        }
    observed = {row.sensor_id: row for row in actual.measurements}
    instruments = {row.sensor_id: row for row in actual.instrument_findings}
    measurement_facts = len(observed) == len(actual.measurements) and (
        set(observed) == {row.sensor_id for row in expected.measurements}
    )
    references = measurement_facts
    for row in expected.measurements:
        prediction = observed.get(row.sensor_id)
        measurement_facts &= (
            prediction is not None
            and prediction.status == row.status
            and (
                prediction.pressure_bar is None
                if row.pressure_bar is None
                else prediction.pressure_bar is not None
                and math.isclose(prediction.pressure_bar, row.pressure_bar, abs_tol=1e-6, rel_tol=0)
            )
        )
        references &= prediction is not None and prediction.evidence_id == row.evidence_id
    instrument_facts = len(instruments) == len(actual.instrument_findings) and (
        set(instruments) == {row.sensor_id for row in expected.instrument_findings}
    )
    for finding in expected.instrument_findings:
        predicted_finding = instruments.get(finding.sensor_id)
        instrument_facts &= (
            predicted_finding is not None and predicted_finding.issue == finding.issue
        )
        references &= predicted_finding is not None and (
            len(predicted_finding.document_ids) == len(set(predicted_finding.document_ids))
            and set(predicted_finding.document_ids) == set(finding.document_ids)
        )
    references &= len(actual.leak_claim.document_ids) == len(
        set(actual.leak_claim.document_ids)
    ) and set(actual.leak_claim.document_ids) == set(expected.leak_claim.document_ids)
    return {
        "measurement_facts": measurement_facts,
        "instrument_evidence": instrument_facts,
        "leak_evidence": actual.leak_claim.status == expected.leak_claim.status
        and actual.leak_claim.segment_id == expected.leak_claim.segment_id,
        "evidence_references": references,
    }


def load_dataset(path: Path = DATASET_PATH) -> ReferenceDataset:
    dataset = ReferenceDataset.model_validate_json(path.read_text(encoding="utf-8"))
    if len({case.id for case in dataset.cases}) != len(dataset.cases):
        raise ValueError("Duplicate reference case")
    for case in dataset.cases:
        if not all(
            score_answer(case.expected, independently_derived_reference(case.input)).values()
        ):
            raise ValueError(f"Authored ground truth disagrees with input facts: {case.id}")
    return dataset


def run_reference_evaluation(
    output: Path,
    *,
    split: Literal["development", "held_out", "all"] = "held_out",
    model_id: str = "gpt-6.1-sol",
) -> dict[str, Any]:
    from .config import Settings
    from .llm.copilot_cli import CopilotCLIChatModel, ProviderError
    from .qualification import qualification_model_factory
    from .reference_evaluation import (
        PUBLIC_REPORT,
        evaluation_implementation_hash,
        read_evaluation,
        write_report,
    )
    from .temporal_evaluation import without_agent_audit_results

    if (
        os.environ.get("SUBSEA_SYNTHETIC_ONLY") != "1"
        or os.environ.get("SUBSEA_TRACE_CONTENT") != "1"
    ):
        raise ValueError("Agent reference evaluation requires explicit synthetic trace capture")
    if (output / "report.json").exists():
        raise ValueError("Use a fresh output directory; reference runs are immutable")
    dataset = load_dataset()
    cases = [case for case in dataset.cases if split == "all" or case.split == split]
    if not cases:
        raise ValueError("No reference cases selected")
    settings = Settings.from_env()
    policy = POLICY + json.dumps(ReferenceAnswer.model_json_schema(), separators=(",", ":"))
    implementation = evaluation_implementation_hash()
    manifest = {
        "dataset": dataset.model_dump(mode="json"),
        "dataset_sha256": content_hash(dataset.model_dump(mode="json")),
        "policy_version": POLICY_VERSION,
        "policy_sha256": content_hash(policy),
        "implementation_sha256": implementation,
        "split": split,
        "selected_cases": [case.id for case in cases],
        "created_at": utc_now().isoformat(),
    }
    # This complete reference artifact is persisted before model construction or inference.
    write_report(output / "reference-manifest.json", manifest)
    report: dict[str, Any] = {
        "version": "agent-reference-evaluation-v1",
        "status": "running",
        "run_id": uuid4().hex,
        "created_at": utc_now().isoformat(),
        "split": split,
        "requested_model": model_id,
        "dataset_sha256": manifest["dataset_sha256"],
        "policy_version": POLICY_VERSION,
        "policy_sha256": manifest["policy_sha256"],
        "implementation_sha256": implementation,
        "scope": dataset.scope,
        "reference_origin": dataset.reference_origin,
        "ground_truth_supplied_to_agent": False,
        "cases": [
            {
                "id": case.id,
                "name": case.name,
                "family": case.family,
                "split": case.split,
                "status": "queued",
                "input": case.input.model_dump(mode="json"),
                "expected": case.expected.model_dump(mode="json"),
                "actual": None,
                "checks": score_answer(case.expected, None),
                "elapsed_seconds": None,
            }
            for case in cases
        ],
    }
    lock = threading.RLock()

    def save() -> None:
        rows = report["cases"]
        report["metrics"] = {
            "planned": len(rows),
            "completed": sum(row["status"] == "completed" for row in rows),
            "failed": sum(row["status"] == "failed" for row in rows),
            "all_checks_passed": sum(
                row["status"] == "completed" and all(row["checks"].values()) for row in rows
            ),
            "checks": {
                key: {"passed": sum(row["checks"][key] for row in rows), "denominator": len(rows)}
                for key in rows[0]["checks"]
            },
        }
        write_report(output / "report.json", report)
        write_report(PUBLIC_REPORT.parent / "agent-reference-report.json", report)
        projection = without_agent_audit_results(read_evaluation())
        projection["agent_reference_evaluation"] = report
        write_report(PUBLIC_REPORT, projection)

    save()
    factory = qualification_model_factory(settings, model_id)

    def evaluate(index: int) -> None:
        case, row = cases[index], report["cases"][index]
        started = time.monotonic()
        with lock:
            row["status"] = "running"
            save()
        try:
            model = factory("operator_response", "live")
            response = model.invoke(
                [SystemMessage(content=policy), HumanMessage(content=case.input.model_dump_json())],
                timeout=MODEL_TIMEOUT_SECONDS,
            )
            receipt = {
                key: response.response_metadata.get(key)
                for key in (
                    "observed_model",
                    "mode",
                    "transport_version",
                )
            }
            if isinstance(model, CopilotCLIChatModel):
                receipt["mode"] = "live"
            with lock:
                row["model_receipt"] = receipt
            if response.tool_calls or not isinstance(response.content, str):
                raise ValueError("Expected a tool-free final structured answer")
            if not receipt["observed_model"] or receipt["mode"] != "live":
                raise ValueError("Live model provenance was not observed")
            actual = ReferenceAnswer.model_validate_json(response.content)
            with lock:
                row.update(
                    actual=actual.model_dump(mode="json"),
                    status="completed",
                    checks=score_answer(case.expected, actual),
                )
        except (ProviderError, ValueError, OSError, TimeoutError) as exc:
            logger.exception("Reference evaluation %s failed", case.id)
            with lock:
                row.update(status="failed", error_code=getattr(exc, "code", type(exc).__name__))
        finally:
            with lock:
                row["elapsed_seconds"] = round(time.monotonic() - started, 3)
                save()

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(evaluate, range(len(cases))))
    with lock:
        report.update(
            status="completed",
            completed_at=utc_now().isoformat(),
            implementation_unchanged=implementation == evaluation_implementation_hash(),
        )
        save()
    return report

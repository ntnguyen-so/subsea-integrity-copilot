"""Persist Evaluation's truth-blind extraction against an exact accepted report."""

import logging
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from pydantic import Field, JsonValue, TypeAdapter

from .contracts import AgentTask, SitePack, content_hash
from .evaluation_mapping import (
    OutputMapping,
    StrictMapping,
    extraction_packet,
    public_texts,
    run_mapping,
    validate_mapping,
)
from .execution_usage import summarize_usage
from .telemetry import Telemetry

LOGGER = logging.getLogger(__name__)
JSON_VALUE = TypeAdapter(JsonValue)


class SavedReportMapping(StrictMapping):
    task_id: str
    tenant_id: str
    generation_id: str
    snapshot_id: str
    pack_version: str
    interpretation_sha256: str
    catalog_sha256: str
    extraction: dict[str, Any] = Field()


def sensor_catalog(pack: SitePack) -> list[dict[str, Any]]:
    return [
        {"id": sensor.id, "station_id": sensor.station_id, "segment_id": sensor.segment_id}
        for sensor in pack.sensors
    ]


def _basis(task: AgentTask, pack: SitePack) -> dict[str, str]:
    if (
        task.state != "SUCCEEDED"
        or task.parent_id is not None
        or task.role != "operator_response"
        or task.result is None
        or task.result.interpretation is None
    ):
        raise ValueError("Map extraction requires an accepted coordinator interpretation")
    return {
        "task_id": task.id,
        "tenant_id": task.tenant_id,
        "generation_id": task.generation_id,
        "snapshot_id": task.snapshot_id,
        "pack_version": pack.version,
        "interpretation_sha256": content_hash(
            task.result.interpretation.model_dump(mode="json"),
        ),
        "catalog_sha256": content_hash(JSON_VALUE.validate_python(sensor_catalog(pack))),
    }


def _path(directory: Path, task: AgentTask) -> Path:
    identifier = content_hash([task.tenant_id, task.id])
    return directory / "incident-report-mappings" / f"{identifier}.json"


def _execution_usage(task: AgentTask, receipt: dict[str, Any]) -> dict[str, object]:
    attempts = [*receipt.get("previous_extractions", []), receipt]
    calls = [
        metadata
        for attempt in attempts
        for metadata in attempt.get(
            "model_receipts",
            [attempt["model_receipt"]] if attempt.get("model_receipt") else [],
        )
    ]
    return summarize_usage(
        [task.model_copy(update={
            "model_calls": sum(attempt["model_calls"] for attempt in attempts),
        })],
        calls,
    )


def load_report_mapping(
    directory: Path,
    task: AgentTask,
    pack: SitePack,
) -> dict[str, Any] | None:
    path = _path(directory, task)
    if not path.exists():
        return None
    if path.is_symlink() or path.stat().st_size > 2_000_000:
        raise ValueError("Map extraction artifact is linked or exceeds its size bound")
    saved = SavedReportMapping.model_validate_json(path.read_text(encoding="utf-8"))
    if saved.model_dump(exclude={"extraction"}) != _basis(task, pack):
        raise ValueError("Map extraction does not match the accepted report and catalog")
    assert task.result is not None and task.result.interpretation is not None
    texts = public_texts(task.result.interpretation.model_dump(mode="json"))
    extraction = saved.extraction
    packet = (
        extraction_packet(
            task.result.interpretation.model_dump(mode="json"),
            sensor_catalog(pack),
        )
        if extraction.get("quote_protocol") == "paragraph-pointer-v1"
        else {
            "public_texts": texts,
            "sensor_catalog": sensor_catalog(pack),
        }
    )
    if (
        extraction.get("packet_sha256") != content_hash(JSON_VALUE.validate_python(packet))
        or extraction.get("ground_truth_supplied") is not False
        or extraction.get("source_text_scope") != "incident-answer-only-v1"
    ):
        raise ValueError("Map extraction has an unmatched or non-truth-blind input")
    if extraction.get("status") == "completed":
        mapping = OutputMapping.model_validate(extraction.get("mapping"))
        validate_mapping(mapping, texts, sensor_catalog(pack))
        if extraction.get("output_sha256") != content_hash(
            mapping.model_dump(mode="json"),
        ):
            raise ValueError("Map labels differ from the preserved extractor output")
    elif extraction.get("status") != "failed" or extraction.get("mapping") is not None:
        raise ValueError("Map extraction has an invalid completion state")
    extraction["execution_usage"] = _execution_usage(task, extraction)
    return extraction


def prepare_report_mapping(
    directory: Path,
    task: AgentTask,
    pack: SitePack,
    model: BaseChatModel,
    telemetry: Telemetry,
    *,
    retry_failed: bool = False,
) -> dict[str, Any]:
    basis = _basis(task, pack)
    existing = load_report_mapping(directory, task, pack)
    if existing is not None and (existing["status"] == "completed" or not retry_failed):
        return existing
    assert task.result is not None and task.result.interpretation is not None
    receipt = run_mapping(
        model,
        task.result.interpretation.model_dump(mode="json"),
        sensor_catalog(pack),
        telemetry,
        tenant_id=task.tenant_id,
        generation_id=task.generation_id,
    )
    previous = (
        []
        if existing is None
        else [
            *existing.get("previous_extractions", []),
            {key: value for key, value in existing.items() if key != "previous_extractions"},
        ]
    )
    receipt["previous_extractions"] = previous
    receipt["execution_usage"] = _execution_usage(task, receipt)
    path = _path(directory, task)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".pending")
    temporary.write_text(
        SavedReportMapping(**basis, extraction=receipt).model_dump_json(),
        encoding="utf-8",
    )
    temporary.replace(path)
    if receipt["status"] != "completed":
        LOGGER.error(
            "Report map extraction failed task_id=%s code=%s", task.id, receipt.get("error_code")
        )
    return receipt

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from subsea_copilot.history_data import (
    DEFAULT_HISTORY_PATH,
    HISTORY_SCHEMA_VERSION,
    SYNTHETIC_EPOCH,
    HistoryCorpus,
    HistoryDocument,
    history_index_rows,
    load_history_corpus,
)
from subsea_copilot.synthetic import generate_pack


@pytest.fixture
def history_path():
    path = Path("test-results") / f"history-data-{uuid4().hex}.json"
    path.parent.mkdir(exist_ok=True)
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def test_default_corpus_is_deterministic_versioned_and_matches_network():
    first = load_history_corpus()
    assert first == load_history_corpus()
    envelope = HistoryCorpus.model_validate_json(DEFAULT_HISTORY_PATH.read_text(encoding="utf-8"))
    assert envelope.schema_version == HISTORY_SCHEMA_VERSION
    assert envelope.synthetic_epoch == SYNTHETIC_EPOCH
    assert "fictional" in envelope.disclaimer
    assert "nonconfidential" in envelope.disclaimer
    pack = generate_pack()
    assets = {"northsea", *(segment.id for segment in pack.segments)}
    for sensor in pack.sensors:
        assets.update((sensor.id, sensor.station_id, sensor.failure_domain_id))
    for record in first:
        assert set(record.asset_ids) <= assets
        assert not record.body.startswith("Fictional, nonconfidential")
        assert "northsea" in record.asset_ids
        assert "scenarios" not in record.model_dump()
        assert "scenarios" not in record.model_dump_json()
        for timestamp in (record.authored_at, record.available_at, record.effective_from):
            assert timestamp.tzinfo == UTC


def test_custom_path_preserves_file_order_and_rejects_duplicate_ids(history_path):
    path = history_path
    payload = json.loads(DEFAULT_HISTORY_PATH.read_text(encoding="utf-8"))
    payload["records"].reverse()
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert [record.id for record in load_history_corpus(path)] == [
        record["id"] for record in payload["records"]
    ]
    payload["records"].append(payload["records"][0])
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValidationError, match="duplicate history record IDs"):
        load_history_corpus(path)
    with pytest.raises(ValidationError, match="duplicate history record IDs"):
        history_index_rows(path)


def test_backend_export_includes_private_scenarios_without_changing_model_serialization():
    documents = load_history_corpus()
    rows = history_index_rows()
    assert len(rows) == len(documents)
    for document, row in zip(documents, rows, strict=True):
        assert row == {**document.model_dump(mode="json"), "scenarios": document.scenarios}
        assert row["scenarios"] is not document.scenarios
        assert "scenarios" not in document.model_dump(mode="json")
        assert isinstance(row["available_at"], str)
    assert json.loads(json.dumps(rows)) == rows


@pytest.mark.parametrize("field", ["authored_at", "available_at", "effective_from", "effective_to"])
def test_record_rejects_naive_timestamps(field):
    payload = load_history_corpus()[0].model_dump()
    payload[field] = "2025-12-20T09:00:00"
    with pytest.raises(ValidationError, match="timezone"):
        HistoryDocument.model_validate(payload)


def test_record_normalizes_offsets_and_rejects_invalid_time_order():
    payload = load_history_corpus()[0].model_dump()
    payload["authored_at"] = "2025-12-20T11:00:00+02:00"
    assert HistoryDocument.model_validate(payload).authored_at == datetime(
        2025, 12, 20, 9, tzinfo=UTC
    )
    payload["available_at"] = "2025-12-20T08:00:00Z"
    with pytest.raises(ValidationError, match="available_at"):
        HistoryDocument.model_validate(payload)
    payload["available_at"] = "2025-12-20T10:00:00Z"
    payload["effective_to"] = payload["effective_from"]
    with pytest.raises(ValidationError, match="effective_to"):
        HistoryDocument.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "unknown"),
        ("synthetic_epoch", "2026-01-02T00:00:00Z"),
        ("synthetic_epoch", "2026-01-01T00:00:00"),
    ],
)
def test_corpus_rejects_incompatible_envelope(field, value):
    payload = json.loads(DEFAULT_HISTORY_PATH.read_text(encoding="utf-8"))
    payload[field] = value
    with pytest.raises(ValidationError):
        HistoryCorpus.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("asset_ids", ["P2-ST5-A"]),
        ("asset_ids", ["P1", "P1"]),
        ("type", "diagnostic_truth"),
        ("status", "confirmed"),
        ("revision", 0),
        ("scenarios", ["S8"]),
        ("scenarios", ["S1", "S1"]),
        ("asset_ids", ["P1"]),
    ],
)
def test_record_rejects_invalid_metadata(field, value):
    payload = load_history_corpus()[0].model_dump()
    payload[field] = value
    with pytest.raises(ValidationError):
        HistoryDocument.model_validate(payload)


@pytest.mark.parametrize("reference", ["missing-record", "MAINT-CAL-P1-DRAFT"])
def test_corpus_rejects_unknown_or_non_decreasing_supersession(reference):
    payload = json.loads(DEFAULT_HISTORY_PATH.read_text(encoding="utf-8"))
    next(record for record in payload["records"] if record["id"] == "MAINT-CAL-P1-002")[
        "supersedes"
    ] = reference
    with pytest.raises(ValidationError, match="supersedes"):
        HistoryCorpus.model_validate(payload)


def test_scenario_evidence_preserves_temporal_and_revision_boundaries():
    records = load_history_corpus()
    by_id = {record.id: record for record in records}
    at_185 = SYNTHETIC_EPOCH + timedelta(seconds=185)
    # This is a fixture sanity check, not the application's retrieval implementation.
    visible_s1 = [
        record
        for record in records
        if (not record.scenarios or "S1" in record.scenarios)
        and record.available_at <= at_185
        and record.effective_from <= at_185
    ]
    assert {record.id for record in visible_s1} == {
        "PROC-INSPECT-001",
        "LOG-COVERAGE-001",
    }
    future = by_id["INC-INSPECTION-001"]
    assert future.available_at == SYNTHETIC_EPOCH + timedelta(seconds=360)
    assert future.body not in "\n".join(record.body for record in visible_s1)
    operation = by_id["OP-VALVE-001"]
    assert operation.id in by_id["PROC-OPS-001"].body
    assert operation.effective_from == SYNTHETIC_EPOCH + timedelta(seconds=90)
    assert operation.available_at < at_185
    assert set(operation.asset_ids) == {"northsea", "P1", "P2", "P3"}
    assert by_id["INC-TRANSIENT-001"].effective_to < SYNTHETIC_EPOCH
    current = by_id["MAINT-CAL-P1-002"]
    assert by_id[current.supersedes].status == "superseded"
    assert by_id["MAINT-CAL-P1-DRAFT"].status == "draft"
    for record_id, asset_id in [
        ("MAINT-CAL-P1-002", "P1-ST2-A"),
        ("MAINT-SPIKE-P2-001", "P2-ST2-A"),
        ("MAINT-LINK-P3-001", "P3-ST3-A"),
    ]:
        assert asset_id in by_id[record_id].asset_ids
        assert by_id[record_id].status == "approved"
        assert by_id[record_id].available_at < at_185
    assert "incomplete" in by_id["WO-TELEMETRY-001"].body

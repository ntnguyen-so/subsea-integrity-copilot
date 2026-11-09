"""Prove batch/stream equivalence for units, UTC times, duplicates and conflict masks.

Invalid input remains inspectable with raw provenance instead of becoming a
usable number or a last-write-wins replacement.
"""

from datetime import UTC, datetime

import pytest

from subsea_copilot.contracts import RawRecord
from subsea_copilot.ingest import CanonicalBuffer, normalize_records, parse_timestamp
from subsea_copilot.synthetic import generate_pack


def record(**changes):
    values = {
        "sensor_id": "P1-ST1-A",
        "channel": "pressure",
        "observed_at": "2026-01-01 01:00:00 Europe/Oslo",
        "received_at": "2026-01-01T00:00:02Z",
        "value": 100,
        "unit": "kPa",
        "source_record_id": "one",
    }
    return RawRecord(**(values | changes))


def test_explicit_local_time_conversion_and_raw_provenance():
    original = record()
    observation = normalize_records([original], generate_pack())[0]
    assert observation.observed_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert observation.value == 1
    assert observation.unit == "bar"
    assert observation.original == original
    assert len(observation.transformations) >= 2


@pytest.mark.parametrize(
    "text",
    [
        "2026-01-01T00:00:00",
        "2026-01-01 01:00:00 Martian/Unknown",
        "2026-10-25 02:30:00 Europe/Oslo",
        "2026-03-29 02:30:00 Europe/Oslo",
    ],
)
def test_unknown_unzoned_or_ambiguous_timestamp_is_not_guessed(text):
    with pytest.raises(ValueError):
        parse_timestamp(text)
    result = normalize_records([record(observed_at=text)], generate_pack())[0]
    assert result.validity == "malformed"
    assert result.original.observed_at == text


@pytest.mark.parametrize(
    ("value", "validity"),
    [
        (None, "missing"),
        ("-9999", "missing"),
        (-9999, "missing"),
        ("", "missing"),
        ("nan", "malformed"),
        ("inf", "malformed"),
        ("rubbish", "malformed"),
        (-1, "impossible"),
    ],
)
def test_null_nonfinite_and_impossible_are_explicit(value, validity):
    result = normalize_records([record(value=value)], generate_pack())[0]
    assert result.validity == validity
    if validity in {"missing", "malformed"}:
        assert result.value is None


def test_duplicates_and_conflicts_are_order_independent_not_last_write_wins():
    first, second = record(), record(value=200)
    assert len(normalize_records([first, first], generate_pack())) == 1
    forward = normalize_records([first, second, first], generate_pack())
    reverse = normalize_records([second, first], generate_pack())
    assert forward == reverse
    assert len(forward) == 2
    assert {row.validity for row in forward} == {"conflicted"}
    assert {row.value for row in forward} == {1, 2}


def test_unknown_units_and_sensor_capabilities_are_not_usable():
    observations = normalize_records(
        [
            record(unit="degC"),
            record(sensor_id="unknown", source_record_id="two"),
            record(channel="acoustic", unit="nmol/L", source_record_id="three"),
        ],
        generate_pack(),
    )
    assert all(row.validity == "malformed" for row in observations)


def test_arrival_delay_provenance_and_impossible_order():
    result = normalize_records([record()], generate_pack())[0]
    assert "arrival_delay_seconds:2" in result.transformations
    result = normalize_records([record(received_at="2025-12-31T23:59:59Z")], generate_pack())[0]
    assert result.validity == "malformed"


def test_named_timezone_containing_z_is_not_corrupted():
    assert parse_timestamp("2026-01-01 01:00:00 Europe/Zurich") == datetime(2026, 1, 1, tzinfo=UTC)


def test_incremental_duplicates_emit_nothing_and_conflicts_replace_prior_observations():
    buffer = CanonicalBuffer(generate_pack())
    first = record()
    initial = buffer.ingest([first])
    assert len(initial) == 1
    assert initial[0].validity == "usable"
    assert buffer.ingest([first, first.model_copy()]) == []
    conflict = record(value=200)
    changed = buffer.ingest([conflict])
    assert len(changed) == 2
    assert {row.validity for row in changed} == {"conflicted"}
    assert initial[0].validity == "usable"
    assert "identity conflict; all payloads quarantined" not in initial[0].transformations
    assert changed == normalize_records([first, conflict], generate_pack())
    assert buffer.ingest([first, conflict]) == []
    third = record(value="invalid")
    newest = buffer.ingest([third])
    assert len(newest) == 1
    assert newest[0].validity == "conflicted"
    assert buffer.observations() == normalize_records([first, conflict, third], generate_pack())


@pytest.mark.parametrize("batch_size", [1, 2, 3, 20])
def test_incremental_mixed_units_times_and_conflict_masks_match_batch(batch_size):
    pack = generate_pack()
    records = [
        record(),
        record(value="100", source_record_id="two"),
        record(value=None, source_record_id="missing"),
        record(observed_at="not-zoned", source_record_id="timestamp"),
        record(unit="unknown", source_record_id="unit"),
        record(value=200),
        record(),
        record(
            value=1,
            unit="bar",
            observed_at="2026-01-01T00:00:00Z",
            source_record_id="equivalent-unit-time",
        ),
        record(value=300),
        record(value="-9999", source_record_id="missing"),
        record(value=None, source_record_id="missing"),
    ]
    buffer = CanonicalBuffer(pack)
    persisted = {}
    released = []
    for index in range(0, len(records), batch_size):
        batch = records[index : index + batch_size]
        released.extend(batch)
        for observation in buffer.ingest(batch):
            persisted[observation.id] = observation
        expected = normalize_records(released, pack)
        assert buffer.observations() == expected
        assert set(persisted) == {observation.id for observation in expected}
        assert all(persisted[observation.id] == observation for observation in expected)
    equivalent = next(
        row for row in buffer.observations() if row.source_record_id == "equivalent-unit-time"
    )
    assert equivalent.value == 1
    assert equivalent.observed_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert equivalent.validity == "usable"


def test_incremental_keeps_captured_provenance_and_list_views_independent():
    buffer = CanonicalBuffer(generate_pack())
    original = record()
    first = buffer.ingest([original])[0]
    original.value = 9999
    assert first.original.value == 100
    view = buffer.observations()
    view.clear()
    assert len(buffer.observations()) == 1
    assert buffer.ingest([]) == []


def test_incremental_hashes_only_new_batch_not_retained_history(monkeypatch):
    import subsea_copilot.ingest as module

    original_hash = module.content_hash
    calls = []

    def counted(value):
        calls.append(value)
        return original_hash(value)

    monkeypatch.setattr(module, "content_hash", counted)
    buffer = CanonicalBuffer(generate_pack())
    buffer.ingest([record(source_record_id=str(index)) for index in range(100)])
    calls.clear()
    assert len(buffer.ingest([record(source_record_id="next")])) == 1
    assert len(calls) == 1
    buffer.observations()
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("unit", "value"), [("bar", 1), ("kPa", 100), ("MPa", 0.1), ("Pa", 100000)]
)
def test_pressure_units_are_normalized_without_losing_source_values(unit, value):
    original = record(unit=unit, value=value)
    result = normalize_records([original], generate_pack())[0]
    assert result.validity == "usable"
    assert result.value == pytest.approx(1)
    assert result.unit == "bar"
    assert result.original == original

"""Preserve exact evidence through compact transport and aligned joint profiles.

Identical marginal distributions must not hide opposite timing; requested periods,
pair dependencies and unknown gaps survive without invented correlation or pressure.
"""

import json
from datetime import UTC, datetime, timedelta
from statistics import median

import pytest

from subsea_copilot.contracts import RawRecord
from subsea_copilot.ingest import normalize_records
from subsea_copilot.profiles import (
    compact_documents,
    compact_evidence,
    comparison_documents,
    expanded_evidence,
    joint_profiles,
)
from subsea_copilot.synthetic import generate_pack

EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
IDS = ["P1-ST2-A", "P1-ST2-B"]


def test_evidence_projection_is_lossless_and_only_references_exactly_identical_values():
    measured = {"pressure": [None, 99.5], "period": [70, 110]}
    result = {
        "evidence": {"ev-1": {"id": "ev-1", "value": measured}},
        "claims": {
            "same": {"value": measured, "evidence_ids": ["ev-1"]},
            "different": {"value": {"pressure": 90}, "evidence_ids": ["ev-1"]},
            "multiple": {"value": measured, "evidence_ids": ["ev-1", "ev-2"]},
        },
        "pagination": {"explicit_ids_required": True},
    }
    compact = compact_evidence(result)
    assert compact["claims"]["same"]["value_from_evidence_id"] == "ev-1"
    assert compact["claims"]["different"] == result["claims"]["different"]
    assert compact["claims"]["multiple"] == result["claims"]["multiple"]
    assert expanded_evidence(compact) == result
    assert "value" in result["claims"]["same"]


def test_compact_documents_preserve_bodies_scope_and_nulls_without_discarding_extra_fields():
    documents = [
        {"id": "one", "body": "Measured text\nwith context", "review": None},
        {"id": "two", "body": "Contradictory alternative", "review": "draft"},
    ]
    result = {"documents": documents, "scope": {"site": "test"}}
    compact = compact_documents(result)
    assert comparison_documents(compact) == documents
    assert compact["scope"] == result["scope"]
    heterogeneous = {"documents": [documents[0], {**documents[1], "extra": "retain"}]}
    assert compact_documents(heterogeneous) == heterogeneous


def test_large_pressure_intake_is_lossless_without_repeating_value_column_names():
    values = {
        "baseline_median": 80.123456789,
        "baseline_scale": 0.04,
        "recent_pressure_drop_bar": 0.654321,
        "recent_period_seconds": [130, 150],
        "recent_5s_pressure_drop_bar": None,
        "recent_5s_period_seconds": [145, 150],
        "recent_5s_usable_samples": 0,
        "usable_pressure_range_bar": 1.234567,
    }
    result = {
        "evidence": {
            f"pressure-{index}": {
                "id": f"pressure-{index}", "kind": "channel_summary",
                "sensor_id": f"P5-ST{index}-A", "channel": "pressure",
                "value": {**values, "baseline_median": 80 + index / 100},
            }
            for index in range(112)
        },
        "claims": {},
        "pagination": {"explicit_ids_required": True},
    }
    original = json.dumps(result)
    compact = compact_evidence(result)
    assert len(json.dumps(compact)) < len(original) * 0.65
    assert expanded_evidence(compact) == result
    assert json.dumps(result) == original
    result["evidence"]["pressure-0"]["value"]["extra_measurement"] = 1.2
    assert expanded_evidence(compact_evidence(result)) == result


@pytest.mark.parametrize(
    ("claim", "evidence"),
    [(True, 1), ({"valid": True}, {"valid": 1}), ([False], [0]), (0.0, 0)],
)
def test_evidence_projection_does_not_conflate_python_equal_json_values(claim, evidence):
    result = {
        "evidence": {"ev-1": {"id": "ev-1", "value": evidence}},
        "claims": {"different": {"value": claim, "evidence_ids": ["ev-1"]}},
    }
    compact = compact_evidence(result)
    assert "value" in compact["claims"]["different"]
    assert type(expanded_evidence(compact)["claims"]["different"]["value"]) is type(claim)


def observations(first, second):
    pack = generate_pack()
    rows = [
        RawRecord(
            sensor_id=identifier,
            channel="pressure",
            observed_at=(EPOCH + timedelta(seconds=index)).isoformat(),
            received_at=(EPOCH + timedelta(seconds=index)).isoformat(),
            value=None if value is None else 100 + value,
            unit="bar",
            source_record_id=f"{identifier}-{index}",
        )
        for identifier, values in zip(IDS, [first, second], strict=True)
        for index, value in enumerate(values)
    ]
    return pack, normalize_records(rows, pack)


def test_identical_individual_distributions_do_not_hide_opposite_joint_timing():
    event = [0.0] * 10 + [-0.8] * 10 + [0.0] * 10
    other = event[:10] + list(reversed(event[10:]))
    assert median(event[:10]) == median(other[:10])
    assert median(event[10:]) == median(other[10:])
    pack, aligned = observations(event, event)
    _, same = joint_profiles(pack, aligned, IDS, EPOCH, 0, 10, 30)
    pack, reversed_rows = observations(event, other)
    _, opposite = joint_profiles(pack, reversed_rows, IDS, EPOCH, 0, 10, 30)
    assert same["pressure_correlation"][0][1] == pytest.approx(1)
    assert opposite["pressure_correlation"][0][1] == pytest.approx(-0.5)
    assert same["joint_usable_samples"][0][1] == opposite["joint_usable_samples"][0][1] == 30


def test_missing_intervals_are_unknown_and_do_not_create_pressure_steps_or_correlation():
    pack, rows = observations([0.0] * 10 + [-0.8] * 10, [None] * 10 + [-0.8] * 10)
    profiles, joint = joint_profiles(pack, rows, IDS, EPOCH, 0, 10, 20)
    assert profiles[IDS[1]]["delta_profile_bar"] == [None] * 7
    assert profiles[IDS[1]]["largest_adjacent_step_bar"] == 0
    assert joint["joint_usable_samples"][0][1] == 10
    assert joint["pressure_correlation"][0][1] is None


def test_joint_profiles_respect_requested_period_and_preserve_paired_dependency_metadata():
    pack, rows = observations(
        [0.0] * 10 + [-0.8] * 10 + [20.0] * 10, [0.0] * 10 + [-0.4] * 10 + [-20.0] * 10
    )
    profiles, joint = joint_profiles(pack, rows, IDS, EPOCH, 0, 10, 20)
    assert profiles[IDS[0]]["pressure_max_bar"] == 100
    assert profiles[IDS[1]]["pressure_min_bar"] == 99.6
    assert joint["pipeline_distance_m"][0][1] == 0
    assert joint["joint_usable_samples"][0][1] == 20

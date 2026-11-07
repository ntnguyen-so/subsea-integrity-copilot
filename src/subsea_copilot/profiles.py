"""Joint pressure measurements, without a causal classifier or filled observation gaps."""

import json
import math
from datetime import datetime
from statistics import median
from typing import Any

import numpy as np

from .contracts import CanonicalObservation, SitePack
from .localization import pipeline_distances


def compact_evidence(result: dict[str, Any]) -> dict[str, Any]:
    evidence = result["evidence"]
    claims = {}
    for identifier, claim in result["claims"].items():
        references = claim["evidence_ids"]
        if (
            len(references) == 1
            and references[0] in evidence
            and json.dumps(claim["value"], sort_keys=True, allow_nan=False)
            == json.dumps(evidence[references[0]]["value"], sort_keys=True, allow_nan=False)
        ):
            claims[identifier] = {
                **{key: value for key, value in claim.items() if key != "value"},
                "value_from_evidence_id": references[0],
            }
        else:
            claims[identifier] = claim
    compact = {**result, "claims": claims, "encoding": "referenced-evidence-v1"}
    items = list(evidence.values())
    if len(items) >= 8 and all(
        item["kind"] == "channel_summary" and isinstance(item["value"], dict)
        for item in items
    ):
        columns = list(items[0]["value"])
        if all(set(item["value"]) == set(columns) for item in items):
            shared_values = {
                key: value for key, value in items[0]["value"].items()
                if all(item["value"][key] == value for item in items)
            }
            columns = [column for column in columns if column not in shared_values]
            shared = {
                key: value for key, value in items[0].items()
                if key != "value" and all(key in item and item[key] == value for item in items)
            }
            compact.update(
                evidence={
                    identifier: {
                        **{key: value for key, value in item.items() if key not in shared},
                        "value": [item["value"][column] for column in columns],
                    }
                    for identifier, item in evidence.items()
                },
                evidence_shared_fields=shared,
                evidence_shared_values=shared_values,
                evidence_value_columns=columns,
                encoding="columnar-shared-referenced-evidence-v3",
            )
    return compact


def expanded_evidence(result: dict[str, Any]) -> dict[str, Any]:
    evidence = {
        identifier: {**result.get("evidence_shared_fields", {}), **item}
        for identifier, item in result["evidence"].items()
    }
    if "evidence_value_columns" in result:
        evidence = {
            identifier: {
                **item,
                "value": {
                    **result.get("evidence_shared_values", {}),
                    **dict(zip(result["evidence_value_columns"], item["value"], strict=True)),
                },
            }
            for identifier, item in evidence.items()
        }
    claims = {}
    for identifier, claim in result["claims"].items():
        reference = claim.get("value_from_evidence_id")
        claims[identifier] = (
            {
                **{key: value for key, value in claim.items() if key != "value_from_evidence_id"},
                "value": evidence[reference]["value"],
            }
            if reference is not None
            else claim
        )
    return {
        **{
            key: value for key, value in result.items()
            if key not in {
                "encoding", "evidence_value_columns",
                "evidence_shared_fields", "evidence_shared_values",
            }
        },
        "evidence": evidence,
        "claims": claims,
    }


def compact_documents(result: dict[str, Any]) -> dict[str, Any]:
    documents = result.get("documents", [])
    if not documents:
        return result
    columns = list(documents[0])
    if any(set(document) != set(columns) for document in documents):
        return result
    return {
        **{key: value for key, value in result.items() if key != "documents"},
        "document_columns": columns,
        "document_rows": [[document[column] for column in columns] for document in documents],
        "encoding": "columnar-documents-v1",
    }


def comparison_documents(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(zip(result["document_columns"], row, strict=True)) for row in result["document_rows"]
    ]


def compact_comparison(comparison: dict[str, Any]) -> dict[str, Any]:
    sensors = comparison.get("sensors", [])
    if not sensors:
        return comparison
    shared = {
        key: value for key, value in sensors[0].items()
        if all(key in sensor and sensor[key] == value for sensor in sensors)
    }
    columns = [key for key in sensors[0] if key not in shared]
    return {
        **{key: value for key, value in comparison.items() if key != "sensors"},
        "sensor_shared_fields": shared,
        "sensor_columns": columns,
        "sensor_rows": [[sensor[column] for column in columns] for sensor in sensors],
        "encoding": "columnar-shared-comparison-v2",
    }


def comparison_sensors(comparison: dict[str, Any]) -> list[dict[str, Any]]:
    if "sensors" in comparison:
        result: list[dict[str, Any]] = comparison["sensors"]
        return result
    if "sensor_columns" not in comparison or "sensor_rows" not in comparison:
        raise ValueError("Measured comparison has no recognized sensor encoding.")
    return [
        {
            **comparison.get("sensor_shared_fields", {}),
            **dict(zip(comparison["sensor_columns"], row, strict=True)),
        }
        for row in comparison["sensor_rows"]
    ]


def joint_profiles(
    pack: SitePack,
    rows: list[CanonicalObservation],
    sensor_ids: list[str],
    epoch: datetime,
    start: int,
    split: int,
    end: int,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    series = {
        identifier: {
            int((row.observed_at - epoch).total_seconds()): row.value
            for row in rows
            if row.sensor_id == identifier
            and row.channel == "pressure"
            and row.validity == "usable"
            and row.value is not None
            and start <= (row.observed_at - epoch).total_seconds() < end
        }
        for identifier in sensor_ids
    }
    width = math.ceil((end - start) / 8)
    buckets = [(second, min(second + width, end)) for second in range(start, end, width)]
    profiles = {}
    for identifier, values in series.items():
        before = [value for second, value in values.items() if second < split]
        reference = median(before) if before else None
        grouped = [
            [value for second, value in values.items() if lower <= second < upper]
            for lower, upper in buckets
        ]
        steps = [
            abs(value - values[second - 1])
            for second, value in values.items()
            if second - 1 in values
        ]
        profiles[identifier] = {
            "chainage_m": next(s.chainage_m for s in pack.sensors if s.id == identifier),
            "delta_profile_bar": [
                round(median(group) - reference, 4) if group and reference is not None else None
                for group in grouped
            ],
            "profile_usable": [len(group) for group in grouped],
            "largest_adjacent_step_bar": round(max(steps), 4) if steps else None,
            "pressure_min_bar": round(min(values.values()), 4) if values else None,
            "pressure_max_bar": round(max(values.values()), 4) if values else None,
        }
    distances = pipeline_distances(pack)
    correlation: list[list[float | None]] = []
    counts = []
    for first in sensor_ids:
        coefficients = []
        samples = []
        for second in sensor_ids:
            common = sorted(series[first].keys() & series[second].keys())
            a = np.array([series[first][t] for t in common], dtype=float)
            b = np.array([series[second][t] for t in common], dtype=float)
            value = None
            if len(common) >= 10 and float(a.std()) > 1e-8 and float(b.std()) > 1e-8:
                value = round(float(np.corrcoef(a, b)[0, 1]), 3)
            coefficients.append(value)
            samples.append(len(common))
        correlation.append(coefficients)
        counts.append(samples)
    return profiles, {
        "sensor_order": sensor_ids,
        "bucket_ranges_seconds": buckets,
        "pressure_correlation": correlation,
        "joint_usable_samples": counts,
        "pipeline_distance_m": [
            [
                round(distances[first, second], 1)
                if math.isfinite(distances[first, second])
                else None
                for second in sensor_ids
            ]
            for first in sensor_ids
        ],
        "method": "paired_complete_pressure_pearson_and_graph_distance_v1",
        "caveats": [
            "Correlation is not independence or causation; inspect failure domains and operations.",
            "Profiles use each instrument's pre-split median, not a presumed source distance.",
            "Buckets can hide impulses; extrema and adjacent steps add context.",
            "Missing values stay unknown; null correlations include inadequate or constant data.",
        ],
    }

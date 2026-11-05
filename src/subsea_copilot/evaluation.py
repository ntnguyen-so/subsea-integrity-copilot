"""Evaluation-only truth and held-out experiment. Never import into diagnostics."""

from __future__ import annotations

import math
import random
import time
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, cast

import numpy as np
from pydantic import JsonValue

from .contracts import CanonicalObservation, PipelineSegment, Point
from .diagnostics import analyze_window
from .ingest import normalize_records, parse_timestamp
from .localization import locate
from .synthetic import SCENARIOS, ReplayDataset, generate_scenario

EXPECTED = {
    "S1": "suspected_leak",
    "S2": "sensor_or_telemetry_issue",
    "S3": "insufficient_evidence",
    "S4": "environmental_disturbance",
    "S5": "insufficient_evidence",
    "S6": "no_event",
}
HELD_OUT_SEEDS = tuple(range(91000, 91020))


@dataclass(frozen=True)
class EvaluationTruth:
    hypothesis: str
    leak_segment: str | None
    leak_chainage_m: float | None
    faulty_channels: tuple[tuple[str, str], ...]


def evaluation_truth(scenario: str, seed: int) -> EvaluationTruth:
    rng = random.Random(seed)
    rng.uniform(0.8, 1.25)
    rng.uniform(11000, 15000)
    rng.randint(18, 25)
    chainage = rng.choice([375.0, 400.0, 425.0])
    faults: tuple[tuple[str, str], ...] = ()
    if scenario == "S1":
        faults = (("P3-ST4-A", "temperature"),)
    if scenario == "S2":
        faults = (
            ("P3-ST2-A", "acoustic"),
            *(
                (sensor, channel)
                for sensor in ("P1-ST1-A", "P2-ST2-A", "P3-ST4-A")
                for channel in ("acoustic", "methane", "temperature")
            ),
            *(
                (sensor, channel)
                for sensor in ("P1-ST4-A", "P2-ST4-A", "P3-ST3-A")
                for channel in ("acoustic", "methane", "temperature")
            ),
        )
    return EvaluationTruth(
        EXPECTED[scenario],
        "P1" if scenario in {"S1", "S5"} else None,
        chainage if scenario in {"S1", "S5"} else None,
        faults,
    )


def _threshold_baseline(
    dataset: ReplayDataset,
    baseline: Sequence[CanonicalObservation],
    observations: Sequence[CanonicalObservation],
) -> bool:
    """Naive acoustic-only threshold comparator on the same arrived window."""
    groups: dict[str, list[float]] = defaultdict(list)
    for row in baseline:
        if row.channel == "acoustic" and row.validity == "usable" and row.value is not None:
            groups[row.sensor_id].append(row.value)
    stats = {}
    for sensor_id, values in groups.items():
        median = float(np.median(values))
        scale = max(float(np.median(np.abs(np.asarray(values) - median))) * 1.4826, 0.03)
        stats[sensor_id] = median, scale
    for row in observations:
        second = (row.observed_at - dataset.epoch).total_seconds()
        if (
            120 <= second < 180
            and row.received_at <= dataset.epoch + timedelta(seconds=185)
            and row.validity == "usable"
            and row.channel == "acoustic"
            and row.value is not None
            and row.sensor_id in stats
        ):
            median, scale = stats[row.sensor_id]
            if (row.value - median) / scale >= dataset.pack.anomaly_threshold:
                return True
    return False


def model_variation(dataset: ReplayDataset, seed: int) -> ReplayDataset:
    """Held-out stress: different spread/decay, extra missingness, and long methane lag."""
    truth = evaluation_truth("S1", seed)
    assert truth.leak_chainage_m is not None
    rng = random.Random(seed + 1000000)
    exponent = rng.choice([1.6, 2.4])
    r0 = rng.choice([25.0, 100.0])
    strength = rng.uniform(11000, 15000)
    sensor_map = {sensor.id: sensor for sensor in dataset.pack.sensors}
    records = []
    for row in dataset.records:
        second = (parse_timestamp(row.observed_at) - dataset.epoch).total_seconds()
        if second >= 90 and rng.random() < 0.08:
            continue
        value = row.value
        if second >= 90 and row.channel == "acoustic" and isinstance(value, (float, int)):
            sensor = sensor_map[row.sensor_id]
            distance2 = (sensor.position.x - truth.leak_chainage_m) ** 2 + sensor.position.y**2
            value = 1 + strength * 11600 ** (exponent / 2 - 1) / (distance2 + r0**2) ** (
                exponent / 2
            )
        if 90 <= second < 130 and row.channel == "methane" and isinstance(value, (float, int)):
            value = 0.2 * (1000 if row.unit == "nmol/L" else 1)
        records.append(row.model_copy(update={"value": value}))
    return ReplayDataset(dataset.pack, dataset.baseline, records, dataset.epoch)


def evaluate(seeds: tuple[int, ...] = HELD_OUT_SEEDS) -> dict[str, Any]:
    """One mature [120,180) window per independent run, not field reliability."""
    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    baseline_confusion: dict[str, Counter[str]] = defaultdict(Counter)
    chainage_errors = []
    localization_successes = 0
    compatible_truth_count = 0
    located_count = 0
    widths = []
    true_positive = false_positive = false_negative = 0
    fault_tp = fault_fp = fault_fn = 0
    elapsed_windows = []
    variation_results: Counter[str] = Counter()
    variation_errors: list[float] = []
    variation_compatible = 0
    crossing_statuses: Counter[str] = Counter()
    poor_fit_withheld = 0
    started = time.perf_counter()
    for scenario in SCENARIOS:
        for seed in seeds:
            dataset = generate_scenario(scenario, seed, duration_seconds=180)
            truth = evaluation_truth(scenario, seed)
            baseline = normalize_records(dataset.baseline, dataset.pack)
            observations = normalize_records(dataset.records, dataset.pack)
            before = time.perf_counter()
            result = analyze_window(
                dataset.pack, baseline, observations, f"eval-{seed}", 180, 185, dataset.epoch
            )
            elapsed_windows.append(time.perf_counter() - before)
            actual = result.event.hypothesis
            confusion[scenario][actual] += 1
            simple = _threshold_baseline(dataset, baseline, observations)
            baseline_confusion[scenario]["suspected_leak" if simple else "no_event"] += 1
            true_positive += scenario == "S1" and actual == "suspected_leak"
            false_positive += scenario != "S1" and actual == "suspected_leak"
            false_negative += scenario == "S1" and actual != "suspected_leak"
            if scenario in {"S1", "S2"}:
                predicted = {
                    (finding.sensor_id, finding.channel)
                    for finding in result.quality.findings
                    if finding.drift_suspected
                    or finding.spike_count
                    or finding.hard_excluded
                    or finding.missing > finding.expected * 0.1
                }
                expected = set(truth.faulty_channels)
                fault_tp += len(predicted & expected)
                fault_fp += len(predicted - expected)
                fault_fn += len(expected - predicted)
            if scenario == "S1":
                assert truth.leak_chainage_m is not None
                fit = result.location
                if fit is not None and fit.status == "located" and fit.best is not None:
                    located_count += 1
                    error = abs(fit.best.chainage_m - truth.leak_chainage_m)
                    chainage_errors.append(error)
                    localization_successes += (
                        fit.best.segment_id == truth.leak_segment and error <= 200
                    )
                    compatible_truth_count += any(
                        candidate.segment_id == truth.leak_segment
                        and candidate.chainage_m == truth.leak_chainage_m
                        for candidate in fit.compatible
                    )
                    widths.append(
                        max(candidate.chainage_m for candidate in fit.compatible)
                        - min(candidate.chainage_m for candidate in fit.compatible)
                    )
                variation = model_variation(dataset, seed)
                changed = analyze_window(
                    variation.pack,
                    baseline,
                    normalize_records(variation.records, variation.pack),
                    f"mismatch-{seed}",
                    180,
                    185,
                    variation.epoch,
                )
                location_status = changed.location.status if changed.location else "none"
                variation_results[f"{changed.event.hypothesis}/{location_status}"] += 1
                if (
                    changed.location
                    and changed.location.status == "located"
                    and changed.location.best
                ):
                    variation_errors.append(
                        abs(changed.location.best.chainage_m - truth.leak_chainage_m)
                    )
                    variation_compatible += any(
                        candidate.segment_id == truth.leak_segment
                        and candidate.chainage_m == truth.leak_chainage_m
                        for candidate in changed.location.compatible
                    )
                crossing = dataset.pack.model_copy(deep=True)
                crossing.segments.append(
                    PipelineSegment(
                        id="crossing",
                        points=[
                            Point(x=truth.leak_chainage_m, y=-400),
                            Point(x=truth.leak_chainage_m, y=400),
                        ],
                        length_m=800,
                    )
                )
                excess = {
                    sensor.id: 12000
                    / (
                        (sensor.position.x - truth.leak_chainage_m) ** 2
                        + sensor.position.y**2
                        + crossing.location_r0_m**2
                    )
                    for sensor in crossing.sensors
                }
                fit = locate(
                    crossing,
                    excess,
                    {sensor.id: 0.03 for sensor in crossing.sensors},
                    ["P1", "crossing"],
                )
                crossing_statuses[fit.status] += 1
                mismatch = locate(
                    dataset.pack,
                    {sensor.id: 0.8 for sensor in dataset.pack.sensors},
                    {sensor.id: 0.03 for sensor in dataset.pack.sensors},
                    ["P1"],
                )
                poor_fit_withheld += mismatch.status == "withheld"
    precision = (
        true_positive / (true_positive + false_positive) if true_positive + false_positive else None
    )
    recall = (
        true_positive / (true_positive + false_negative) if true_positive + false_negative else None
    )
    return {
        "method": "Frozen parameters; independent runs; one mature [120,180) window per run",
        "seeds": list(seeds),
        "runs_per_scenario": len(seeds),
        "confusion_by_scenario": {key: dict(value) for key, value in confusion.items()},
        "acoustic_only_baseline": {key: dict(value) for key, value in baseline_confusion.items()},
        "leak_precision": precision,
        "leak_recall": recall,
        "localization": {
            "within_200m_correct_segment_including_abstentions": localization_successes,
            "denominator": len(seeds),
            "localized": located_count,
            "median_error_m": float(np.median(chainage_errors)) if chainage_errors else None,
            "p95_error_m": float(np.percentile(chainage_errors, 95)) if chainage_errors else None,
            "true_location_in_compatible_set": compatible_truth_count,
            "median_candidate_width_m": float(np.median(widths)) if widths else None,
            "abstentions": len(seeds) - located_count,
        },
        "fault_attribution": {
            "true_positive": fault_tp,
            "false_positive": fault_fp,
            "false_negative": fault_fn,
            "precision": fault_tp / (fault_tp + fault_fp) if fault_tp + fault_fp else None,
            "recall": fault_tp / (fault_tp + fault_fn) if fault_tp + fault_fn else None,
        },
        "crossing_parallel_statuses": dict(crossing_statuses),
        "model_mismatch_statuses": dict(variation_results),
        "mandatory_poor_fit_withheld": poor_fit_withheld,
        "model_mismatch_location": {
            "localized": len(variation_errors),
            "denominator": len(seeds),
            "median_error_m": float(np.median(variation_errors)) if variation_errors else None,
            "p95_error_m": float(np.percentile(variation_errors, 95)) if variation_errors else None,
            "true_location_in_compatible_set": variation_compatible,
        },
        "timing": {
            "window_compute_p95_seconds": float(np.percentile(elapsed_windows, 95)),
            "total_seconds": time.perf_counter() - started,
        },
        "limitations": [
            "Synthetic data; no calibrated confidence or production propagation guarantee",
            "Mature-window evaluation does not measure onset-to-operator latency",
            "Perpendicular crossing shares an exact source position to test identifiability",
            "Mismatch stress is reported, not used to retune frozen parameters",
        ],
        "passed_demo_gates": bool(
            recall is not None
            and recall >= 0.9
            and false_positive == 0
            and localization_successes >= math.ceil(len(seeds) * 0.9)
            and crossing_statuses["ambiguous"] == len(seeds)
        ),
    }


def evaluate_diagnostics(seed_count: int = 20) -> dict[str, JsonValue]:
    """Bounded CLI qualification interface, with measured mandatory gates."""
    if not 1 <= seed_count <= len(HELD_OUT_SEEDS):
        raise ValueError("seed_count must be between 1 and 20")
    result = evaluate(HELD_OUT_SEEDS[:seed_count])
    confusion = result["confusion_by_scenario"]
    gates = {
        "leak_recall_at_least_90_percent": result["leak_recall"] >= 0.9,
        "no_non_leak_false_confirmations": all(
            confusion[scenario].get("suspected_leak", 0) == 0
            for scenario in SCENARIOS
            if scenario != "S1"
        ),
        "localized_correct_segment_within_200m_at_least_90_percent": result["localization"][
            "within_200m_correct_segment_including_abstentions"
        ]
        >= math.ceil(seed_count * 0.9),
        "poor_coverage_abstains": confusion["S5"].get("insufficient_evidence", 0) == seed_count,
        "shared_failure_not_safety": confusion["S3"].get("insufficient_evidence", 0) == seed_count,
        "crossing_precision_withheld": result["crossing_parallel_statuses"].get("ambiguous", 0)
        == seed_count,
        "poor_model_fit_abstains": result["mandatory_poor_fit_withheld"] == seed_count,
    }
    result["gates"] = gates
    result["passed"] = all(gates.values())
    return cast(dict[str, JsonValue], result)

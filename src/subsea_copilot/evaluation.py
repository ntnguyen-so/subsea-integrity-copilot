"""Evaluation-only truth; never imported by the detector or agents."""

from __future__ import annotations

import random
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypedDict, cast

import numpy as np
from pydantic import JsonValue

from .diagnostics import analyze_window
from .ingest import CanonicalBuffer, normalize_records
from .synthetic import SOURCE_VERSION, generate_scenario
from .warning import monitoring_warning

EXPECTED = {
    "S1": "suspected_leak",
    "S2": "sensor_or_telemetry_issue",
    "S3": "insufficient_evidence",
    "S4": "insufficient_evidence",
    "S5": "insufficient_evidence",
    "S6": "no_event",
}
HELD_OUT_SEEDS = tuple(range(91000, 91020))


class WarningTimingCase(TypedDict):
    scenario: str
    seed: int
    known_issue_onset_seconds: int | None
    expected_warning_kind: str | None
    first_expected_warning_clock_seconds: int | None
    source_onset_to_warning_seconds: int | None
    first_possible_leak_clock_seconds: int | None
    false_possible_leak_warning: bool
    mature_hypothesis: str


@dataclass(frozen=True)
class EvaluationTruth:
    hypothesis: str
    leak_segment: str | None
    leak_chainage_m: float | None
    faulty_channels: tuple[tuple[str, str], ...]


def evaluation_truth(scenario: str, seed: int) -> EvaluationTruth:
    rng = random.Random(seed)
    rng.uniform(0.8, 1.25)
    rng.uniform(1.3, 1.8)
    rng.uniform(100, 130)
    chainage = rng.choice([375.0, 400.0, 425.0])
    faults: tuple[tuple[str, str], ...] = ()
    if scenario == "S1":
        faults = (("P3-ST4-A", "pressure"),)
    elif scenario == "S2":
        faults = tuple(
            (sensor, "pressure")
            for sensor in (
                "P1-ST2-A",
                "P1-ST1-A",
                "P2-ST2-A",
                "P3-ST4-A",
                "P1-ST4-A",
                "P2-ST4-A",
                "P3-ST3-A",
            )
        )
    return EvaluationTruth(
        EXPECTED[scenario],
        "P1" if scenario in {"S1", "S5"} else None,
        chainage if scenario in {"S1", "S5"} else None,
        faults,
    )


def evaluate(seeds: tuple[int, ...] = HELD_OUT_SEEDS) -> dict[str, Any]:
    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    alert_baseline: dict[str, Counter[str]] = defaultdict(Counter)
    widths = []
    contained = located = false_positive = detected = 0
    fault_tp = fault_fp = fault_fn = 0
    elapsed = []
    started = time.perf_counter()
    for scenario in EXPECTED:
        for seed in seeds:
            data = generate_scenario(scenario, seed, duration_seconds=180)
            truth = evaluation_truth(scenario, seed)
            baseline = normalize_records(data.baseline, data.pack)
            rows = normalize_records(data.records, data.pack)
            before = time.perf_counter()
            result = analyze_window(data.pack, baseline, rows, f"eval-{seed}", 180, 185, data.epoch)
            elapsed.append(time.perf_counter() - before)
            actual = result.event.hypothesis
            confusion[scenario][actual] += 1
            alert_baseline[scenario][
                "anomaly_alert"
                if any(f.anomaly_count for f in result.quality.findings)
                else "no_alert"
            ] += 1
            detected += scenario == "S1" and actual == "suspected_leak"
            false_positive += scenario not in {"S1", "S5"} and actual == "suspected_leak"
            if scenario in {"S1", "S2"}:
                predicted = {
                    (f.sensor_id, f.channel)
                    for f in result.quality.findings
                    if f.spike_count
                    or f.drift_suspected
                    or f.peer_disagreement
                    or f.hard_excluded
                    or f.missing > f.expected * 0.1
                }
                expected = set(truth.faulty_channels)
                fault_tp += len(predicted & expected)
                fault_fp += len(predicted - expected)
                fault_fn += len(expected - predicted)
            fit = result.location
            if scenario == "S1" and fit and fit.status == "located":
                located += 1
                assert truth.leak_chainage_m is not None
                assert fit.inspection_start_m is not None and fit.inspection_end_m is not None
                contained += bool(
                    fit.best
                    and fit.best.segment_id == truth.leak_segment
                    and fit.inspection_start_m <= truth.leak_chainage_m <= fit.inspection_end_m
                )
                widths.append(fit.inspection_end_m - fit.inspection_start_m)
    gates = {
        "all_scenarios_match_expected_investigation": all(
            confusion[scenario].get(EXPECTED[scenario], 0) == len(seeds) for scenario in EXPECTED
        ),
        "no_non_leak_false_leak_conclusions": false_positive == 0,
        "detectable_leak_recall_at_least_90_percent": detected >= len(seeds) * 0.9,
        "inspection_interval_contains_true_section_at_least_90_percent": (
            contained >= len(seeds) * 0.9
        ),
        "operating_change_not_called_localized_leak": (
            confusion["S4"].get("insufficient_evidence", 0) == len(seeds)
        ),
        "poor_coverage_abstains": confusion["S5"].get("insufficient_evidence", 0) == len(seeds),
    }
    return {
        "source_version": SOURCE_VERSION,
        "method": "Frozen lightweight median/MAD; one mature [120,180) window per run",
        "seeds": list(seeds),
        "runs_per_scenario": len(seeds),
        "confusion_by_scenario": {key: dict(value) for key, value in confusion.items()},
        "per_sensor_alert_baseline": {key: dict(value) for key, value in alert_baseline.items()},
        "leak_precision": detected / (detected + false_positive)
        if detected + false_positive
        else None,
        "detectable_leak_recall": detected / len(seeds) if seeds else None,
        "inspection_intervals": {
            "located": located,
            "denominator": len(seeds),
            "truth_contained": contained,
            "median_width_m": float(np.median(widths)) if widths else None,
            "abstentions": len(seeds) - located,
            "meaning": "Recommended search areas, not predicted exact source points",
        },
        "fault_attribution": {
            "true_positive": fault_tp,
            "false_positive": fault_fp,
            "false_negative": fault_fn,
            "precision": fault_tp / (fault_tp + fault_fp) if fault_tp + fault_fp else None,
            "recall": fault_tp / (fault_tp + fault_fn) if fault_tp + fault_fn else None,
        },
        "timing": {
            "window_compute_p95_seconds": float(np.percentile(elapsed, 95)),
            "total_seconds": time.perf_counter() - started,
        },
        "limitations": [
            "Synthetic pressure footprints, not a validated gas transient model",
            "No live valve/compressor or customer detector connector",
            "Interval containment is not calibrated confidence or field localization accuracy",
            "Recall excludes S5's deliberately unobservable leak; its abstentions are reported",
            "Mature-window compute time is not onset-to-operator latency",
        ],
        "gates": gates,
        "passed": all(gates.values()),
    }


def evaluate_diagnostics(seed_count: int = 20) -> dict[str, JsonValue]:
    if not 1 <= seed_count <= len(HELD_OUT_SEEDS):
        raise ValueError("seed_count must be between 1 and 20")
    return cast(dict[str, JsonValue], evaluate(HELD_OUT_SEEDS[:seed_count]))


def evaluate_warning_timeliness(seed_count: int = 3) -> dict[str, JsonValue]:
    """Arrival-gated sliding windows; source-time delay is not wall-clock delivery."""
    if not 1 <= seed_count <= len(HELD_OUT_SEEDS):
        raise ValueError("seed_count must be between 1 and 20")
    expected_kinds = {
        "S1": "possible_leak",
        "S2": "sensor_telemetry",
        "S3": "coverage_lost",
        "S4": "unresolved",
        "S5": "coverage_lost",
        "S6": None,
    }
    cases: list[WarningTimingCase] = []
    compute_seconds = []
    for scenario in EXPECTED:
        for seed in HELD_OUT_SEEDS[:seed_count]:
            data = generate_scenario(scenario, seed, duration_seconds=180)
            baseline = normalize_records(data.baseline, data.pack)
            arrivals = [
                (
                    datetime.fromisoformat(row.received_at.replace("Z", "+00:00")) - data.epoch
                ).total_seconds()
                for row in data.records
            ]
            buffer = CanonicalBuffer(data.pack)
            released = 0
            first: int | None = None
            first_leak: int | None = None
            false_leak = False
            onset = 0 if scenario == "S2" else 90
            for endpoint in range(data.pack.hop_seconds, 181, data.pack.hop_seconds):
                clock = endpoint + data.pack.lateness_seconds
                previous = released
                while released < len(arrivals) and arrivals[released] <= clock:
                    released += 1
                buffer.ingest(data.records[previous:released])
                started = time.perf_counter()
                snapshot = analyze_window(
                    data.pack,
                    baseline,
                    buffer.observations(),
                    f"warning-{scenario}-{seed}",
                    endpoint,
                    clock,
                    data.epoch,
                )
                warning = monitoring_warning(snapshot)
                compute_seconds.append(time.perf_counter() - started)
                if warning.kind == expected_kinds[scenario] and clock >= onset and first is None:
                    first = clock
                if warning.kind == "possible_leak":
                    if scenario not in {"S1", "S5"} or clock < onset:
                        false_leak = True
                    elif first_leak is None:
                        first_leak = clock
            cases.append(
                {
                    "scenario": scenario,
                    "seed": seed,
                    "known_issue_onset_seconds": None if scenario == "S6" else onset,
                    "expected_warning_kind": expected_kinds[scenario],
                    "first_expected_warning_clock_seconds": first,
                    "source_onset_to_warning_seconds": first - onset if first is not None else None,
                    "first_possible_leak_clock_seconds": first_leak,
                    "false_possible_leak_warning": false_leak,
                    "mature_hypothesis": snapshot.event.hypothesis,
                }
            )
    delays = [
        delay for row in cases if (delay := row["source_onset_to_warning_seconds"]) is not None
    ]
    leak_cases = [row for row in cases if row["scenario"] in {"S1", "S5"}]
    warned_leaks = sum(row["first_possible_leak_clock_seconds"] is not None for row in leak_cases)
    gates = {
        "expected_warnings_within_120_source_seconds": all(
            row["source_onset_to_warning_seconds"] is not None
            and row["source_onset_to_warning_seconds"] <= 120
            for row in cases
            if row["expected_warning_kind"] is not None
        ),
        "no_false_possible_leak_warnings": not any(
            row["false_possible_leak_warning"] for row in cases
        ),
        "mature_outcomes_preserved": all(
            row["mature_hypothesis"] == EXPECTED[row["scenario"]] for row in cases
        ),
        "unobservable_leaks_explicitly_warn_about_coverage": all(
            row["first_expected_warning_clock_seconds"] is not None
            and row["first_possible_leak_clock_seconds"] is None
            for row in cases
            if row["scenario"] == "S5"
        ),
    }
    return cast(
        dict[str, JsonValue],
        {
            "source_version": SOURCE_VERSION,
            "method": "Sequential 5s hops; arrival-gated normalization; no model calls",
            "seeds": list(HELD_OUT_SEEDS[:seed_count]),
            "cases": cases,
            "source_warning_delay_p50_seconds": float(np.percentile(delays, 50)),
            "source_warning_delay_p95_seconds": float(np.percentile(delays, 95)),
            "compute_p95_seconds": float(np.percentile(compute_seconds, 95)),
            "all_truth_leak_cases": len(leak_cases),
            "truth_leak_cases_with_possible_leak_warning": warned_leaks,
            "all_truth_leak_case_recall": warned_leaks / len(leak_cases),
            "gates": gates,
            "passed": all(gates.values()),
            "limitations": [
                "Synthetic source delay/local compute, not physical-sensor-to-operator latency",
                "S2 faults start at zero, including warm-up; other issues start at 90",
                "S5 remains in the all-truth leak denominator despite correct abstention",
                "Repeated windows and authored cases are not independent field observations",
                "No load, network, human acknowledgement or hydraulic validation",
            ],
        },
    )

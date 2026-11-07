"""Pure ground-truth scoring; no LLM, detector or runtime inference imports."""

from __future__ import annotations

import math
from typing import Any


def proportion(successes: int, total: int) -> dict[str, Any]:
    if not total:
        return {"value": None, "numerator": successes, "denominator": 0, "wilson95": None}
    p, z = successes / total, 1.959963984540054
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    spread = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return {
        "value": p,
        "numerator": successes,
        "denominator": total,
        "wilson95": [max(0, center - spread), min(1, center + spread)],
    }


def detection_metrics(truth: set[Any], predicted: set[Any]) -> dict[str, Any]:
    tp, fp, fn = len(truth & predicted), len(predicted - truth), len(truth - predicted)
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": proportion(tp, tp + fp),
        "recall": proportion(tp, tp + fn),
        "f1": {"value": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None},
    }


def score_report(report: dict[str, Any]) -> dict[str, Any]:
    rows = [row for row in report["cases"] if row["status"] in {"completed", "failed"}]
    leaks, predicted_leaks, faults, predicted_faults = set(), set(), set(), set()
    pipelines: set[tuple[str, str]] = set()
    predicted_pipelines: set[tuple[str, str]] = set()
    sensor_truth: set[tuple[str, str]] = set()
    sensor_predictions: set[tuple[str, str]] = set()
    typed_truth: set[tuple[str, str, str]] = set()
    typed_predictions: set[tuple[str, str, str]] = set()
    pressure_truth: set[tuple[str, str]] = set()
    pressure_predictions: set[tuple[str, str]] = set()
    missing_truth: set[tuple[str, str]] = set()
    missing_predictions: set[tuple[str, str]] = set()
    localization_hits = 0
    errors: list[float] = []
    widths: list[float] = []
    reports, judged, withheld, negative_cases, controls = 0, 0, 0, 0, 0
    for row in rows:
        identity, truth = row["case_id"], row["truth"]
        mapping = (row.get("extraction") or {}).get("mapping")
        source = truth["leak_source"]
        if source:
            leaks.add(identity)
            pipelines.add((identity, source["segment_id"]))
        if truth["instrumentation_concern"]:
            faults.add(identity)
        if mapping:
            if mapping["leaks"]:
                predicted_leaks.add(identity)
                predicted_pipelines.update(
                    (identity, item["segment_id"]) for item in mapping["leaks"]
                )
            if mapping["instrumentation_concern"]:
                predicted_faults.add(identity)
        if truth["pressure_trigger"]:
            typed_truth.update(
                (identity, item["sensor_id"], item["kind"]) for item in truth["sensor_issues"]
            )
            sensor_truth.update(
                (identity, item["sensor_id"])
                for item in truth["sensor_issues"]
                if item["kind"] != "missing"
            )
            if mapping:
                typed_predictions.update(
                    (identity, item["sensor_id"], item["kind"]) for item in mapping["sensor_issues"]
                )
                sensor_predictions.update(
                    (identity, item["sensor_id"])
                    for item in mapping["sensor_issues"]
                    if item["kind"] != "missing"
                )
            reports += int(row.get("accepted_report", False))
            judged += int((row.get("judge") or {}).get("passed", False))
        else:
            controls += int(row.get("root_count") == 0 and row["status"] == "completed")
        for key, true_set, predicted_set in (
            ("pressure_anomaly_sensors", pressure_truth, pressure_predictions),
            ("missing_value_sensors", missing_truth, missing_predictions),
        ):
            true_set.update((identity, sensor) for sensor in truth[key])
            predicted_set.update(
                (identity, sensor) for sensor in row.get("detector", {}).get(key, [])
            )
        if source and mapping:
            for prediction in mapping["leaks"]:
                interval = prediction["interval"]
                if prediction["segment_id"] == source["segment_id"] and interval:
                    width = interval["end_m"] - interval["start_m"]
                    widths.append(width)
                    errors.append(
                        abs((interval["start_m"] + interval["end_m"]) / 2 - source["chainage_m"])
                    )
                    localization_hits += int(
                        interval["start_m"] <= source["chainage_m"] <= interval["end_m"]
                        and 0 < width <= 400
                    )
        if not source:
            negative_cases += 1
            withheld += int(
                row["status"] == "completed"
                and not any(item["interval"] for item in (mapping or {}).get("leaks", []))
            )
    eligible = sum(row["truth"]["pressure_trigger"] for row in rows)
    groups = {
        "leak_recognition": detection_metrics(leaks, predicted_leaks),
        "agent_pipeline_identification": detection_metrics(pipelines, predicted_pipelines),
        "instrumentation_recognition": detection_metrics(faults, predicted_faults),
        "agent_sensor_concerns": detection_metrics(sensor_truth, sensor_predictions),
        "agent_issue_types": detection_metrics(typed_truth, typed_predictions),
        "detector_pressure_anomalies": detection_metrics(pressure_truth, pressure_predictions),
        "detector_missing_values": detection_metrics(missing_truth, missing_predictions),
    }
    rates = {
        "localization_containment": proportion(localization_hits, len(leaks)),
        "accepted_report_coverage": proportion(reports, eligible),
        "judge_pass_rate": proportion(judged, eligible),
        "correct_withholding": proportion(withheld, negative_cases),
        "no_pressure_no_agent": proportion(controls, len(rows) - eligible),
    }
    core = [
        group[key]["value"]
        for name, group in groups.items()
        if not name.startswith("detector_")
        for key in ("precision", "recall", "f1")
    ] + [rate["value"] for rate in rates.values()]
    calibration = (
        bool(report.get("mapping_calibration"))
        and all(row["passed"] for row in report["mapping_calibration"])
        and bool(report.get("judge_calibration"))
        and all(
            row["status"] == "completed" and row["passed"] == row["expected_pass"]
            for row in report["judge_calibration"]
        )
    )
    unsafe = sum(
        item["assertion"] == "confirmed"
        for row in rows
        for item in (
            ((row.get("extraction") or {}).get("mapping") or {}).get("leaks", [])
            + ((row.get("extraction") or {}).get("mapping") or {}).get("sensor_issues", [])
        )
    )
    return {
        "completed_cases": len(rows),
        "groups": groups,
        "rates": rates,
        "localization_mean_midpoint_error_m": sum(errors) / len(errors) if errors else None,
        "localization_mean_width_m": sum(widths) / len(widths) if widths else None,
        "confirmed_cause_claims": unsafe,
        "calibration_passed": calibration,
        "target": 0.95,
        "target_met": bool(
            len(rows) == report["planned_cases"]
            and report.get("implementation_unchanged", False)
            and calibration
            and unsafe == 0
            and core
            and all(value is not None and value > 0.95 for value in core)
        ),
        "field_reliability_claim_supported": False,
    }

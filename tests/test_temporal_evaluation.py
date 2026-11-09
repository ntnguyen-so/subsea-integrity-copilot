"""Require fresh source-matched detection and clean admitted recovery evidence.

Stale/mismatched reports and absent reviews cannot fake clearance; retained false alarms,
failed/unattempted process checks and archive gaps remain visible across suite publication.
"""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from subsea_copilot.spatial_data import spatial_dataset, spatial_truth, temporal_cases
from subsea_copilot.temporal_evaluation import (
    agent_process_metrics,
    lifecycle_metrics,
    publish_evaluation,
)


def recording() -> dict:
    recipe = temporal_cases("recovery")[1]
    sources = recipe["sources"]
    frames = []
    rows = []
    for end in (120, 150, 210, 240, 270, 300):
        source = sources[0] if end <= 150 else sources[1] if end > 240 else None
        frames.append({
            "source_seconds": end, "review_case_id": f"R2@{end}",
            "snapshot_id": f"snapshot-{end}", "input_hash": f"hash-{end}",
            "truth": {"leak_source": source},
        })
        rows.append({
            "case_id": f"R2@{end}", "network_id": "R2", "source_seconds": end,
            "snapshot_id": f"snapshot-{end}", "input_hash": f"hash-{end}",
            "status": "completed", "accepted_report": True, "root_count": 1,
            "state": "SUCCEEDED", "agent_elapsed_seconds": end,
            "extraction": {"status": "completed", "mapping": {
                "leaks": [{"segment_id": source["segment_id"]}] if source else [],
                "sensor_issues": [],
            }},
        })
    return {
        "suite": "recovery", "status": "completed", "cases": rows,
        "networks": [{"id": "R2", "name": recipe["name"], "source_labels": recipe,
                      "pack": {"window_seconds": 60}, "frames": frames}],
    }


def test_recovery_requires_a_clean_admitted_negative_and_each_event_has_its_own_detection():
    report = recording()
    result = lifecycle_metrics(report)["episodes"]
    assert len(result) == 2
    assert result[0]["first_clear_review_seconds"] == 210
    assert result[0]["clearance_delay_source_seconds"] == 60
    assert result[1]["first_fresh_correct_review_seconds"] == 270
    assert result[1]["detection_delay_source_seconds"] == 30
    for row in report["cases"][2:]:
        row.update(status="failed", accepted_report=False, error_code="deadline_exceeded")
    result = lifecycle_metrics(report)["episodes"]
    assert result[0]["first_clear_review_seconds"] is None
    assert result[0]["false_leak_recovery_windows"] == 2
    assert result[1]["first_fresh_correct_review_seconds"] is None
    assert result[1]["uncovered_active_windows"] == 2


def test_mismatched_clearance_and_old_same_branch_reports_cannot_fake_recovery_or_redetection():
    report = recording()
    report["cases"][2]["input_hash"] = "wrong-input"
    report["cases"][3].update(status="failed", accepted_report=False)
    result = lifecycle_metrics(report)["episodes"][0]
    assert result["first_clear_review_seconds"] is None
    assert result["false_leak_recovery_windows"] == 2
    report = recording()
    report["networks"][0]["source_labels"]["sources"][1]["segment_id"] = "P5"
    for row in report["cases"][2:]:
        row.update(status="failed", accepted_report=False)
    result = lifecycle_metrics(report)["episodes"][1]
    assert result["first_fresh_correct_review_seconds"] is None


def test_non_leak_controls_keep_unassessed_windows_and_retained_false_alarms():
    report = recording()
    network = report["networks"][0]
    network["source_labels"] = temporal_cases("non_leak")[0]
    report["cases"][0].update(status="failed", accepted_report=False)
    report["cases"][2].update(status="failed", accepted_report=False)
    result = lifecycle_metrics(report)["controls"][0]
    assert result["windows"] == 6
    assert result["unassessed_windows"] == 1
    assert result["false_leak_windows"] == 4


def test_agent_process_counts_failed_and_unattempted_reviews_without_inventing_audit_passes():
    report = recording()
    report["cases"][0]["agent_audit"] = {"checks": {"persisted_results_revalidated": True}}
    report["cases"][1].update(
        status="failed", state="FAILED", accepted_report=False, error_code="deadline_exceeded",
        agent_audit={"checks": {"persisted_results_revalidated": False}},
    )
    report["cases"].append({"case_id": "not-dispatched", "force_review": True, "root_count": 0})
    metrics = agent_process_metrics(report)
    assert metrics["attempted_reviews"] == 6
    assert metrics["planned_agent_reviews"] == 7
    assert metrics["not_attempted_reviews"] == 1
    assert metrics["mapped_reports"] == 5
    assert metrics["timeouts"] == 1
    assert metrics["p50_wall_seconds"] == 225
    assert metrics["p95_wall_seconds"] == 300
    assert metrics["checks"]["persisted_results_revalidated"] == {
        "label": "Evidence-reference validation", "passed": 1, "failed": 1,
        "not_recorded": 4, "denominator": 6,
    }


@pytest.mark.parametrize("suite", ["recovery", "non_leak"])
def test_frozen_datasets_recover_and_never_expose_source_labels_to_the_runtime(suite):
    from subsea_copilot.replay_sources import source_payload

    for recipe in temporal_cases(suite):
        dataset = spatial_dataset(recipe, 1234, "northsea")
        assert set(source_payload(dataset)) == {"pack", "baseline", "records", "epoch"}
        if suite == "non_leak":
            assert all(spatial_truth(recipe, dataset, end)["leak_source"] is None
                       for end in range(60, 361, 5))
            assert not spatial_truth(recipe, dataset, 300)["sensor_issues"]
        else:
            assert spatial_truth(recipe, dataset, 120)["leak_source"]["segment_id"] == "P5"
            assert spatial_truth(recipe, dataset, 220)["leak_source"] is None
            if recipe["id"] == "R2":
                assert spatial_truth(recipe, dataset, 270)["leak_source"]["segment_id"] == "P6"
        assert all(row.value != "not-a-pressure" for row in dataset.records
                   if row.source_record_id.startswith("measurement:300:"))


def test_publishing_suites_preserves_the_original_cohort(tmp_path):
    current = {"version": "spatial-evaluation-v1", "suite": "current",
               "status": "completed", "run_id": "original", "cases": [{"original": True}]}
    path = tmp_path / "public.json"
    publish_evaluation(current, path)
    recovery = {**recording(), "run_id": "recovery-attempt"}
    publish_evaluation(recovery, path)
    controls = {**deepcopy(recovery), "suite": "non_leak", "run_id": "control-attempt"}
    publish_evaluation(controls, path)
    published = json.loads(path.read_text())
    assert published["cases"] == current["cases"]
    assert published["run_id"] == "original"
    assert {item["suite"] for item in published["additional_evaluations"]} == {
        "recovery", "non_leak",
    }
    publish_evaluation({**current, "run_id": "new-current"}, path)
    assert len(json.loads(path.read_text())["additional_evaluations"]) == 2


def test_recovery_changes_actual_pressures_and_second_event_moves_to_the_new_branch():
    recipe = temporal_cases("recovery")[1]
    quiet = {**deepcopy(recipe), "sources": []}
    dataset = spatial_dataset(recipe, 1234, "northsea")
    baseline = {
        row.source_record_id: row for row in spatial_dataset(quiet, 1234, "northsea").records
    }
    deficits = {}
    for row in dataset.records:
        second = int(row.source_record_id.split(":")[1])
        if second not in {130, 220, 280}:
            continue
        factor = {"bar": 1, "kPa": 0.01, "MPa": 10}[row.unit]
        deficit = (float(baseline[row.source_record_id].value) - float(row.value)) * factor
        deficits.setdefault((second, row.sensor_id.split("-")[0]), []).append(deficit)
    assert max(deficits[130, "P5"]) > 1
    assert max(abs(value) for (second, _), values in deficits.items()
               if second == 220 for value in values) == 0
    assert max(deficits[280, "P6"]) > 1
    assert max(deficits[280, "P5"]) < 0.3


@pytest.mark.parametrize("missing_archive", [False, True])
def test_archived_agent_audit_preserves_original_cases_and_discloses_missing_receipts(
    tmp_path, monkeypatch, missing_archive,
):
    from types import SimpleNamespace

    from subsea_copilot import operations_evaluation, reference_evaluation
    from subsea_copilot.config import Settings
    from subsea_copilot.store import ScopeError, Store
    from subsea_copilot.temporal_evaluation import run_agent_evaluation

    source = {**recording(), "run_id": "original", "version": "spatial-evaluation-v1"}
    source["cases"] = source["cases"][:1]
    source["cases"][0].update(
        tenant_id="recorded-tenant", root_id="recorded-root", agent_audit={"original": True},
    )
    path = tmp_path / "public.json"
    path.write_text(json.dumps(source))
    monkeypatch.setattr(reference_evaluation, "PUBLIC_REPORT", path)
    monkeypatch.setattr(Settings, "from_env", lambda: SimpleNamespace(
        database_dsn="unused", tools_dsn="unused", site_id="northsea",
    ))
    monkeypatch.setattr(Store, "__init__", lambda *args, **kwargs: None)
    monkeypatch.setattr(Store, "__enter__", lambda self: self)
    monkeypatch.setattr(Store, "__exit__", lambda *args: None)
    monkeypatch.setattr(Store, "get_task", lambda *args: "archived-root")
    monkeypatch.setattr(Store, "get_window", lambda *args: SimpleNamespace(input_hash="hash-120"))

    def audit(*args):
        if missing_archive:
            raise ScopeError("Missing recorded receipts")
        return {"checks": {"persisted_results_revalidated": True},
                "validation_errors": [], "critic_decisions": ["accept"]}

    monkeypatch.setattr(operations_evaluation, "audit_operations", audit)
    result = run_agent_evaluation(tmp_path / "audit")
    published = json.loads(path.read_text())
    assert published["cases"] == source["cases"]
    assert published["run_id"] == "original"
    assert "agent_process_audit" not in published
    assert "agent_process" not in published
    check = result["agent_process"]["checks"]["persisted_results_revalidated"]
    assert check["passed"] == (0 if missing_archive else 1)
    assert check["not_recorded"] == (1 if missing_archive else 0)
    if missing_archive:
        assert result["cases"][0]["agent_audit_error"]


@pytest.mark.parametrize("release_reader", [False, True])
def test_report_publication_retries_transient_windows_locks_but_propagates_persistent_errors(
    tmp_path, monkeypatch, release_reader,
):
    from pathlib import Path

    from subsea_copilot import reference_evaluation

    path = tmp_path / "public.json"
    reference_evaluation.write_report(path, {"original": True})
    replace = Path.replace
    attempts = []
    sleeps = []

    def locked_replace(temporary, target):
        attempts.append(target)
        if len(attempts) <= 2 or not release_reader:
            error = PermissionError("Windows reader holds this file")
            error.winerror = 5
            raise error
        return replace(temporary, target)

    monkeypatch.setattr(Path, "replace", locked_replace)
    monkeypatch.setattr(reference_evaluation.time, "sleep", sleeps.append)
    if release_reader:
        reference_evaluation.write_report(path, {"new": True})
        assert json.loads(path.read_text()) == {"new": True}
        assert len(attempts) == 3
    else:
        with pytest.raises(PermissionError):
            reference_evaluation.write_report(path, {"new": True})
        assert json.loads(path.read_text()) == {"original": True}
        assert len(attempts) == 5
    assert len(sleeps) == len(attempts) - 1

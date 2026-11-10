"""Ensure saved reports keep their exact evidence basis and retain real failures."""

from datetime import timedelta

import pytest
from pydantic import ValidationError
from test_agents import snapshot as snapshot_fixture

from subsea_copilot import playback
from subsea_copilot.casefile import InvestigationCase
from subsea_copilot.contracts import AgentResult, AgentTask, utc_now
from subsea_copilot.playback import (
    RecordedTrace,
    Recording,
    RecordingLibrary,
    load_library,
    save_library,
)
from subsea_copilot.synthetic import generate_pack


@pytest.fixture
def recording():
    snapshot = snapshot_fixture.__wrapped__()
    pack = generate_pack(snapshot.site_id)
    snapshot = snapshot.model_copy(update={"pack_version": pack.version})
    task = AgentTask(
        id="saved", root_id="saved", site_id=snapshot.site_id,
        generation_id=snapshot.generation_id, snapshot_id=snapshot.id,
        role="operator_response", question="Where should we inspect?",
        purpose="answer_question", mode="scripted",
        state="SUCCEEDED", deadline=utc_now() + timedelta(seconds=300),
        result=AgentResult(outcome="supported", claim_refs=[], limitations=[]),
        answer="Recorded output",
    )
    file = InvestigationCase(
        task_id=task.id, generation_id=task.generation_id, snapshot_id=snapshot.id,
        question=task.question, mode=task.mode, state="SUCCEEDED",
        window_start=snapshot.window_start.isoformat(), window_end=snapshot.window_end.isoformat(),
        input_hash=snapshot.input_hash, pack_version=snapshot.pack_version,
        baseline_version=snapshot.baseline_version, parameter_version=snapshot.parameter_version,
        history_version=None, disposition="Recorded", hypothesis=None, inspection=None,
        next_action="Review", interpretation=None, checked_claims=[], limitations=[],
        sources=[], comparisons=[], steps=[], reused_task_ids=[], fresh_model_calls=1,
        fresh_tool_calls=1, recorded_elapsed_seconds=1, report_target_met=True,
    )
    return Recording(
        scenario="S1", seed=2026, dataset_sha256="a" * 64,
        pack=pack, snapshot=snapshot, task=task, children=[], casefile=file,
    )


def test_recording_roundtrip_keeps_source_time_and_excludes_execution_tokens(recording, tmp_path):
    path = tmp_path / "recordings.json"
    save_library(path, RecordingLibrary(recordings=[recording]))
    saved = load_library(path).recordings[0]
    assert saved.snapshot == recording.snapshot
    assert saved.summary()["source_seconds"] == recording.snapshot.end_seconds
    assert "lease_token" not in saved.public_detail()["detail"]["task"]


def test_library_writer_and_reader_share_utf8_size_bound_without_replacing_prior_data(
    recording, tmp_path, monkeypatch,
):
    task = recording.task.model_copy(update={"answer": "Recorded output \u03bb"})
    library = RecordingLibrary(recordings=[recording.model_copy(update={"task": task})])
    payload = library.model_dump_json()
    size = len(payload.encode("utf-8"))
    assert size > len(payload)
    path = tmp_path / "recordings.json"
    monkeypatch.setattr(playback, "RECORDING_LIBRARY_MAX_BYTES", size)
    save_library(path, library)
    assert load_library(path) == library
    before = path.read_bytes()
    monkeypatch.setattr(playback, "RECORDING_LIBRARY_MAX_BYTES", size - 1)
    with pytest.raises(ValueError, match="exceeds its size bound"):
        save_library(path, library)
    assert path.read_bytes() == before
    assert not path.with_suffix(".pending").exists()
    with pytest.raises(ValueError, match="exceeds its size bound"):
        load_library(path)


@pytest.mark.parametrize("field,value", [
    ("input_hash", "foreign"), ("snapshot_id", "foreign"), ("pack_version", "foreign"),
])
def test_recording_cannot_mix_an_answer_with_another_evidence_basis(recording, field, value):
    changed = recording.model_dump()
    changed["casefile"][field] = value
    with pytest.raises(ValidationError, match="immutable investigation basis"):
        Recording.model_validate(changed)


def test_library_rejects_duplicate_trials_and_malformed_files(recording, tmp_path):
    with pytest.raises(ValidationError, match="Duplicate"):
        RecordingLibrary(recordings=[recording, recording])
    path = tmp_path / "recordings.json"
    path.write_text('{"recordings": "broken"}')
    with pytest.raises(ValidationError):
        load_library(path)


def test_failed_recording_preserves_the_failure_without_an_accepted_report(recording, tmp_path):
    failed = recording.model_copy(update={
        "task": recording.task.model_copy(update={
            "state": "FAILED", "result": None, "answer": None,
            "error_code": "grounding_rejected",
        }),
        "casefile": None,
    })
    path = tmp_path / "terminal-recordings.json"
    save_library(path, RecordingLibrary(recordings=[failed]))
    saved = load_library(path).recordings[0]
    assert saved.base_playback_speed == 5
    assert saved.public_detail()["detail"]["casefile"] is None
    assert saved.public_detail()["detail"]["task"]["error_code"] == "grounding_rejected"


def test_successful_recording_requires_its_accepted_report(recording):
    payload = recording.model_dump()
    payload["casefile"] = None
    with pytest.raises(ValidationError, match="immutable investigation basis"):
        Recording.model_validate(payload)


@pytest.mark.parametrize("field,value", [
    ("task_id", "another-run"), ("snapshot_id", "another-window"), ("trace_id", "not-a-trace"),
])
def test_recorded_trace_must_retain_its_own_run_identity(recording, field, value):
    payload = recording.model_dump()
    payload["trace_metadata"] = {
        "task_id": recording.task.id, "snapshot_id": recording.snapshot.id,
        "trace_id": "a" * 32, field: value,
    }
    with pytest.raises(ValidationError):
        Recording.model_validate(payload)


def test_original_trace_survives_export_without_saving_a_viewer_or_credentials(recording, tmp_path):
    trace = RecordedTrace(
        task_id=recording.task.id, snapshot_id=recording.snapshot.id,
        trace_id="a" * 32, span_id="b" * 16, trace_layout="investigation-v1",
    )
    saved = recording.model_copy(update={"trace_metadata": trace})
    path = tmp_path / "traced-recording.json"
    save_library(path, RecordingLibrary(recordings=[saved]))
    assert load_library(path).recordings[0].trace_metadata == trace

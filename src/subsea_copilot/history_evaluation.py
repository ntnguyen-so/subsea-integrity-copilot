"""A declared fixed policy using the same scoped records; no LLM or fake live receipts."""

from typing import Any

from subsea_copilot.contracts import AgentResult, AgentTask, HistoryInvestigation, WindowSnapshot
from subsea_copilot.history import read_history
from subsea_copilot.investigation import validate_investigation
from subsea_copilot.synthetic import generate_pack
from subsea_copilot.validation import ValidationError

EXPECTED_CONTEXTS = {
    "S1": {"unresolved"},
    "S2": {"instrumentation_context"},
    "S4": {"operating_change_plausible"},
    "S5": {"unresolved", "instrumentation_context"},
}


def history_answer_supported(scenario: str, result: AgentResult | None, state: str) -> bool:
    if result is None or result.investigation is None:
        return False
    review = result.investigation
    if review.assessment not in EXPECTED_CONTEXTS[scenario]:
        return False
    return scenario != "S5" or (
        state == "ABSTAINED"
        and result.outcome == "insufficient_evidence"
        and result.hypothesis is None
        and review.next_action == "restore_telemetry"
    )


class FixedReader:
    def __init__(self, store: Any):
        self.store = store
        self.reads: list[dict[str, Any]] = []

    def get_replay(self, identifier: str) -> Any:
        return self.store.get_replay(identifier)

    def history_documents(self, *args: Any, **kwargs: Any) -> Any:
        return self.store.history_documents(*args, **kwargs)

    def observations(self, *args: Any, **kwargs: Any) -> Any:
        return self.store.observations(*args, **kwargs)

    def tool_receipts(self, _: str) -> list[dict[str, Any]]:
        return self.reads


def fixed_history_baseline(
    store: Any,
    diagnosis: AgentTask,
    snapshot: WindowSnapshot,
    *,
    quality_aware: bool = False,
) -> dict[str, Any]:
    reader = FixedReader(store)

    def read(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        arguments = {"intent": "seek_counterevidence", **arguments}
        result = read_history(
            reader,
            diagnosis,
            snapshot,
            name,
            arguments,
        )
        reader.reads.append(
            {
                "call_id": f"fixed-policy-{len(reader.reads) + 1}",
                "name": name,
                "arguments": arguments,
                "result": result,
                "error": None,
            }
        )
        return result

    found = read(
        "history.search",
        {
            "query": "pressure OR sensor OR valve OR gateway",
            "asset_ids": ["northsea"],
        },
    )
    ids = [row["id"] for row in found["documents"] if row["admissible"]][:3]
    documents = read("history.read", {"document_ids": ids})["documents"] if ids else []
    pack = generate_pack(snapshot.site_id)
    # A reasonable fixed baseline spans all segments rather than an intentionally weak pair.
    sensors = [
        next(sensor.id for sensor in pack.sensors if sensor.segment_id == segment.id)
        for segment in pack.segments
    ]
    if quality_aware:
        concerns = {
            f.sensor_id
            for f in snapshot.quality.findings
            if f.spike_count
            or f.drift_suspected
            or f.peer_disagreement
            or f.hard_excluded
            or f.missing > f.expected * 0.1
        }
        selected = []
        for segment in pack.segments:
            sensor = next(
                (s for s in pack.sensors if s.segment_id == segment.id and s.id in concerns), None
            )
            if sensor:
                selected.append(sensor.id)
        if selected:
            sensors = list(dict.fromkeys([*selected, *sensors]))[:4]
    split = snapshot.end_seconds // 2
    comparison = read(
        "history.compare",
        {
            "sensor_ids": sensors,
            "start_seconds": 0,
            "split_seconds": split,
            "end_seconds": snapshot.end_seconds,
        },
    )
    assert diagnosis.result is not None
    assessment = "unresolved"
    guard_error = None
    for candidate in ("operating_change_plausible", "instrumentation_context", "unresolved"):
        proposed = diagnosis.result.model_copy(deep=True)
        proposed.investigation = HistoryInvestigation(
            assessment=candidate,
            document_ids=ids,
            comparison_call_ids=[reader.reads[-1]["call_id"]],
        )
        try:
            validate_investigation(proposed, diagnosis, snapshot, reader.reads)
        except ValidationError as exc:
            guard_error = exc.code
            continue
        assessment = candidate
        guard_error = None
        break
    return {
        "policy": (
            "Fixed broad query; read top three current hits; compare quality-flagged "
            "instruments spread across segments, filling with segment representatives."
            if quality_aware
            else "Fixed broad query; read top three current hits; compare first instrument "
            "on each segment across the time-range midpoint."
        ),
        "execution": (
            "Offline policy evaluation using actual scoped database reads; "
            "not a model execution or production receipt."
        ),
        "assessment": assessment,
        "document_ids": ids,
        "comparison": comparison,
        "guard_error": guard_error,
        "tool_reads": len(reader.reads),
        "receipts": reader.reads,
        "model_calls": 0,
        "document_types": [document["type"] for document in documents],
        "limitation": (
            "Controlled small corpus; not a human-effort or field-performance experiment."
        ),
    }

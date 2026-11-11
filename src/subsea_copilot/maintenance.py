"""Read-only maintenance reference catalog with the agent history's visibility rules."""

from datetime import timedelta

from pydantic import JsonValue

from .contracts import ReplaySession, content_hash, utc_now
from .history import admissible
from .history_data import EXTENDED_HISTORY_PATH, HistoryDocument, history_index_rows
from .knowledge import load_knowledge, select_knowledge
from .synthetic import EXTENDED_PACK_VERSION


def maintenance_catalog(
    replay: ReplaySession, pack_version: str, source_seconds: int,
) -> dict[str, object]:
    if not 0 <= source_seconds <= replay.duration_seconds:
        raise ValueError("Source time must be within the selected replay")
    rows = history_index_rows(
        EXTENDED_HISTORY_PATH if pack_version == EXTENDED_PACK_VERSION else None,
    )
    documents = [HistoryDocument.model_validate(row) for row in rows]
    layout_workload = (
        pack_version == EXTENDED_PACK_VERSION and replay.scenario.startswith("frozen-pressure-")
    )
    if layout_workload:
        rows = [{**row, "scenarios": [replay.scenario]} for row in rows]
    ordered = sorted(rows, key=lambda row: str(row["id"]))
    encoded: list[JsonValue] = list(ordered)
    as_of = replay.epoch + timedelta(seconds=source_seconds)
    visible = [
        document for document in documents
        if document.type == "maintenance"
        and (layout_workload or not document.scenarios or replay.scenario in document.scenarios)
        and document.available_at <= as_of
        and document.authored_at <= as_of
        and document.effective_from <= as_of
    ]
    visible.sort(key=lambda document: (
        document.status != "approved", -document.effective_from.timestamp(), document.id,
    ))
    records = []
    for document in visible:
        public = document.model_dump(mode="json")
        allowed = admissible(public, as_of)
        public["admissible"] = allowed
        public["exclusion_reason"] = None if allowed else (
            "Draft: not approved as operational authority." if document.status == "draft"
            else "Superseded revision: not current operational authority."
            if document.status == "superseded"
            else "Expired at the selected source time."
        )
        records.append(public)
    return {
        "generation_id": replay.id,
        "site_id": replay.site_id,
        "pack_version": pack_version,
        "source_seconds": source_seconds,
        "as_of": as_of.isoformat(),
        "corpus_version": content_hash(encoded),
        "records": records,
        "knowledge": select_knowledge(
            load_knowledge(), site_id=replay.site_id, pack_version=pack_version, as_of=utc_now(),
        ).model_dump(mode="json"),
    }

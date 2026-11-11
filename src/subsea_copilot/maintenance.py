"""Read-only maintenance reference catalog containing only currently effective records."""

from datetime import timedelta
from math import ceil

from pydantic import JsonValue

from .contracts import ReplaySession, content_hash, utc_now
from .history import admissible
from .history_data import (
    DEFAULT_HISTORY_PATH,
    EXTENDED_HISTORY_PATH,
    HistoryDocument,
    history_index_rows,
)
from .knowledge import DEFAULT_KNOWLEDGE_PATH, load_knowledge, select_knowledge
from .synthetic import EXTENDED_PACK_VERSION


def maintenance_catalog(
    replay: ReplaySession, pack_version: str, source_seconds: int,
) -> dict[str, object]:
    if not 0 <= source_seconds <= replay.duration_seconds:
        raise ValueError("Source time must be within the selected replay")
    history_path = (
        EXTENDED_HISTORY_PATH if pack_version == EXTENDED_PACK_VERSION else DEFAULT_HISTORY_PATH
    )
    rows = history_index_rows(history_path)
    documents = [HistoryDocument.model_validate(row) for row in rows]
    layout_workload = (
        pack_version == EXTENDED_PACK_VERSION and replay.scenario.startswith("frozen-pressure-")
    )
    if layout_workload:
        rows = [{**row, "scenarios": [replay.scenario]} for row in rows]
    ordered = sorted(rows, key=lambda row: str(row["id"]))
    encoded: list[JsonValue] = list(ordered)
    as_of = replay.epoch + timedelta(seconds=source_seconds)
    scoped = [
        document for document in documents
        if document.type == "maintenance"
        and (layout_workload or not document.scenarios or replay.scenario in document.scenarios)
    ]
    visible = [
        document for document in scoped
        if document.available_at <= as_of
        and document.authored_at <= as_of
        and document.effective_from <= as_of
    ]
    visible.sort(key=lambda document: (
        document.status != "approved", -document.effective_from.timestamp(), document.id,
    ))
    records = []
    for document in visible:
        public = document.model_dump(mode="json")
        if not admissible(public, as_of):
            continue
        public["admissible"] = True
        public["exclusion_reason"] = None
        records.append(public)
    next_times = []
    for document in scoped:
        first_time = max(document.available_at, document.authored_at, document.effective_from)
        seconds = ceil((first_time - replay.epoch).total_seconds())
        if source_seconds < seconds <= replay.duration_seconds and admissible(
            document.model_dump(mode="json"), replay.epoch + timedelta(seconds=seconds),
        ):
            next_times.append(seconds)
    return {
        "generation_id": replay.id,
        "site_id": replay.site_id,
        "source_file": "\\".join(history_path.relative_to(DEFAULT_HISTORY_PATH.parents[2]).parts),
        "knowledge_source_file": "\\".join(
            DEFAULT_KNOWLEDGE_PATH.relative_to(DEFAULT_HISTORY_PATH.parents[2]).parts,
        ),
        "scenario": replay.scenario,
        "pack_version": pack_version,
        "source_seconds": source_seconds,
        "duration_seconds": replay.duration_seconds,
        "next_effective_seconds": min(next_times, default=None),
        "as_of": as_of.isoformat(),
        "corpus_version": content_hash(encoded),
        "records": records,
        "knowledge": select_knowledge(
            load_knowledge(DEFAULT_KNOWLEDGE_PATH),
            site_id=replay.site_id, pack_version=pack_version, as_of=utc_now(),
        ).model_dump(mode="json"),
    }

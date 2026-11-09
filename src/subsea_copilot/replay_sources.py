"""Immutable measurement-only replay sources; independent of evaluation recipes/truth."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .contracts import RawRecord, ReplaySession, SitePack, content_hash
from .synthetic import ReplayDataset

FROZEN_PREFIX = "frozen-pressure-"
FROZEN_SOURCE_DIR = Path(__file__).resolve().parents[2] / "runtime" / "golden-inputs"


def source_payload(dataset: ReplayDataset) -> dict[str, Any]:
    return {
        "pack": dataset.pack.model_dump(mode="json"),
        "baseline": [row.model_dump(mode="json") for row in dataset.baseline],
        "records": [row.model_dump(mode="json") for row in dataset.records],
        "epoch": dataset.epoch.isoformat(),
    }


def freeze_replay_source(dataset: ReplayDataset) -> str:
    """Persist measurement-only inputs under their hash, excluding recipes and answer labels."""
    payload = source_payload(dataset)
    digest = content_hash(payload)
    FROZEN_SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    destination = FROZEN_SOURCE_DIR / f"{digest}.json"
    serialized = json.dumps(payload, separators=(",", ":"), allow_nan=False)
    if destination.exists():
        if content_hash(json.loads(destination.read_text(encoding="utf-8"))) != digest:
            raise ValueError("Existing frozen source failed integrity verification")
    else:
        destination.write_text(serialized, encoding="utf-8")
    return FROZEN_PREFIX + digest


def load_frozen_replay_source(session: ReplaySession) -> ReplayDataset | None:
    """Return None only for ordinary scenarios; corrupt/missing frozen inputs fail closed."""
    if not session.scenario.startswith(FROZEN_PREFIX):
        return None
    digest = session.scenario.removeprefix(FROZEN_PREFIX)
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Invalid frozen measurement source identity")
    path = FROZEN_SOURCE_DIR / f"{digest}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if content_hash(payload) != digest:
        raise ValueError("Frozen measurements changed after qualification")
    dataset = ReplayDataset(
        pack=SitePack.model_validate(payload["pack"]),
        baseline=[RawRecord.model_validate(row) for row in payload["baseline"]],
        records=[RawRecord.model_validate(row) for row in payload["records"]],
        epoch=datetime.fromisoformat(payload["epoch"]),
    )
    if dataset.pack.id != session.site_id or dataset.epoch != session.epoch:
        raise ValueError("Frozen measurement source does not match replay scope")
    return dataset

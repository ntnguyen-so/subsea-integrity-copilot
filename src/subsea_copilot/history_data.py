"""Validated fictional history; applicability is private retrieval metadata, not evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

HISTORY_SCHEMA_VERSION = "synthetic-operational-history-v1"
SYNTHETIC_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
DEFAULT_HISTORY_PATH = (
    Path(__file__).resolve().parents[2] / "fixtures" / "synthetic" / "operational-history.json"
)
EXTENDED_HISTORY_PATH = DEFAULT_HISTORY_PATH.with_name("extended-operational-history.json")

HistoryType = Literal["procedure", "maintenance", "incident", "operation"]
HistoryStatus = Literal["approved", "draft", "superseded"]

_ASSET_IDS = {
    asset
    for segment in ("P1", "P2", "P3", "P4", "P5", "P6", "P7")
    for asset in (
        segment,
        *(f"gateway-{segment}-{index}" for index in range(2)),
        *(f"{segment}-ST{station}" for station in range(1, 9)),
        *(f"{segment}-ST{station}-{side}" for station in range(1, 9) for side in ("A", "B")),
    )
} | {"northsea"}


class HistoryDocument(BaseModel):
    """One source document, retaining provenance and non-current revisions."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    type: HistoryType
    asset_ids: list[str] = Field(min_length=1)
    authored_at: AwareDatetime
    available_at: AwareDatetime
    effective_from: AwareDatetime
    effective_to: AwareDatetime | None = None
    revision: int = Field(ge=1)
    supersedes: str | None = None
    status: HistoryStatus
    body: str = Field(min_length=1)
    scenarios: list[str] = Field(default_factory=list, exclude=True, repr=False)

    @field_validator("scenarios")
    @classmethod
    def validate_scenarios(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value) or any(
            scenario not in {"S1", "S2", "S3", "S4", "S5", "S6", "S7"} for scenario in value
        ):
            raise ValueError("scenarios must be unique S1 through S7 IDs; empty means all")
        return value

    @field_validator("authored_at", "available_at", "effective_from", "effective_to")
    @classmethod
    def normalize_utc(cls, value: datetime | None) -> datetime | None:
        return value.astimezone(UTC) if value is not None else None

    @field_validator("asset_ids")
    @classmethod
    def validate_assets(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value) or any(asset not in _ASSET_IDS for asset in value):
            raise ValueError("asset_ids must be unique assets in the synthetic network")
        if "northsea" not in value:
            raise ValueError("asset_ids must include the northsea site")
        return value

    @model_validator(mode="after")
    def validate_times(self) -> HistoryDocument:
        if self.authored_at > self.available_at:
            raise ValueError("available_at must not precede authored_at")
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must follow effective_from")
        return self


HistoryRecord = HistoryDocument


class HistoryCorpus(BaseModel):
    """Versioned on-disk envelope; loading does not select current evidence."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["synthetic-operational-history-v1"]
    synthetic_epoch: AwareDatetime
    disclaimer: str = Field(min_length=1)
    records: list[HistoryDocument] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_corpus(self) -> HistoryCorpus:
        if self.synthetic_epoch != SYNTHETIC_EPOCH:
            raise ValueError("synthetic_epoch must be 2026-01-01T00:00:00Z")
        by_id = {record.id: record for record in self.records}
        if len(by_id) != len(self.records):
            raise ValueError("duplicate history record IDs")
        for record in self.records:
            if record.supersedes is None:
                continue
            previous = by_id.get(record.supersedes)
            if previous is None:
                raise ValueError(f"unknown supersedes reference: {record.supersedes}")
            if previous.type != record.type or previous.revision >= record.revision:
                raise ValueError("supersedes must reference the same type at a lower revision")
        return self


def load_history_corpus(path: str | Path | None = None) -> list[HistoryDocument]:
    """Validate the complete corpus in file order, without clock/scenario filtering."""
    source = DEFAULT_HISTORY_PATH if path is None else Path(path)
    return HistoryCorpus.model_validate_json(source.read_text(encoding="utf-8")).records


def history_index_rows(path: str | Path | None = None) -> list[dict[str, JsonValue]]:
    """Export validated JSON-compatible backend rows, including private routing metadata."""
    rows: list[dict[str, JsonValue]] = []
    for document in load_history_corpus(path):
        row: dict[str, JsonValue] = document.model_dump(mode="json")
        row["scenarios"] = [scenario for scenario in document.scenarios]
        rows.append(row)
    return rows

"""Immutable synthetic investigation recordings for presentation-only playback."""

from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .casefile import InvestigationCase
from .contracts import AgentTask, Contract, SitePack, WindowSnapshot, content_hash
from .synthetic import ReplayDataset


class Recording(Contract):
    scenario: str
    seed: int
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pack: SitePack
    snapshot: WindowSnapshot
    task: AgentTask
    children: list[AgentTask]
    casefile: InvestigationCase | None
    execution_usage: dict[str, object] | None = None
    base_playback_speed: Literal[5] = 5

    @model_validator(mode="after")
    def same_basis(self) -> "Recording":
        if (
            self.task.state not in {"SUCCEEDED", "ABSTAINED", "FAILED"}
            or self.task.parent_id is not None
            or self.task.root_id != self.task.id
            or self.task.role != "operator_response"
            or self.task.snapshot_id != self.snapshot.id
            or self.snapshot.pack_version != self.pack.version
            or self.task.generation_id != self.snapshot.generation_id
            or self.task.state == "SUCCEEDED" and (
                self.casefile is None or self.task.result is None
            )
            or self.casefile is not None and (
                self.casefile.state != self.task.state
                or self.task.id != self.casefile.task_id
                or self.casefile.snapshot_id != self.snapshot.id
                or self.casefile.input_hash != self.snapshot.input_hash
                or self.casefile.pack_version != self.pack.version
                or self.casefile.generation_id != self.snapshot.generation_id
                or self.casefile.baseline_version != self.snapshot.baseline_version
                or self.casefile.parameter_version != self.snapshot.parameter_version
                or self.task.result is None
                or self.task.result.interpretation != self.casefile.interpretation
            )
            or any(
                child.root_id != self.task.id or child.snapshot_id != self.snapshot.id
                or child.generation_id != self.task.generation_id
                for child in self.children
            )
        ):
            raise ValueError("Recording must retain one accepted immutable investigation basis")
        return self

    def summary(self) -> dict[str, object]:
        return {
            "task_id": self.task.id, "source_seconds": self.snapshot.end_seconds,
            "created_at": self.task.created_at.isoformat(), "state": self.task.state,
            "snapshot_id": self.snapshot.id, "input_hash": self.snapshot.input_hash,
        }

    def public_detail(self) -> dict[str, object]:
        fields = {
            "id", "root_id", "site_id", "generation_id", "snapshot_id", "episode_id",
            "parent_id", "role", "purpose", "question", "mode", "state", "created_at",
            "updated_at", "model_calls", "tool_calls", "plan", "result", "answer",
            "error_code", "error_message", "automatic", "interpretation_review",
        }
        return {
            "pack": self.pack.model_dump(mode="json"),
            "snapshot": self.snapshot.model_dump(mode="json"),
            "detail": {
                "task": self.task.model_dump(mode="json", include=fields),
                "children": [
                    child.model_dump(mode="json", include=fields) for child in self.children
                ],
                "casefile": self.casefile.model_dump(mode="json") if self.casefile else None,
                "receipts": [], "investigation_receipts": [], "activity": [],
                "execution_usage": self.execution_usage,
            },
        }


class RecordingLibrary(Contract):
    schema_version: str = "agent-playback-v1"
    recordings: list[Recording] = Field(max_length=500)

    @model_validator(mode="after")
    def unique_runs(self) -> "RecordingLibrary":
        if self.schema_version != "agent-playback-v1":
            raise ValueError("Unsupported recording library")
        if len({row.task.id for row in self.recordings}) != len(self.recordings):
            raise ValueError("Duplicate recorded investigation")
        return self


def load_library(path: Path) -> RecordingLibrary:
    if not path.exists():
        return RecordingLibrary(recordings=[])
    if path.is_symlink() or path.stat().st_size > 64_000_000:
        raise ValueError("Recording library is linked or exceeds its size bound")
    return RecordingLibrary.model_validate_json(path.read_text(encoding="utf-8"))


def save_library(path: Path, library: RecordingLibrary) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".pending")
    temporary.write_text(library.model_dump_json(), encoding="utf-8")
    temporary.replace(path)


def dataset_hash(dataset: ReplayDataset) -> str:
    return content_hash({
        "baseline": [row.model_dump(mode="json") for row in dataset.baseline],
        "records": [row.model_dump(mode="json") for row in dataset.records],
    })

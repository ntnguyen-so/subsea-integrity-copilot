"""Versioned advisory knowledge, distinct from measurements and incident records."""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

DEFAULT_KNOWLEDGE_PATH = (
    Path(__file__).resolve().parents[2] / "fixtures" / "knowledge" / "pressure-investigation.json"
)
ShortText = Annotated[str, Field(min_length=1, max_length=500)]
ScopeName = Annotated[str, Field(min_length=1, max_length=100)]


class KnowledgeSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference: ShortText
    locator: ShortText
    boundary: ShortText


class KnowledgeCard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^KN-[A-Z0-9-]+$", max_length=100)
    revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=120)
    kind: Literal["heuristic", "procedure"]
    roles: list[Literal["sensor_quality", "event_diagnosis", "operator_response"]] = Field(
        min_length=1, max_length=3
    )
    status: Literal["draft", "curated", "demo_curated", "retired"]
    site_ids: list[ScopeName] = Field(min_length=1, max_length=10)
    pack_versions: list[ScopeName] = Field(min_length=1, max_length=10)
    available_at: AwareDatetime
    valid_until: AwareDatetime | None = None
    supersedes: ScopeName | None = None
    conflicts_with: list[ScopeName] = Field(default_factory=list, max_length=30)
    applies_when: str = Field(min_length=1, max_length=500)
    guidance: str = Field(min_length=1, max_length=1800)
    verification_steps: list[ShortText] = Field(min_length=1, max_length=6)
    counterexamples: list[ShortText] = Field(min_length=1, max_length=4)
    limitations: list[ShortText] = Field(min_length=1, max_length=5)
    sources: list[KnowledgeSource] = Field(min_length=1, max_length=4)
    review_basis: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def validity(self) -> "KnowledgeCard":
        if self.valid_until is not None and self.valid_until <= self.available_at:
            raise ValueError("Knowledge expiry must follow availability.")
        if len(set(self.conflicts_with)) != len(self.conflicts_with):
            raise ValueError("Knowledge conflict references must be unique.")
        if self.id in self.conflicts_with or self.supersedes == self.id:
            raise ValueError("Knowledge cannot conflict with or supersede itself.")
        return self


class KnowledgeCorpus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["expert-knowledge-v1"]
    authority: Literal["advisory_only", "synthetic_advisory_only"]
    cards: list[KnowledgeCard] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def references(self) -> "KnowledgeCorpus":
        identifiers = {card.id for card in self.cards}
        if len(identifiers) != len(self.cards):
            raise ValueError("Knowledge revision IDs must be unique.")
        by_id = {card.id: card for card in self.cards}
        for card in self.cards:
            references = {*card.conflicts_with}
            if card.supersedes:
                references.add(card.supersedes)
            if not references <= identifiers:
                raise ValueError("Unresolved knowledge conflict or supersession reference.")
            if card.supersedes:
                previous = by_id[card.supersedes]
                if previous.revision >= card.revision or previous.kind != card.kind:
                    raise ValueError("Supersession requires the same kind at a higher revision.")
        return self


class KnowledgePacket(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = Field(pattern=r"^knowledge-[a-f0-9]{64}$")
    authority: Literal["advisory_only", "synthetic_advisory_only"]
    selected_at: AwareDatetime
    site_id: ScopeName
    pack_version: ScopeName
    cards: list[KnowledgeCard] = Field(max_length=24)
    excluded: dict[ScopeName, ShortText] = Field(max_length=30)
    selection_method: Literal["exact_site_version_status_time_and_declared_conflicts"] = (
        "exact_site_version_status_time_and_declared_conflicts"
    )

    @model_validator(mode="after")
    def applicable(self) -> "KnowledgePacket":
        ids = {card.id for card in self.cards}
        if len(ids) != len(self.cards) or ids & self.excluded.keys():
            raise ValueError("Selected knowledge IDs must be unique and not excluded.")
        for card in self.cards:
            if (
                card.status not in {"curated", "demo_curated"}
                or self.site_id not in card.site_ids
                or self.pack_version not in card.pack_versions
                or card.available_at > self.selected_at
                or (card.valid_until is not None and card.valid_until <= self.selected_at)
                or card.supersedes in ids
                or ids.intersection(card.conflicts_with)
            ):
                raise ValueError("Pinned knowledge must be applicable and non-conflicting.")
        if len(self.model_dump_json().encode()) > 72_000:
            raise ValueError("Knowledge packet exceeds the 72 KB reviewed context budget.")
        return self

    def identity(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json", exclude={"selected_at"}),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


def load_knowledge(path: Path = DEFAULT_KNOWLEDGE_PATH) -> KnowledgeCorpus:
    return KnowledgeCorpus.model_validate_json(path.read_text(encoding="utf-8"))


def select_knowledge(
    corpus: KnowledgeCorpus, *, site_id: str, pack_version: str, as_of: datetime
) -> KnowledgePacket:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("Knowledge selection requires an aware investigation timestamp.")
    eligible: dict[str, KnowledgeCard] = {}
    excluded = {}
    for card in corpus.cards:
        reason = (
            "not_curated"
            if card.status not in {"curated", "demo_curated"}
            else "wrong_site"
            if site_id not in card.site_ids
            else "wrong_geometry_version"
            if pack_version not in card.pack_versions
            else "not_yet_available"
            if card.available_at > as_of
            else "expired"
            if card.valid_until is not None and card.valid_until <= as_of
            else None
        )
        if reason:
            excluded[card.id] = reason
        else:
            eligible[card.id] = card
    superseded = {card.supersedes for card in eligible.values() if card.supersedes in eligible}
    for identifier in superseded:
        if identifier is not None:
            excluded[identifier] = "superseded"
            eligible.pop(identifier)
    conflicts = {
        identifier
        for card in eligible.values()
        for other in card.conflicts_with
        if other in eligible
        for identifier in (card.id, other)
    }
    for identifier in conflicts:
        excluded[identifier] = "declared_conflict_requires_expert_review"
        eligible.pop(identifier)
    if len(eligible) > 24:
        raise ValueError("Applicable knowledge exceeds the reviewed packet budget.")
    canonical = json.dumps(corpus.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return KnowledgePacket(
        version="knowledge-" + hashlib.sha256(canonical.encode()).hexdigest(),
        authority=corpus.authority,
        selected_at=as_of,
        site_id=site_id,
        pack_version=pack_version,
        cards=[card.model_copy(deep=True) for card in eligible.values()],
        excluded=excluded,
    )

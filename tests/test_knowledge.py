"""Test advisory applicability, version pinning, conflict exclusion and packet bounds."""

from datetime import UTC, datetime, timedelta

import pytest

from subsea_copilot.knowledge import KnowledgeCorpus, load_knowledge, select_knowledge

NOW = datetime(2026, 11, 7, tzinfo=UTC)


def select(corpus=None, **changes):
    return select_knowledge(
        corpus or load_knowledge(),
        **{
            "site_id": "northsea",
            "pack_version": "pressure-pack-v4-extended",
            "as_of": NOW,
            **changes,
        },
    )


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("status", "draft", "not_curated"),
        ("status", "retired", "not_curated"),
        ("site_ids", ["other"], "wrong_site"),
        ("pack_versions", ["other"], "wrong_geometry_version"),
        ("available_at", NOW + timedelta(days=1), "not_yet_available"),
        ("valid_until", NOW, "expired"),
    ],
)
def test_inapplicable_knowledge_is_withheld_with_an_explicit_reason(field, value, reason):
    corpus = load_knowledge().model_copy(deep=True)
    setattr(corpus.cards[0], field, value)
    packet = select(corpus)
    assert corpus.cards[0].id not in {card.id for card in packet.cards}
    assert packet.excluded[corpus.cards[0].id] == reason


def test_current_knowledge_is_versioned_scoped_and_not_expert_approved():
    packet = select()
    assert len(packet.cards) == 5
    assert packet.authority == "advisory_only"
    assert {card.kind for card in packet.cards} == {"heuristic", "procedure"}
    assert len(packet.model_dump_json().encode()) <= 72_000
    assert packet.version == select().version
    later = select(as_of=NOW + timedelta(seconds=1))
    assert later.selected_at != packet.selected_at
    assert later.identity() == packet.identity()
    assert all(card.sources and card.review_basis for card in packet.cards)


def test_supersession_is_scoped_and_future_revisions_do_not_retire_current_guidance():
    corpus = load_knowledge().model_copy(deep=True)
    original = corpus.cards[0]
    revision = original.model_copy(
        update={
            "id": "KN-QUALITY-R2",
            "revision": 2,
            "supersedes": original.id,
            "available_at": NOW + timedelta(days=1),
        }
    )
    corpus.cards.append(revision)
    current = select(corpus)
    assert original.id in {card.id for card in current.cards}
    later = select(corpus, as_of=NOW + timedelta(days=2))
    assert later.excluded[original.id] == "superseded"
    assert revision.id in {card.id for card in later.cards}
    assert current.identity() != later.identity()


def test_both_sides_of_a_declared_conflict_are_withheld_even_if_one_sided():
    corpus = load_knowledge().model_copy(deep=True)
    first, second = corpus.cards[:2]
    first.conflicts_with = [second.id]
    packet = select(corpus)
    assert {first.id, second.id} <= packet.excluded.keys()
    assert all("conflict" in packet.excluded[id] for id in (first.id, second.id))
    assert not {first.id, second.id}.intersection(card.id for card in packet.cards)


def test_packet_is_a_deep_snapshot_and_guidance_edits_change_its_identity():
    corpus = load_knowledge()
    packet = select(corpus)
    before = packet.model_dump_json()
    corpus.cards[0].guidance = "Changed research guidance requiring new review."
    corpus.cards[0].verification_steps.append("A new verification step.")
    assert packet.model_dump_json() == before
    assert select(corpus).version != packet.version


@pytest.mark.parametrize("broken", ["reference", "revision", "duplicate"])
def test_invalid_revision_graphs_are_rejected(broken):
    data = load_knowledge().model_dump(mode="json")
    if broken == "reference":
        data["cards"][0]["conflicts_with"] = ["KN-MISSING-R1"]
    elif broken == "revision":
        data["cards"][1]["supersedes"] = data["cards"][0]["id"]
    else:
        data["cards"].append(data["cards"][0])
    with pytest.raises(ValueError):
        KnowledgeCorpus.model_validate(data)


def test_oversized_packets_are_rejected_not_silently_truncated():
    corpus = load_knowledge()
    corpus.cards = [
        corpus.cards[0].model_copy(
            update={
                "id": f"KN-LARGE-{index}",
                "guidance": "g" * 1800,
                "verification_steps": ["v" * 500] * 6,
                "counterexamples": ["c" * 500] * 4,
                "limitations": ["l" * 500] * 5,
            }
        )
        for index in range(3)
    ]
    assert len(select(corpus).model_dump_json().encode()) > 24_000
    corpus.cards *= 3
    for index, card in enumerate(corpus.cards):
        corpus.cards[index] = card.model_copy(update={"id": f"KN-LARGE-{index}"})
    with pytest.raises(ValueError, match="72 KB"):
        select(corpus)
    corpus.cards = [
        load_knowledge().cards[0].model_copy(update={"id": f"KN-CARD-{index}"})
        for index in range(9)
    ]
    assert len(select(corpus).cards) == 9
    corpus.cards = [
        corpus.cards[0].model_copy(update={"id": f"KN-CARD-{index}"})
        for index in range(25)
    ]
    with pytest.raises(ValueError, match="packet budget"):
        select(corpus)


def test_archived_knowledge_labels_remain_readable_and_scoped():
    corpus = load_knowledge().model_copy(deep=True)
    corpus.authority = "synthetic_advisory_only"
    for card in corpus.cards:
        card.status = "demo_curated"
    packet = select(corpus)
    assert packet.authority == "synthetic_advisory_only"
    assert len(packet.cards) == 5
    assert select(corpus, site_id="other").cards == []


def test_selection_rejects_naive_timestamps_and_leaves_no_guessed_scope():
    with pytest.raises(ValueError, match="aware"):
        select(as_of=NOW.replace(tzinfo=None))
    packet = select(site_id="unreviewed-site")
    assert packet.cards == []
    assert len(packet.excluded) == 5

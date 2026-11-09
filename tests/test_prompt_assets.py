import hashlib
from dataclasses import replace

import pytest

from subsea_copilot import prompts


def test_catalog_contains_versioned_roles_and_shared_instructions_without_headers_in_messages():
    catalog = prompts.prompt_manifest()
    assert {
        "quality", "diagnosis", "response", "critic", "baseline",
        "transport", "schema-repair", "context-view", "reflection", "batch", "pressure-summary",
    } <= catalog.keys()
    assert len({asset["prompt_id"] for asset in catalog.values()}) == len(catalog)
    for name, identity in catalog.items():
        template = prompts.load_prompt(name)
        assert identity == template.provenance()
        assert template.sha256 == hashlib.sha256(template.content.encode()).hexdigest()
        assert not template.content.startswith("---")


def test_catalog_freezes_all_assets_and_version_only_changes_affect_identity(tmp_path, monkeypatch):
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text("---\nprompt_id: test.first\nversion: 1.0.0\n---\nSame body\n")
    second.write_text("---\nprompt_id: test.second\nversion: 1.0.0\n---\nOriginal second\n")
    prompts._catalog.cache_clear()
    monkeypatch.setattr(prompts, "files", lambda package: tmp_path)
    try:
        original = prompts.load_prompt("first")
        before = prompts.prompt_manifest_sha256()
        second.write_text("---\nprompt_id: test.second\nversion: 2.0.0\n---\nChanged second\n")
        assert prompts.load_prompt("second").content == "Original second\n"
        assert prompts.prompt_manifest_sha256() == before
        second.write_text("---\nprompt_id: test.second\nversion: 1.0.0\n---\nOriginal second\n")
        first.write_text("---\nprompt_id: test.first\nversion: 2.0.0\n---\nSame body\n")
        prompts._catalog.cache_clear()
        assert prompts.load_prompt("first").sha256 == original.sha256
        assert prompts.prompt_manifest_sha256() != before
    finally:
        prompts._catalog.cache_clear()


@pytest.mark.parametrize("header", [
    "---\nprompt_id: test.bad\nversion: latest\n---\nBody",
    "---\nprompt_id: test.bad\nversion: 01.0.0\n---\nBody",
    "---\nprompt_id: test.bad\nversion: 1.0.0\n---\n",
    "Unversioned instructions",
])
def test_invalid_or_empty_assets_fail_closed(header):
    with pytest.raises(ValueError):
        prompts._parse("bad", header)


def test_asset_lookup_rejects_unknown_names_and_render_does_not_reinterpret_values():
    with pytest.raises(ValueError):
        prompts.load_prompt("..\\quality")
    with pytest.raises(ValueError):
        prompts.load_prompt("unknown-asset")
    template = replace(prompts.load_prompt("quality"), content='JSON: {} {{schema}}')
    with pytest.raises(ValueError, match="missing"):
        template.render()
    with pytest.raises(ValueError, match="unknown"):
        template.render(schema="{}", misspelled="value")
    assert template.render(schema='{"literal":"{{not_a_template}}"}') == (
        'JSON: {} {"literal":"{{not_a_template}}"}'
    )


def test_catalog_rejects_duplicate_ids_eagerly(tmp_path, monkeypatch):
    for name in ("first", "second"):
        (tmp_path / f"{name}.md").write_text(
            "---\nprompt_id: test.duplicate\nversion: 1.0.0\n---\nBody\n"
        )
    prompts._catalog.cache_clear()
    monkeypatch.setattr(prompts, "files", lambda package: tmp_path)
    try:
        with pytest.raises(ValueError, match="Duplicate"):
            prompts.load_prompt("first")
    finally:
        prompts._catalog.cache_clear()


def test_caller_cannot_mutate_catalog_provenance():
    before = prompts.prompt_manifest_sha256()
    manifest = prompts.prompt_manifest()
    manifest["quality"]["version"] = "99.0.0"
    assert prompts.prompt_manifest_sha256() == before

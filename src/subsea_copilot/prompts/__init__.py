"""Code-managed, versioned prompt assets with a process-frozen catalog."""

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from types import MappingProxyType

_NAME = re.compile(r"[a-z][a-z0-9-]*\Z")
_HEADER = re.compile(
    r"\A---\nprompt_id: ([a-z][a-z0-9._-]*)\n"
    r"version: ((?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))\n---\n"
)
_TOKEN = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")


@dataclass(frozen=True)
class PromptTemplate:
    prompt_id: str
    version: str
    content: str
    sha256: str

    def render(self, **values: str) -> str:
        required = set(_TOKEN.findall(self.content))
        missing = required - values.keys()
        unknown = values.keys() - required
        if missing or unknown:
            raise ValueError(
                f"Prompt tokens do not match: missing={sorted(missing)}, unknown={sorted(unknown)}"
            )
        return _TOKEN.sub(lambda match: values[match.group(1)], self.content)

    def provenance(self) -> dict[str, str]:
        return {"prompt_id": self.prompt_id, "version": self.version, "sha256": self.sha256}


def _parse(name: str, raw: str) -> PromptTemplate:
    header = _HEADER.match(raw)
    if header is None:
        raise ValueError(f"Prompt {name!r} requires a valid prompt_id and semantic version.")
    identifier, version = header.groups()
    content = raw[header.end():]
    if not content.strip():
        raise ValueError(f"Prompt {name!r} has an empty body.")
    return PromptTemplate(
        identifier, version, content, hashlib.sha256(content.encode("utf-8")).hexdigest()
    )


@cache
def _catalog() -> Mapping[str, PromptTemplate]:
    templates: dict[str, PromptTemplate] = {}
    identifiers: set[str] = set()
    for resource in sorted(files(__package__).iterdir(), key=lambda item: item.name):
        if not resource.is_file() or not resource.name.endswith(".md"):
            continue
        name = resource.name[:-3]
        if not _NAME.fullmatch(name):
            raise ValueError(f"Invalid prompt asset name: {name!r}.")
        template = _parse(name, resource.read_text(encoding="utf-8"))
        if template.prompt_id in identifiers:
            raise ValueError(f"Duplicate prompt identity: {template.prompt_id!r}.")
        identifiers.add(template.prompt_id)
        templates[name] = template
    if not templates:
        raise ValueError("The packaged prompt catalog is empty.")
    return MappingProxyType(templates)


def load_prompt(name: str) -> PromptTemplate:
    if not _NAME.fullmatch(name):
        raise ValueError(f"Invalid prompt asset name: {name!r}.")
    catalog = _catalog()
    if name not in catalog:
        raise ValueError(f"Unknown prompt asset: {name!r}.")
    return catalog[name]


def prompt_manifest() -> dict[str, dict[str, str]]:
    return {name: template.provenance() for name, template in _catalog().items()}


def prompt_manifest_sha256() -> str:
    return hashlib.sha256(
        json.dumps(prompt_manifest(), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def prompt_catalog_provenance() -> dict[str, object]:
    return {
        "prompt_catalog": prompt_manifest(),
        "prompt_catalog_sha256": prompt_manifest_sha256(),
    }

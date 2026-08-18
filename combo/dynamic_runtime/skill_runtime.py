from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from combo.dynamic_runtime.capability_blob_store import CapabilityBlobStore
from combo.dynamic_runtime.capability_definitions import SkillContentRef, SkillDefinition
from combo.dynamic_runtime.capability_store import ActiveCapability
from combo.dynamic_runtime.content_media import is_text_media_type
from combo.runtime_protocol import CapabilityProjectionSnapshot, CapabilitySnapshot


@dataclass(frozen=True, slots=True)
class RuntimeSkill:
    name: str
    display_name: str
    description: str
    instructions: SkillContentRef
    contents: tuple[SkillContentRef, ...]


@dataclass(frozen=True, slots=True)
class RuntimeSkillEntry:
    capability_id: str
    revision: int
    definition: RuntimeSkill


@runtime_checkable
class SkillRuntime(Protocol):
    def list(self) -> list[dict[str, object]]: ...

    def describe(self, name: str) -> dict[str, object]: ...

    def load(self, name: str, *, reason: str) -> dict[str, object]: ...

    def read_resource(self, name: str, *, path: str) -> dict[str, object]: ...


class IndexedSkillRuntime:
    """Progressively disclose an explicitly bounded collection of Skills."""

    def __init__(self, *, entries: Iterable[RuntimeSkillEntry], blobs: CapabilityBlobStore) -> None:
        self._blobs = blobs
        skills: dict[str, RuntimeSkillEntry] = {}
        aliases: dict[str, str] = {}
        for entry in entries:
            skill = entry.definition
            if skill.name in skills:
                raise RuntimeError(f"Skill collection contains duplicate public name: {skill.name}")
            skills[skill.name] = entry
            for alias in (skill.name, skill.display_name, entry.capability_id):
                normalized = _lookup_key(alias)
                existing = aliases.get(normalized)
                if existing is not None and existing != skill.name:
                    raise RuntimeError(f"Skill collection contains ambiguous public alias: {alias}")
                aliases[normalized] = skill.name
        self._skills = skills
        self._aliases = aliases

    def list(self) -> list[dict[str, object]]:
        return [
            self._metadata(entry)
            for _name, entry in sorted(self._skills.items())
        ]

    def describe(self, name: str) -> dict[str, object]:
        entry = self._require(name)
        return {
            **self._metadata(entry),
            "resources": [_resource_metadata(item) for item in entry.definition.contents],
            "instructions_loaded": False,
        }

    def load(self, name: str, *, reason: str) -> dict[str, object]:
        entry = self._require(name)
        rationale = str(reason or "").strip()
        if not rationale:
            raise ValueError("Skill load requires a reason")
        return {
            **self._metadata(entry),
            "instructions": self._blobs.read_text(entry.definition.instructions),
            "resources": [_resource_metadata(item) for item in entry.definition.contents],
            "load_reason": rationale,
        }

    def read_resource(self, name: str, *, path: str) -> dict[str, object]:
        definition = self._require(name).definition
        logical_path = str(path or "").strip().replace("\\", "/")
        matches = [item for item in definition.contents if item.logical_path == logical_path]
        if len(matches) != 1:
            raise LookupError(f"Skill resource not found: {name}/{logical_path}")
        reference = matches[0]
        result = _resource_metadata(reference)
        if result["text_readable"]:
            result["content"] = self._blobs.read_text(reference)
        else:
            result["content"] = None
            result["message"] = "Binary Skill resources cannot be inserted into the model context as text."
        return result

    def _require(self, name: str) -> RuntimeSkillEntry:
        requested = str(name or "").strip()
        canonical_name = self._aliases.get(_lookup_key(requested))
        if canonical_name is None:
            raise LookupError(f"Skill is not available to this runtime: {requested}")
        return self._skills[canonical_name]

    @staticmethod
    def _metadata(entry: RuntimeSkillEntry) -> dict[str, object]:
        definition = entry.definition
        return {
            "name": definition.name,
            "display_name": definition.display_name,
            "description": definition.description,
            "capability_id": entry.capability_id,
            "revision": entry.revision,
        }


class SnapshotSkillRuntime(IndexedSkillRuntime):
    """Expose only Skills selected in one immutable runtime snapshot."""

    def __init__(self, *, snapshot: CapabilitySnapshot, blobs: CapabilityBlobStore) -> None:
        super().__init__(entries=_snapshot_skill_entries(snapshot), blobs=blobs)


class MainSkillRuntime(IndexedSkillRuntime):
    """Expose frozen selected Skills plus searchable active Skills to the main Agent."""

    def __init__(
        self,
        *,
        snapshot: CapabilitySnapshot,
        active_skills: Iterable[ActiveCapability],
        blobs: CapabilityBlobStore,
    ) -> None:
        snapshot_entries = _snapshot_skill_entries(snapshot)
        selected_ids = frozenset(entry.capability_id for entry in snapshot_entries)
        dynamic_entries = tuple(
            _active_skill_entry(item)
            for item in active_skills
            if item.revision.capability_id not in selected_ids
        )
        super().__init__(entries=(*snapshot_entries, *dynamic_entries), blobs=blobs)


def _lookup_key(value: str) -> str:
    return str(value or "").strip().casefold()


def _runtime_skill(projection: CapabilityProjectionSnapshot) -> RuntimeSkill:
    if projection.runtime_definition_schema == "skill_definition.v3":
        definition = SkillDefinition.model_validate(projection.runtime_definition)
        return RuntimeSkill(
            name=definition.name,
            display_name=definition.display_name,
            description=definition.description,
            instructions=definition.instructions,
            contents=definition.contents,
        )
    if projection.runtime_definition_schema == "skill_definition.v2":
        payload = projection.runtime_definition
        name = projection.capability_id.rsplit("/", 1)[-1]
        raw_contents = payload.get("contents")
        contents = raw_contents if isinstance(raw_contents, list) else []
        return RuntimeSkill(
            name=name,
            display_name=name,
            description="",
            instructions=SkillContentRef.model_validate(payload.get("instructions")),
            contents=tuple(
                SkillContentRef.model_validate(item)
                for item in contents
            ),
        )
    raise RuntimeError("selected Skill uses an unsupported definition schema")


def _snapshot_skill_entries(snapshot: CapabilitySnapshot) -> tuple[RuntimeSkillEntry, ...]:
    return tuple(
        RuntimeSkillEntry(
            capability_id=projection.capability_id,
            revision=projection.revision,
            definition=_runtime_skill(projection),
        )
        for projection in snapshot.projections
        if projection.kind == "skill"
    )


def _active_skill_entry(item: ActiveCapability) -> RuntimeSkillEntry:
    revision = item.revision
    if revision.kind != "skill":
        raise TypeError(f"active capability is not a Skill: {revision.capability_id}")
    if revision.content.definition_schema != "skill_definition.v3":
        raise RuntimeError("active Skill uses an unsupported definition schema")
    definition = SkillDefinition.model_validate(revision.content.definition)
    return RuntimeSkillEntry(
        capability_id=revision.capability_id,
        revision=revision.revision,
        definition=RuntimeSkill(
            name=definition.name,
            display_name=definition.display_name,
            description=definition.description,
            instructions=definition.instructions,
            contents=definition.contents,
        ),
    )


def _resource_metadata(reference: SkillContentRef) -> dict[str, object]:
    return {
        "path": reference.logical_path,
        "kind": reference.kind,
        "media_type": reference.media_type,
        "size_bytes": reference.size_bytes,
        "text_readable": _is_text_resource(reference),
    }


def _is_text_resource(reference: SkillContentRef) -> bool:
    return is_text_media_type(reference.media_type)

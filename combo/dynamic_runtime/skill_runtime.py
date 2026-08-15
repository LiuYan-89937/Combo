from __future__ import annotations

from dataclasses import dataclass

from combo.dynamic_runtime.capability_blob_store import CapabilityBlobStore
from combo.dynamic_runtime.capability_definitions import SkillContentRef, SkillDefinition
from combo.dynamic_runtime.content_media import is_text_media_type
from combo.runtime_protocol import CapabilityProjectionSnapshot, CapabilitySnapshot


@dataclass(frozen=True, slots=True)
class RuntimeSkill:
    name: str
    display_name: str
    description: str
    instructions: SkillContentRef
    contents: tuple[SkillContentRef, ...]


class SnapshotSkillRuntime:
    """Progressively disclose Skills selected in one immutable runtime snapshot."""

    def __init__(self, *, snapshot: CapabilitySnapshot, blobs: CapabilityBlobStore) -> None:
        self._blobs = blobs
        skills: dict[str, tuple[CapabilityProjectionSnapshot, RuntimeSkill]] = {}
        aliases: dict[str, str] = {}
        for projection in snapshot.projections:
            if projection.kind != "skill":
                continue
            skill = _runtime_skill(projection)
            if skill.name in skills:
                raise RuntimeError(f"runtime snapshot contains duplicate Skill name: {skill.name}")
            skills[skill.name] = (projection, skill)
            for alias in (skill.name, skill.display_name, projection.capability_id):
                normalized = _lookup_key(alias)
                existing = aliases.get(normalized)
                if existing is not None and existing != skill.name:
                    raise RuntimeError(f"runtime snapshot contains ambiguous Skill alias: {alias}")
                aliases[normalized] = skill.name
        self._skills = skills
        self._aliases = aliases

    def list(self) -> list[dict[str, object]]:
        return [
            self._metadata(projection, definition)
            for _name, (projection, definition) in sorted(self._skills.items())
        ]

    def describe(self, name: str) -> dict[str, object]:
        projection, definition = self._require(name)
        return {
            **self._metadata(projection, definition),
            "resources": [_resource_metadata(item) for item in definition.contents],
            "instructions_loaded": False,
        }

    def load(self, name: str, *, reason: str) -> dict[str, object]:
        projection, definition = self._require(name)
        rationale = str(reason or "").strip()
        if not rationale:
            raise ValueError("Skill load requires a reason")
        return {
            **self._metadata(projection, definition),
            "instructions": self._blobs.read_text(definition.instructions),
            "resources": [_resource_metadata(item) for item in definition.contents],
            "load_reason": rationale,
        }

    def read_resource(self, name: str, *, path: str) -> dict[str, object]:
        _projection, definition = self._require(name)
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

    def _require(self, name: str) -> tuple[CapabilityProjectionSnapshot, RuntimeSkill]:
        requested = str(name or "").strip()
        canonical_name = self._aliases.get(_lookup_key(requested))
        if canonical_name is None:
            raise LookupError(f"Skill is not selected for this runtime: {requested}")
        return self._skills[canonical_name]

    @staticmethod
    def _metadata(
        projection: CapabilityProjectionSnapshot,
        definition: RuntimeSkill,
    ) -> dict[str, object]:
        return {
            "name": definition.name,
            "display_name": definition.display_name,
            "description": definition.description,
            "capability_id": projection.capability_id,
            "revision": projection.revision,
        }


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
        return RuntimeSkill(
            name=name,
            display_name=name,
            description="",
            instructions=SkillContentRef.model_validate(payload.get("instructions")),
            contents=tuple(
                SkillContentRef.model_validate(item)
                for item in payload.get("contents", ())
            ),
        )
    raise RuntimeError("selected Skill uses an unsupported definition schema")


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
